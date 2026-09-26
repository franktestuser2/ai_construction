"""Тесты транспорта к мультимодальной модели: диалекты двух провайдеров."""

import json

import pytest

from site_monitoring.adapters.vlm_transport import VlmTransport, render_schema_shape
from site_monitoring.entity import VlmProvider

SCHEMA = {
    "type": "object",
    "properties": {"ответ": {"type": "string"}},
    "required": ["ответ"],
}
SCHEMA_NAME = "проверка"
API_KEY = "ключ-для-теста"
MODEL = "deepseek-flash"
FOLDER_ID = "b1g-тестовый-каталог"
MAX_TOKENS = 100


def _content() -> list[dict[str, object]]:
    """Готовит тело сообщения из текста и картинки."""
    parts = [
        {"type": "text", "text": "Вопрос по снимку"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]
    return parts


def _deepseek_transport() -> VlmTransport:
    """Собирает транспорт к DeepSeek."""
    transport = VlmTransport(
        provider=VlmProvider.DEEPSEEK,
        base_url="https://api.deepseek.com",
        api_key=API_KEY,
        model=MODEL,
        max_tokens=MAX_TOKENS,
    )
    return transport


def _yandex_transport() -> VlmTransport:
    """Собирает транспорт к Yandex Cloud AI Studio."""
    transport = VlmTransport(
        provider=VlmProvider.YANDEX,
        base_url="https://ai.api.cloud.yandex.net/v1",
        api_key=API_KEY,
        model="qwen3.6-35b-a3b",
        max_tokens=MAX_TOKENS,
        folder_id=FOLDER_ID,
    )
    return transport


def test_deepseek_запрашивает_json_объект_и_вкладывает_образец_в_промпт() -> None:
    # Arrange
    transport = _deepseek_transport()
    prepared = transport._prepare_content(_content(), SCHEMA)

    # Act
    payload = transport._build_payload(prepared, SCHEMA, SCHEMA_NAME, MAX_TOKENS)

    # Assert
    text = payload["messages"][0]["content"][0]["text"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["model"] == MODEL
    assert json.dumps({"ответ": "строка"}, ensure_ascii=False, indent=1) in text
    assert "properties" not in text


def test_образец_ответа_разворачивает_вложенные_массивы_и_перечисления() -> None:
    # Arrange
    schema = {
        "type": "object",
        "properties": {
            "техника": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "обнаружена": {"type": "boolean"},
                        "статус": {"type": "string", "enum": ["работает", "простаивает"]},
                    },
                },
            },
        },
    }

    # Act
    shape = render_schema_shape(schema)

    # Assert
    assert shape == {"техника": [{"обнаружена": "true либо false, без кавычек", "статус": "работает либо простаивает"}]}


def test_deepseek_не_трогает_картинку_при_вкладывании_схемы() -> None:
    # Arrange
    transport = _deepseek_transport()
    content = _content()

    # Act
    prepared = transport._prepare_content(content, SCHEMA)

    # Assert
    assert prepared[1] == content[1]
    assert content[0]["text"] == "Вопрос по снимку"


def test_yandex_передаёт_схему_отдельным_полем_и_uri_модели() -> None:
    # Arrange
    transport = _yandex_transport()

    # Act
    payload = transport._build_payload(_content(), SCHEMA, SCHEMA_NAME, MAX_TOKENS)

    # Assert
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
    assert payload["model"] == f"gpt://{FOLDER_ID}/qwen3.6-35b-a3b"


@pytest.mark.parametrize(
    ("transport_builder", "expected_authorization", "project_header_present"),
    [
        (_deepseek_transport, f"Bearer {API_KEY}", False),
        (_yandex_transport, f"Api-Key {API_KEY}", True),
    ],
)
def test_заголовки_авторизации_различаются_по_провайдеру(
    transport_builder,
    expected_authorization: str,
    project_header_present: bool,
) -> None:
    # Arrange
    transport = transport_builder()

    # Act
    headers = transport._headers()

    # Assert
    assert headers["Authorization"] == expected_authorization
    assert ("OpenAI-Project" in headers) is project_header_present


def test_пустой_ответ_модели_приводит_к_ошибке_после_повтора(monkeypatch) -> None:
    # Arrange
    transport = _deepseek_transport()
    attempts: list[int] = []

    def _empty(payload: dict[str, object]) -> str:
        attempts.append(payload["max_tokens"])
        return ""

    monkeypatch.setattr(transport, "_request_completion", _empty)

    # Act
    with pytest.raises(ValueError):
        transport.complete_json(_content(), SCHEMA, SCHEMA_NAME)

    # Assert
    assert attempts == [MAX_TOKENS, MAX_TOKENS * 2, MAX_TOKENS * 3]


def test_объект_без_полей_схемы_не_принимается_за_ответ(monkeypatch) -> None:
    # Arrange
    transport = _deepseek_transport()
    answers = ['{"type": "json_object"}', '{"type": "json_object"}', '{"ответ": "нашлось"}']

    def _reply(payload: dict[str, object]) -> str:
        return answers.pop(0)

    monkeypatch.setattr(transport, "_request_completion", _reply)

    # Act
    answer = transport.complete_json(_content(), SCHEMA, SCHEMA_NAME)

    # Assert
    assert answer == {"ответ": "нашлось"}
