"""Клиент мультимодальной модели: вопросы о технике по целому кадру.

Отвечает на вопрос, присутствует ли на снимке техника, которой нет в словаре
детектора, и работает ли она. Отправкой запроса занимается транспорт, здесь
живут только промпт, схема ответа и разбор.
"""

import base64
import logging
from pathlib import Path
from typing import Any

from ..entity import EquipmentSource, EquipmentStatus, ObservedEquipment
from .model_answer_reader import read_bool, read_status
from .vlm_transport import VlmTransport

logger = logging.getLogger(__name__)

IMAGE_DATA_URI_TEMPLATE = "data:image/png;base64,{encoded}"
RESPONSE_SCHEMA_NAME = "оценка_техники"
MIN_SHORT_ANSWER_LENGTH = 5

PROMPT_TEMPLATE = (
    "Снимок строительной площадки. По календарному плану сейчас идёт работа: {work_name}.\n\n"
    "Ответь по каждому пункту списка, опираясь только на то, что видно на снимке. "
    "Пункт может описывать не машину, а признак работ — смонтированную конструкцию, опалубку, "
    "арматуру, облицовку; такие пункты пропускать нельзя, отвечай и по ним.\n"
    "{questions}\n\n"
    "Верни ровно столько позиций, сколько пунктов в списке, и в поле «тип» укажи название пункта "
    "слово в слово так, как оно написано выше. Для каждого пункта скажи, обнаружен ли признак, "
    "работает техника или простаивает, и обязательно объясни, по каким видимым деталям ты так решил: "
    "форма рабочего органа, положение стрелы, следы работы, состояние конструкций. "
    "Отдельно оцени, можно ли вообще судить по этому кадру о ходе работ на площадке, "
    "и запиши это в поле «обзор_ограничен».\n"
    "Ставь true, если кадр снят слишком близко и в нём виден лишь фрагмент — одна машина "
    "крупным планом, кусок грунта, штабель материалов, стена, — либо фронт работ перекрыт "
    "или не попадает в кадр. По такому снимку нельзя сказать, что происходит на площадке.\n"
    "Ставь false, если площадка видна общим планом и по кадру понятно, что на ней делается.\n"
    "Это вопрос про обзор кадра, а не про то, та ли это работа: кадр может быть с другого "
    "этапа и при этом иметь полный обзор.\n"
    "Рассуждай кратко: ответ важнее размышлений."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "техника": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "тип": {"type": "string"},
                    "обнаружена": {"type": "boolean"},
                    "статус": {
                        "type": "string",
                        "enum": ["работает", "простаивает", "не задействована", "не применимо"],
                    },
                    "обоснование": {"type": "string"},
                },
                "required": ["тип", "обнаружена", "статус", "обоснование"],
            },
        },
        "обзор_ограничен": {"type": "boolean"},
    },
    "required": ["техника", "обзор_ограничен"],
}


class VlmClient:
    """Адаптер вопросов о технике на целом кадре."""

    def __init__(self, transport: VlmTransport) -> None:
        self._transport = transport

    def assess_frame(
        self,
        image_path: Path,
        work_name: str,
        questions: tuple[tuple[str, str], ...],
    ) -> dict[str, Any]:
        """Спрашивает модель о технике на снимке и возвращает разобранный ответ."""
        content = self._build_content(image_path, work_name, questions)
        answer = self._transport.complete_json(content, RESPONSE_SCHEMA, RESPONSE_SCHEMA_NAME)
        logger.info(
            "VLM разобрала снимок %s, позиций техники: %d",
            image_path.name,
            len(answer.get(ANSWER_EQUIPMENT_KEY, [])),
        )
        return answer

    def _encode_image(self, image_path: Path) -> str:
        """Кодирует снимок в base64 для передачи в теле запроса."""
        raw_bytes = image_path.read_bytes()
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return encoded

    def _build_content(
        self,
        image_path: Path,
        work_name: str,
        questions: tuple[tuple[str, str], ...],
    ) -> list[dict[str, Any]]:
        """Собирает текст вопросов и изображение в тело сообщения."""
        numbered = "\n".join(
            f"{index}. {machine_type} — {question}"
            for index, (machine_type, question) in enumerate(questions, start=1)
        )
        prompt = PROMPT_TEMPLATE.format(work_name=work_name, questions=numbered)
        encoded = self._encode_image(image_path)
        data_uri = IMAGE_DATA_URI_TEMPLATE.format(encoded=encoded)
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
        return content

    def recognize(
        self,
        image_path: Path,
        work_name: str,
        questions: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[ObservedEquipment, ...], bool]:
        """Возвращает найденную моделью технику и признак ограниченного обзора."""
        answer = self.assess_frame(image_path, work_name, questions)
        expected_types = tuple(machine_type for machine_type, _ in questions)
        parsed = parse_vlm_answer(answer, expected_types)
        return parsed


ANSWER_EQUIPMENT_KEY = "техника"
ANSWER_TYPE_KEY = "тип"
ANSWER_DETECTED_KEY = "обнаружена"
ANSWER_STATUS_KEY = "статус"
ANSWER_JUSTIFICATION_KEY = "обоснование"
ANSWER_LIMITED_VIEW_KEY = "обзор_ограничен"
SINGLE_UNIT = 1


def _resolve_machine_type(raw_type: str, known_types: dict[str, str]) -> str | None:
    """Сопоставляет название из ответа модели с типом машины из вопросов.

    Модель то повторяет формулировку вопроса целиком, то сокращает её, поэтому
    кроме точного совпадения проверяется вхождение в обе стороны. Сокращение
    принимается только если оно подходит ровно одному типу из вопросов.
    """
    normalized = raw_type.casefold()
    exact = known_types.get(normalized)
    if exact is not None:
        return exact
    for known, machine_type in known_types.items():
        if known in normalized:
            return machine_type
    if len(normalized) < MIN_SHORT_ANSWER_LENGTH:
        return None
    candidates = [machine_type for known, machine_type in known_types.items() if normalized in known]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _parse_answer_item(payload: dict[str, Any], known_types: dict[str, str]) -> ObservedEquipment | None:
    """Превращает одну позицию ответа модели в наблюдение техники."""
    raw_type = str(payload.get(ANSWER_TYPE_KEY, "")).strip()
    machine_type = _resolve_machine_type(raw_type, known_types)
    if machine_type is None:
        logger.warning("Модель вернула тип техники вне списка вопросов: %s", raw_type)
        return None
    if not read_bool(payload.get(ANSWER_DETECTED_KEY)):
        return None
    equipment = ObservedEquipment(
        machine_type=machine_type,
        source=EquipmentSource.VLM,
        status=read_status(payload.get(ANSWER_STATUS_KEY)),
        count=SINGLE_UNIT,
        justification=str(payload.get(ANSWER_JUSTIFICATION_KEY, "")),
    )
    return equipment


def parse_vlm_answer(
    answer: dict[str, Any],
    expected_types: tuple[str, ...],
) -> tuple[tuple[ObservedEquipment, ...], bool]:
    """Собирает ответ модели в наблюдения техники и признак ограниченного обзора."""
    known_types = {item.casefold(): item for item in expected_types}
    items = answer.get(ANSWER_EQUIPMENT_KEY) or []
    equipment = []
    for item in items:
        parsed = _parse_answer_item(item, known_types)
        if parsed is not None:
            equipment.append(parsed)
    limited_view = read_bool(answer.get(ANSWER_LIMITED_VIEW_KEY))
    result = (tuple(equipment), limited_view)
    return result
