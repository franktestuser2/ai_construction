"""Тесты арифметики план-факта."""

from datetime import date

from site_monitoring.entity import ShiftSlot, ShiftTimeline, StageStatus
from site_monitoring.services.plan_fact import StageFact, build_plan_fact, build_stage_fact

SLOTS_PER_SHIFT = 9
SLOT_MINUTES = 20


def _fact(counted: int, limited: int, planned: int = SLOTS_PER_SHIFT) -> StageFact:
    """План-факт этапа с заданными числами."""
    stage = StageFact(
        work_id="W01",
        title="Разработка грунта",
        plan_date="2026-10-05",
        planned_slots=planned,
        counted_slots=counted,
        limited_slots=limited,
        slot_minutes=SLOT_MINUTES,
    )
    return stage


def test_неизмеренные_отрезки_вычитаются_из_плана() -> None:
    # Arrange: из девяти отрезков три не измерены, из остальных подтверждены три
    stage = _fact(counted=3, limited=3)

    # Act & Assert: доля считается от шести измеренных, а не от девяти
    assert stage.measured_slots == 6
    assert stage.completion == 0.5
    assert stage.lag_slots == 3


def test_полностью_подтверждённый_этап_идёт_по_графику() -> None:
    # Arrange
    stage = _fact(counted=9, limited=0)

    # Act & Assert
    assert stage.completion == 1.0
    assert stage.status is StageStatus.ON_SCHEDULE


def test_этап_без_единого_измеренного_отрезка_не_объявляется_отстающим() -> None:
    # Arrange: смотреть было не на что, вины подрядчика в этом нет
    stage = _fact(counted=0, limited=SLOTS_PER_SHIFT)

    # Act & Assert
    assert stage.measured_slots == 0
    assert stage.status is StageStatus.RISK_OF_DELAY


def test_отставание_в_днях_считается_по_длине_смены() -> None:
    # Arrange: два этапа, подтверждено 9 отрезков из 18 измеренных
    stages = (_fact(counted=5, limited=0), _fact(counted=4, limited=0))

    # Act
    summary = build_plan_fact(stages, SLOTS_PER_SHIFT)

    # Assert
    assert summary.measured_slots == 18
    assert summary.counted_slots == 9
    assert summary.lag_days == 1.0
    assert summary.status is StageStatus.DELAYED


def test_план_факт_считается_по_разобранной_смене() -> None:
    # Arrange
    slots = tuple(
        ShiftSlot(
            index=index,
            starts_at=__import__("datetime").datetime(2026, 10, 5, 9, 0),
            frame_id=f"кадр-{index}",
            has_equipment=True,
            has_kit=True,
            has_motion=index > 0,
            is_first=index == 0,
            limited_view=index == 2,
        )
        for index in range(3)
    )
    timeline = ShiftTimeline(
        plan_date=date(2026, 10, 5),
        work_id="W01",
        slot_minutes=SLOT_MINUTES,
        slots=slots,
    )

    # Act
    stage = build_stage_fact(timeline, "Разработка грунта", SLOTS_PER_SHIFT)

    # Assert
    assert stage.counted_slots == 2
    assert stage.limited_slots == 1
    assert stage.measured_slots == 8
