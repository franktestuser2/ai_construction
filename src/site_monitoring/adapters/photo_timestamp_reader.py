"""Чтение времени съёмки снимка.

По требованиям заказчика метаданные не гарантированы: дата, время, идентификатор
камеры на снимке могут отсутствовать. Поэтому время берётся из EXIF, а если его
там нет — из отметки файла, и вызывающий узнаёт, что источник был ненадёжным.
"""

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132
EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"


def read_capture_time(image_path: Path) -> tuple[datetime, bool]:
    """Возвращает время съёмки и признак того, что оно взято из EXIF."""
    stamp = _read_exif_time(image_path)
    if stamp is not None:
        return stamp, True
    fallback = datetime.fromtimestamp(image_path.stat().st_mtime)
    return fallback, False


def _read_exif_time(image_path: Path) -> datetime | None:
    """Достаёт время съёмки из EXIF, если оно там записано."""
    try:
        with Image.open(image_path) as image:
            exif = image.getexif()
            raw = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(EXIF_DATETIME)
    except (OSError, ValueError):
        logger.warning("Снимок %s не открылся для чтения метаданных", image_path.name)
        return None
    if not raw:
        return None
    try:
        parsed = datetime.strptime(str(raw), EXIF_TIME_FORMAT)
    except ValueError:
        return None
    return parsed
