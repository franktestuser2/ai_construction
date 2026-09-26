"""Проверка находок детектора визуально-языковой моделью.

На вход модели идут два изображения: вырезанный по рамке фрагмент крупным планом
и весь кадр для контекста. Модель обязана сначала перечислить видимые признаки
техники и лишь затем согласиться с гипотезой детектора или отклонить её.
"""

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from ..entity import ArbitrationResult, EquipmentStatus
from .model_answer_reader import read_bool, read_status
from .vlm_transport import VlmTransport

logger = logging.getLogger(__name__)

IMAGE_DATA_URI_TEMPLATE = "data:image/jpeg;base64,{encoded}"
SCHEMA_NAME = "проверка_находки"
CROP_PADDING = 0.35
CROP_QUALITY = 90
FEATURES_KEY = "признаки"
CONFIRMED_KEY = "гипотеза_подтверждена"
ACTUAL_CLASS_KEY = "фактический_класс"
STATUS_KEY = "статус"
JUSTIFICATION_KEY = "обоснование"

PROMPT_TEMPLATE = (
    "Первое изображение — фрагмент снимка строительной площадки крупным планом, "
    "второе — тот же снимок целиком, для контекста.\n"
    "Детектор предполагает, что на фрагменте «{machine_type}». По календарному плану "
    "сейчас идёт работа: {work_name}.\n\n"
    "Сначала в поле «признаки» перечисли, что конкретно видно на фрагменте: рабочий орган "
    "(ковш, стрела, барабан, отвал, вилы, буровая колонна), где он расположен, тип шасси "
    "(гусеничное или колёсное), кабина, цвет и маркировка.\n"
    "Затем в поле «обоснование» объясни, какие из этих признаков подтверждают гипотезу детектора, "
    "а какие ей противоречат, и сделай вывод. Не соглашайся с детектором, если признаки не сходятся: "
    "назови технику так, как её видно на самом деле.\n"
    "В поле «статус» укажи, работает машина или простаивает, и назови признак: рабочий орган в грунте "
    "или в движении, оператор в кабине, груз на крюке — работает; сложенная стрела, машина на стоянке "
    "или вне фронта работ — простаивает.\n"
    "Рассуждай кратко: ответ важнее размышлений."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        FEATURES_KEY: {"type": "string"},
        CONFIRMED_KEY: {"type": "boolean"},
        ACTUAL_CLASS_KEY: {"type": "string"},
        STATUS_KEY: {"type": "string", "enum": ["работает", "простаивает", "не задействована", "не применимо"]},
        JUSTIFICATION_KEY: {"type": "string"},
    },
    "required": [FEATURES_KEY, CONFIRMED_KEY, ACTUAL_CLASS_KEY, STATUS_KEY, JUSTIFICATION_KEY],
}


class DetectionArbiter:
    """Адаптер проверки рамки детектора визуально-языковой моделью."""

    def __init__(self, transport: VlmTransport) -> None:
        self._transport = transport

    def verify(
        self,
        image_path: Path,
        box: tuple[float, float, float, float],
        machine_type: str,
        work_name: str,
    ) -> ArbitrationResult:
        """Проверяет одну рамку детектора и возвращает вывод арбитра."""
        image = Image.open(image_path).convert("RGB")
        piece = self._crop(image, box)
        images = (self._encode(piece), self._encode(image))
        content = self._build_content(images, machine_type, work_name)
        answer = self._transport.complete_json(content, RESPONSE_SCHEMA, SCHEMA_NAME)
        result = self._build_result(answer)
        logger.info(
            "Арбитр по «%s» на %s: подтверждено=%s, видит «%s»",
            machine_type,
            image_path.name,
            result.confirmed,
            result.actual_class,
        )
        return result

    def _crop(self, image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
        """Вырезает фрагмент по рамке, оставляя поля для контекста."""
        width, height = image.size
        left, top, right, bottom = box[0] * width, box[1] * height, box[2] * width, box[3] * height
        pad_x, pad_y = (right - left) * CROP_PADDING, (bottom - top) * CROP_PADDING
        area = (
            max(left - pad_x, 0),
            max(top - pad_y, 0),
            min(right + pad_x, width),
            min(bottom + pad_y, height),
        )
        piece = image.crop(area)
        return piece

    def _encode(self, image: Image.Image) -> str:
        """Кодирует изображение в data-URI для передачи в теле запроса."""
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=CROP_QUALITY)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        data_uri = IMAGE_DATA_URI_TEMPLATE.format(encoded=encoded)
        return data_uri

    def _build_content(
        self,
        images: tuple[str, str],
        machine_type: str,
        work_name: str,
    ) -> list[dict[str, Any]]:
        """Собирает тело сообщения: требование рассуждений, фрагмент и целый кадр."""
        prompt = PROMPT_TEMPLATE.format(machine_type=machine_type, work_name=work_name)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for data_uri in images:
            content.append({"type": "image_url", "image_url": {"url": data_uri}})
        return content

    def _build_result(self, answer: dict[str, Any]) -> ArbitrationResult:
        """Превращает ответ модели в результат арбитража."""
        reasoning = f"{answer.get(FEATURES_KEY, '')} {answer.get(JUSTIFICATION_KEY, '')}".strip()
        result = ArbitrationResult(
            confirmed=read_bool(answer.get(CONFIRMED_KEY)),
            actual_class=str(answer.get(ACTUAL_CLASS_KEY, "")),
            status=read_status(answer.get(STATUS_KEY)),
            justification=reasoning,
        )
        return result
