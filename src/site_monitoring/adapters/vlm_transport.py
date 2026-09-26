"""Транспорт обращения к мультимодальной модели по OpenAI-совместимому API.

Поддерживает двух поставщиков: DeepSeek (по умолчанию) и Yandex Cloud AI Studio.
Различия между ними — заголовок авторизации, вид имени модели и способ потребовать
JSON — заперты в этом модуле; промпты и разбор ответов живут в вызывающих адаптерах.
"""

import json
import logging
import threading
from typing import Any

import httpx

from ..entity import VlmProvider

logger = logging.getLogger(__name__)

CHAT_COMPLETIONS_PATH = "/chat/completions"
YANDEX_MODEL_URI_TEMPLATE = "gpt://{folder_id}/{model}"
YANDEX_AUTHORIZATION_TEMPLATE = "Api-Key {api_key}"
DEEPSEEK_AUTHORIZATION_TEMPLATE = "Bearer {api_key}"
YANDEX_PROJECT_HEADER = "OpenAI-Project"
TEMPERATURE = 0.1
RETRY_TOKENS_MULTIPLIERS = (1, 2, 3)
REQUEST_TIMEOUT_SECONDS = 180.0
MAX_CONNECTIONS = 16
EMPTY_ANSWER_MESSAGE = "Модель вернула пустой ответ: бюджет токенов израсходован на рассуждения"
JSON_DIRECTIVE_TEMPLATE = (
    "\n\nВерни ответ одним объектом JSON ровно такой формы, без пояснений вокруг "
    "и без описания самой схемы:\n{shape}"
)
TEXT_PART_KEY = "text"
SCHEMA_TYPE_KEY = "type"
SCHEMA_PROPERTIES_KEY = "properties"
SCHEMA_ITEMS_KEY = "items"
SCHEMA_ENUM_KEY = "enum"
OBJECT_TYPE = "object"
ARRAY_TYPE = "array"
ENUM_SEPARATOR = " либо "
TYPE_HINTS = {
    "string": "строка",
    "boolean": "true либо false, без кавычек",
    "integer": "целое число",
    "number": "число",
}
UNKNOWN_TYPE_HINT = "значение"


