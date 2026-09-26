"""Сравнение двух соседних снимков смены: работает техника или просто стоит.

Вопрос задаётся модели по паре кадров, а не считается по координатам рамок.
Причина простая: рамка детектора дрожит от кадра к кадру сама по себе, и правило
по смещению рамок засчитывало работу там, где техника не двигалась вовсе.
Модель же отвечает на три разных признака — сдвиг машины, положение рабочего
органа и присутствие оператора в кабине. Второй признак важнее первого: машина
чаще работает стоя на месте, двигая ковшом или кузовом, чем переезжая по площадке.
"""

import base64
import logging
from pathlib import Path
from typing import Any

from ..entity import MotionObservation
from .model_answer_reader import read_bool
from .vlm_transport import VlmTransport

logger = logging.getLogger(__name__)

IMAGE_DATA_URI_TEMPLATE = "data:image/jpeg;base64,{encoded}"
SCHEMA_NAME = "признаки_работы"
MOVED_KEY = "машина_сместилась"
OPERATOR_KEY = "оператор_в_кабине"
WORKING_BODY_KEY = "рабочий_орган_сменил_положение"
JUSTIFICATION_KEY = "обоснование"

PROMPT_TEMPLATE = (
    "Два снимка одной строительной площадки с одной точки, сняты с разницей "
    "в {minutes} минут: первый раньше, второй позже. Идёт работа: {work_name}.\n\n"
    "Определи, работала ли техника между этими кадрами, по трём признакам отдельно:\n"
    "1. Сместилась ли хотя бы одна машина по площадке — сравни её положение "
    "относительно неподвижных ориентиров: ограждения, бытовок, отвалов, стены.\n"
    "2. Сменил ли положение рабочий орган — машина при этом может стоять на месте, "
    "и это всё равно работа: ковш поднят, опущен или повёрнут, стрела развёрнута, "
    "кузов самосвала поднят или опущен, груз в кузове появился, убыл или изменил уровень, "
    "отвал переставлен, барабан или буровая колонна на другой высоте, "
    "крюк или груз на тросе сместился.\n"
    "3. Виден ли человек в кабине или рядом с машиной у органов управления.\n\n"
    "Не считай движением дрожание кадра, смену освещения, тени и мелкие сдвиги "
    "всей картинки целиком: если сместилось всё сразу, сдвинулась камера, а не машина.\n"
    "В обосновании назови, по какой машине и какому ориентиру ты судишь, "
    "в двух-трёх предложениях.\n"
    "Рассуждай кратко: ответ важнее размышлений."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        MOVED_KEY: {"type": "boolean"},
        WORKING_BODY_KEY: {"type": "boolean"},
        OPERATOR_KEY: {"type": "boolean"},
        JUSTIFICATION_KEY: {"type": "string"},
    },
    "required": [MOVED_KEY, WORKING_BODY_KEY, OPERATOR_KEY, JUSTIFICATION_KEY],
}


class MotionObserver:
    """Адаптер вопроса о признаках работы по паре соседних кадров."""

    def __init__(self, transport: VlmTransport, slot_minutes: int) -> None:
        self._transport = transport
        self._slot_minutes = slot_minutes

    def compare(
        self,
        earlier_path: Path,
        later_path: Path,
        work_name: str,
    ) -> MotionObservation:
        """Сравнивает два снимка и возвращает признаки работы техники."""
        content = self._build_content(earlier_path, later_path, work_name)
        answer = self._transport.complete_json(content, RESPONSE_SCHEMA, SCHEMA_NAME)
        observation = _build_observation(answer)
        logger.info(
            "Пара %s → %s: сдвиг=%s, рабочий орган=%s, оператор=%s",
            earlier_path.name,
            later_path.name,
            observation.moved,
            observation.working_body_changed,
            observation.operator_present,
        )
        return observation

    def _build_content(
        self,
        earlier_path: Path,
        later_path: Path,
        work_name: str,
    ) -> list[dict[str, Any]]:
        """Собирает тело сообщения: вопрос и два кадра по порядку времени."""
        prompt = PROMPT_TEMPLATE.format(minutes=self._slot_minutes, work_name=work_name)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for path in (earlier_path, later_path):
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            data_uri = IMAGE_DATA_URI_TEMPLATE.format(encoded=encoded)
            content.append({"type": "image_url", "image_url": {"url": data_uri}})
        return content


def _build_observation(answer: dict[str, Any]) -> MotionObservation:
    """Превращает ответ модели в наблюдение о работе техники."""
    observation = MotionObservation(
        moved=read_bool(answer.get(MOVED_KEY)),
        operator_present=read_bool(answer.get(OPERATOR_KEY)),
        working_body_changed=read_bool(answer.get(WORKING_BODY_KEY)),
        justification=str(answer.get(JUSTIFICATION_KEY, "")),
    )
    return observation
