"""Чтение разобранных смен из кеша прогона.

Ленты слотов считаются один раз и складываются в кеш: страницы сервиса должны
открываться мгновенно, не обращаясь к моделям.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

from ..entity import ShiftSlot, ShiftTimeline

logger = logging.getLogger(__name__)

SLOTS_KEY = "slots"


class ShiftTimelineReader:
    """Адаптер чтения лент слотов из кеша."""

    def __init__(self, cache_path: Path) -> None:
        self._cache_path = cache_path

    def read_timelines(self) -> dict[str, ShiftTimeline]:
        """Возвращает ленты смен по видам работ."""
        if not self._cache_path.exists():
            return {}
        payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        timelines = {work_id: _build_timeline(item) for work_id, item in payload.items()}
        logger.info("Ленты смен прочитаны из кеша: %d", len(timelines))
        return timelines


def _build_timeline(payload: dict[str, object]) -> ShiftTimeline:
    """Собирает ленту смены из записи кеша."""
    slots = tuple(_build_slot(item) for item in payload[SLOTS_KEY])  # type: ignore[union-attr]
    timeline = ShiftTimeline(
        plan_date=date.fromisoformat(str(payload["plan_date"])),
        work_id=str(payload["work_id"]),
        slot_minutes=int(payload["slot_minutes"]),  # type: ignore[arg-type]
        slots=slots,
    )
    return timeline


def _build_slot(payload: dict[str, object]) -> ShiftSlot:
    """Собирает один отрезок смены из записи кеша."""
    slot = ShiftSlot(
        index=int(payload["index"]),  # type: ignore[arg-type]
        starts_at=datetime.fromisoformat(str(payload["starts_at"])),
        frame_id=payload["frame_id"],  # type: ignore[arg-type]
        has_equipment=bool(payload["has_equipment"]),
        has_kit=bool(payload["has_kit"]),
        has_motion=bool(payload["has_motion"]),
        is_first=bool(payload["is_first"]),
        limited_view=bool(payload.get("limited_view", False)),
    )
    return slot
