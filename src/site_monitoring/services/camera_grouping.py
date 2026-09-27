"""Разделение снимков объекта по камерам.

На объекте несколько камер, и кадры от них приходят в общий пул. Разбирать их одним
рядом нельзя: работа между кадрами определяется сравнением соседних снимков, а соседние
снимки разных камер отличаются ракурсом, а не движением техники.

Камера узнаётся по имени файла: контур наблюдения называет снимки `{камера}-{дата}-{время}`.
Если имя другое — например, пользователь загрузил свой архив, — все кадры считаются одной
камерой, и разбор идёт как раньше.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Имя снимка контура наблюдения: идентификатор камеры, дата и время съёмки.
CAMERA_NAME_PATTERN = re.compile(r"^(?P<camera>.+)-\d{8}-\d{6}$")
SINGLE_CAMERA = ""


def camera_of(photo: Path) -> str:
    """Камера, снявшая кадр; пустая строка, если по имени её не узнать."""
    found = CAMERA_NAME_PATTERN.match(photo.stem)
    if found is None:
        return SINGLE_CAMERA
    return found.group("camera")


def group_by_camera(photos: tuple[Path, ...]) -> dict[str, tuple[Path, ...]]:
    """Раскладывает снимки по камерам, сохраняя порядок съёмки внутри каждой."""
    grouped: dict[str, list[Path]] = {}
    for photo in sorted(photos):
        grouped.setdefault(camera_of(photo), []).append(photo)
    if len(grouped) > 1:
        logger.info("Снимки разложены по камерам: %s", ", ".join(sorted(grouped)))
    return {name: tuple(items) for name, items in grouped.items()}
