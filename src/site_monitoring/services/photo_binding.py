"""Привязка загруженных снимков к этапам календарного плана.

Требования заказчика прямо говорят, что метаданные снимка не гарантированы,
а способ привязки команда разрабатывает сама. Здесь их два, и сервис честно
сообщает, каким воспользовался:

1. **По времени съёмки.** Если у снимков есть EXIF и время попадает в периоды
   плана, каждый снимок уходит в свой этап. Это основной путь.
2. **По порядку.** Если времени нет или оно не попадает ни в один период,
   снимки раскладываются по этапам поровну в том порядке, в каком загружены.
   Путь запасной, и в отчёте он помечается как допущение.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..adapters.photo_timestamp_reader import read_capture_time
from ..adapters.uploaded_plan_reader import UploadedStage

logger = logging.getLogger(__name__)

BINDING_BY_TIME = "по времени съёмки из метаданных снимка"
BINDING_BY_ORDER = "по порядку загрузки: времени съёмки в снимках нет"
NOTHING = 0


@dataclass(frozen=True)
class BoundPhoto:
    """Снимок, привязанный к этапу плана."""

    path: Path
    captured_at: datetime
    from_metadata: bool


@dataclass(frozen=True)
class StagePhotos:
    """Этап плана и доставшиеся ему снимки по времени съёмки."""

    stage: UploadedStage
    photos: tuple[BoundPhoto, ...]


@dataclass(frozen=True)
class BindingResult:
    """Раскладка снимков по этапам и способ, которым она получена."""

    stages: tuple[StagePhotos, ...]
    method: str


def _read_photos(paths: tuple[Path, ...]) -> tuple[BoundPhoto, ...]:
    """Читает время съёмки каждого снимка."""
    photos = []
    for path in paths:
        captured_at, from_metadata = read_capture_time(path)
        photos.append(BoundPhoto(path=path, captured_at=captured_at, from_metadata=from_metadata))
    return tuple(photos)


def _bind_by_time(
    stages: tuple[UploadedStage, ...],
    photos: tuple[BoundPhoto, ...],
) -> tuple[StagePhotos, ...] | None:
    """Раскладывает снимки по периодам этапов; ничего не возвращает, если не легло."""
    grouped: dict[str, list[BoundPhoto]] = {stage.work_id: [] for stage in stages}
    placed = NOTHING
    for photo in photos:
        day = photo.captured_at.date()
        for stage in stages:
            if stage.start <= day <= stage.finish:
                grouped[stage.work_id].append(photo)
                placed += 1
                break
    if placed < len(photos):
        return None
    bound = tuple(
        StagePhotos(stage=stage, photos=tuple(sorted(grouped[stage.work_id], key=lambda item: item.captured_at)))
        for stage in stages
    )
    return bound


def _bind_by_order(
    stages: tuple[UploadedStage, ...],
    photos: tuple[BoundPhoto, ...],
) -> tuple[StagePhotos, ...]:
    """Раскладывает снимки по этапам поровну в порядке загрузки."""
    share, extra = divmod(len(photos), len(stages))
    bound = []
    start = NOTHING
    for index, stage in enumerate(stages):
        size = share + (1 if index < extra else 0)
        bound.append(StagePhotos(stage=stage, photos=photos[start : start + size]))
        start += size
    return tuple(bound)


def bind_photos(stages: tuple[UploadedStage, ...], paths: tuple[Path, ...]) -> BindingResult:
    """Привязывает снимки к этапам плана и сообщает, каким способом."""
    photos = _read_photos(paths)
    by_time = _bind_by_time(stages, photos) if stages and photos else None
    if by_time is not None and all(photo.from_metadata for photo in photos):
        logger.info("Снимки привязаны по времени съёмки: этапов %d", len(by_time))
        return BindingResult(stages=by_time, method=BINDING_BY_TIME)
    by_order = _bind_by_order(stages, photos) if stages else ()
    logger.info("Снимки привязаны по порядку загрузки: этапов %d", len(by_order))
    return BindingResult(stages=by_order, method=BINDING_BY_ORDER)