def _read_answer_object(raw_answer: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Достаёт из ответа объект с полями схемы, либо ничего.

    DeepSeek иногда пишет перед ответом служебный объект вроде `{"type": "json_object"}`,
    и тогда в тексте оказывается два объекта подряд. Разбираем их по очереди
    и берём тот, где есть поля схемы. Если такого нет, решение о повторе принимает
    вызывающий: пустой ответ, мусор и объект не по схеме лечатся одинаково.
    """
    decoder = json.JSONDecoder()
    expected = set(schema.get(SCHEMA_PROPERTIES_KEY, {}))
    position = 0
    while position < len(raw_answer):
        try:
            parsed, position = decoder.raw_decode(raw_answer, position)
        except ValueError:
            break
        if isinstance(parsed, dict) and expected & set(parsed):
            return parsed
        position = _skip_separators(raw_answer, position)
    # Объект без полей схемы принимать нельзя: он разберётся в «ничего не нашли»,
    # а это не то же самое, что «на снимке ничего нет». Лучше повторить запрос.
    logger.warning("В ответе модели нет объекта с полями схемы")
    return None


def _skip_separators(raw_answer: str, position: int) -> int:
    """Сдвигает разбор к следующему объекту через пробелы и переводы строк."""
    while position < len(raw_answer) and raw_answer[position] in " \t\r\n,":
        position += 1
    return position


def render_schema_shape(schema: dict[str, Any]) -> Any:
    """Превращает JSON Schema в образец ответа с подсказками вместо значений.

    Провайдеры без строгих схем гораздо надёжнее повторяют форму готового объекта,
    чем описание схемы: на самой схеме модель отвечает обёрткой `properties`.
    """
    kind = schema.get(SCHEMA_TYPE_KEY)
    if kind == OBJECT_TYPE:
        properties = schema.get(SCHEMA_PROPERTIES_KEY, {})
        shape = {name: render_schema_shape(sub) for name, sub in properties.items()}
        return shape
    if kind == ARRAY_TYPE:
        items = [render_schema_shape(schema.get(SCHEMA_ITEMS_KEY, {}))]
        return items
    allowed = schema.get(SCHEMA_ENUM_KEY)
    if allowed:
        variants = ENUM_SEPARATOR.join(str(item) for item in allowed)
        return variants
    hint = TYPE_HINTS.get(str(kind), UNKNOWN_TYPE_HINT)
    return hint


class VlmTransport:
    """Отправляет запросы к визуально-языковой модели выбранного поставщика."""

    def __init__(
        self,
        provider: VlmProvider,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int,
        folder_id: str = "",
    ) -> None:
        self._provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._folder_id = folder_id
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()

    def complete_json(
        self,
        content: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        """Запрашивает у модели ответ в JSON и возвращает его разобранным.

        Рассуждающие модели изредка тратят весь бюджет токенов на размышления
        и возвращают пустой ответ, поэтому запрос повторяется с удвоенным лимитом.
        """
        prepared = self._prepare_content(content, schema)
        limits = tuple(self._max_tokens * factor for factor in RETRY_TOKENS_MULTIPLIERS)
        for limit in limits:
            payload = self._build_payload(prepared, schema, schema_name, limit)
            raw_answer = self._request_completion(payload)
            answer = _read_answer_object(raw_answer, schema) if raw_answer else None
            if answer is not None:
                return answer
            logger.warning("Ответ модели при лимите %d токенов не разобран, повтор", limit)
        raise ValueError(EMPTY_ANSWER_MESSAGE)

    def _prepare_content(
        self,
        content: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Дописывает схему в текст запроса там, где провайдер её не принимает.

        DeepSeek умеет только режим «ответ — объект JSON» и схему в запросе
        не принимает, поэтому в промпт уходит образец ответа, построенный по схеме.
        """
        if self._provider is not VlmProvider.DEEPSEEK:
            return content
        shape = render_schema_shape(schema)
        rendered = json.dumps(shape, ensure_ascii=False, indent=1)
        directive = JSON_DIRECTIVE_TEMPLATE.format(shape=rendered)
        prepared = [dict(part) for part in content]
        for part in prepared:
            if TEXT_PART_KEY in part:
                part[TEXT_PART_KEY] = f"{part[TEXT_PART_KEY]}{directive}"
                break
        return prepared

    def _build_payload(
        self,
        content: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Собирает тело запроса в диалекте выбранного поставщика."""
        payload = {
            "model": self._model_name(),
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
            "response_format": self._response_format(schema, schema_name),
        }
        return payload

    def _model_name(self) -> str:
        """Возвращает имя модели: у Yandex Cloud оно записывается через URI каталога."""
        if self._provider is VlmProvider.YANDEX:
            uri = YANDEX_MODEL_URI_TEMPLATE.format(folder_id=self._folder_id, model=self._model)
            return uri
        return self._model

    def _response_format(self, schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        """Возвращает требование формата ответа в понятном поставщику виде."""
        if self._provider is VlmProvider.YANDEX:
            schema_block = {"name": schema_name, "schema": schema, "strict": True}
            strict_format = {"type": "json_schema", "json_schema": schema_block}
            return strict_format
        object_format = {"type": "json_object"}
        return object_format

    def _headers(self) -> dict[str, str]:
        """Собирает заголовки авторизации поставщика."""
        if self._provider is VlmProvider.YANDEX:
            yandex_headers = {
                "Authorization": YANDEX_AUTHORIZATION_TEMPLATE.format(api_key=self._api_key),
                YANDEX_PROJECT_HEADER: self._folder_id,
            }
            return yandex_headers
        deepseek_headers = {
            "Authorization": DEEPSEEK_AUTHORIZATION_TEMPLATE.format(api_key=self._api_key),
        }
        return deepseek_headers

    def _shared_client(self) -> httpx.Client:
        """Отдаёт общий клиент: соединение переиспользуется между запросами.

        Раньше на каждый запрос поднимался свой клиент, а значит и своё TLS-рукопожатие.
        При параллельной отправке это заметная доля времени. `httpx.Client` рассчитан
        на работу из нескольких потоков, поэтому хватает одного на весь прогон.
        """
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                limits = httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_CONNECTIONS)
                self._client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, limits=limits)
        return self._client

    def _request_completion(self, payload: dict[str, Any]) -> str:
        """Отправляет запрос к модели и достаёт текст ответа."""
        url = f"{self._base_url}{CHAT_COMPLETIONS_PATH}"
        response = self._shared_client().post(url, json=payload, headers=self._headers())
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        raw_answer = message.get("content") or ""
        return raw_answer
