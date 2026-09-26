"""Чтение разметки камеры: где на кадре стоит здание.

У авторов фасадных моделей область здания берётся из настроек камеры в базе,
а не из детекции. Для сцены, снятой с одной точки, это надёжнее: на дорисованных
кадрах детектор зданий выбирает соседний готовый дом вместо строящегося.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

WORKS_KEY = "works"
BOX_SIZE = 4


class CameraMarkupReader:
    """Адаптер чтения файла разметки камеры."""

    def __init__(self, markup_path: Path) -> None:
        self._markup_path = markup_path

    def read_boxes(self) -> dict[str, tuple[float, float, float, float]]:
        """Возвращает область здания в долях кадра по каждому виду работ."""
        if not self._markup_path.exists():
            return {}
        payload = json.loads(self._markup_path.read_text(encoding="utf-8"))
        boxes = {}
        for work_id, values in (payload.get(WORKS_KEY) or {}).items():
            if len(values) != BOX_SIZE:
                logger.warning("Разметка камеры для %s задана неверно", work_id)
                continue
            boxes[str(work_id)] = tuple(float(value) for value in values)
        logger.info("Разметка камеры прочитана для %d видов работ", len(boxes))
        return boxes  # type: ignore[return-value]
