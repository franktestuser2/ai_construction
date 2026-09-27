"""Тесты сведения камер объекта: отрезок засчитан, если работа видна хотя бы на одной."""

from datetime import date, datetime

import pytest

from site_monitoring.entity import ShiftSlot, ShiftTimeline
from site_monitoring.services.multi_camera_shift import merge_timelines

PLAN_DATE = date(2026, 9, 28)
WORK_ID = "W06"
SLOT_MINUTES = 20
SHIFT_START = datetime(2026, 9, 28, 9, 0)


def _slot(
    index: int,
    frame_id: str | None,
    *,
    equipment: bool = False,
    kit: bool = False,
    motion: bool = False,
    limited: bool = False,
    foreign: tuple[str, ...] = (),
) -> ShiftSlot:
    """Отрезок с заданными признаками."""
    slot = ShiftSlot(
        index=index,
        starts_at=SHIFT_START,
        frame_id=frame_id,
        has_equipment=equipment,
        has_kit=kit,
        has_motion=motion,
        is_first=index == 0,
        limited_view=limited,
        foreign_equipment=foreign,
    )
    return slot


def _timeline(slots: tuple[ShiftSlot, ...]) -> ShiftTimeline:
    """Лента одной камеры."""
    timeline = ShiftTimeline(
        plan_date=PLAN_DATE, work_id=WORK_ID, slot_minutes=SLOT_MINUTES, slots=slots
    )
    return timeline


def test_работа_хотя_бы_на_одной_камере_засчитывает_отрезок() -> None:
    # Arrange
    busy = _timeline((_slot(0, "cam1-1", equipment=True, kit=True, motion=True),))
    idle = _timeline((_slot(0, "cam2-1"),))

    # Act
    merged = merge_timelines({"cam1": busy, "cam2": idle})

    # Assert
    assert merged.counted_slots == 1
    assert merged.slots[0].frame_id == "cam1-1"


def test_признаки_собираются_со_всех_камер() -> None:
    # Arrange
    first = _timeline((_slot(0, "cam1-1", equipment=True),))
    second = _timeline((_slot(0, "cam2-1", kit=True, motion=True),))

    # Act
    merged = merge_timelines({"cam1": first, "cam2": second})

    # Assert
    assert merged.slots[0].has_equipment is True
    assert merged.slots[0].has_kit is True
    assert merged.slots[0].has_motion is True


def test_обзор_ограничен_только_когда_площадку_не_видит_ни_одна_камера() -> None:
    # Arrange
    blind = _timeline((_slot(0, "cam1-1", limited=True), _slot(1, "cam1-2", limited=True)))
    seeing = _timeline((_slot(0, "cam2-1", limited=True), _slot(1, "cam2-2", equipment=True)))

    # Act
    merged = merge_timelines({"cam1": blind, "cam2": seeing})

    # Assert
    assert merged.slots[0].limited_view is True
    assert merged.slots[1].limited_view is False


def test_чужая_техника_собирается_со_всех_камер_без_повторов() -> None:
    # Arrange
    first = _timeline((_slot(0, "cam1-1", foreign=("Самосвал", "Каток")),))
    second = _timeline((_slot(0, "cam2-1", foreign=("Каток", "Автокран")),))

    # Act
    merged = merge_timelines({"cam1": first, "cam2": second})

    # Assert
    assert merged.slots[0].foreign_equipment == ("Самосвал", "Каток", "Автокран")


def test_отрезок_без_снимков_остаётся_незасчитанным() -> None:
    # Arrange
    first = _timeline((_slot(0, None),))
    second = _timeline((_slot(0, None),))

    # Act
    merged = merge_timelines({"cam1": first, "cam2": second})

    # Assert
    assert merged.counted_slots == 0
    assert merged.slots[0].frame_id is None


def test_снимок_берётся_у_камеры_с_наибольшим_числом_признаков() -> None:
    # Arrange
    weak = _timeline((_slot(0, "cam1-1", equipment=True),))
    strong = _timeline((_slot(0, "cam2-1", equipment=True, kit=True),))

    # Act
    merged = merge_timelines({"cam1": weak, "cam2": strong})

    # Assert
    assert merged.slots[0].frame_id == "cam2-1"


def test_одна_камера_отдаётся_как_есть() -> None:
    # Arrange
    single = _timeline((_slot(0, "cam1-1", equipment=True),))

    # Act
    merged = merge_timelines({"cam1": single})

    # Assert
    assert merged is single


def test_без_камер_сводить_нечего() -> None:
    # Arrange
    empty: dict[str, ShiftTimeline] = {}

    # Act, Assert
    with pytest.raises(ValueError):
        merge_timelines(empty)
