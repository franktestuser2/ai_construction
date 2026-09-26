"""Тесты разбора смены на двадцатиминутные слоты."""

from datetime import date

from site_monitoring.entity import (
    EquipmentSource,
    FacadeReadiness,
    ShiftFrames,
    EquipmentStatus,
    FrameObservation,
    MotionObservation,
    ObservedEquipment,
    PlanEntry,
    PositionAlternative,
    PositionKind,
    SlotStripe,
    WorkEquipmentRules,
    WorkPosition,
)
from site_monitoring.services.shift_timeline import ShiftTimelineService


def _frames(observations, motions) -> ShiftFrames:
    """Разобранные снимки смены обычного этапа."""
    bundle = ShiftFrames(
        plan_entry=_plan_entry(),
        frame_ids=tuple(item.frame_id for item in observations),
        observations=observations,
        motions=motions,
    )
    return bundle


def _facade_frames(readings) -> ShiftFrames:
    """Разобранные снимки фасадной смены."""
    bundle = ShiftFrames(
        plan_entry=_plan_entry(),
        frame_ids=tuple(f"кадр-{index}" for index in range(len(readings))),
        facade=readings,
    )
    return bundle


def _readiness(monolith: int, block: int, window: int) -> FacadeReadiness:
    """Разбор фасада по одному снимку."""
    reading = FacadeReadiness(
        frame_id="кадр",
        building_score=0.95,
        cells_total=monolith + block + window,
        monolith=monolith,
        block=block,
        window=window,
        rows=5,
        barrier_checked=0,
        barrier_violations=0,
    )
    return reading

PROJECT_ID = "EDU-DEMO-001"
WORK_ID = "W03"
SHIFT_DATE = date(2026, 11, 27)
SLOT_MINUTES = 20
SLOTS_PER_SHIFT = 9
SHIFT_START_HOUR = 9
LEAD_MACHINE = "Excavator"
SUPPORT_MACHINE = "Dump truck"


def _rules() -> WorkEquipmentRules:
    """Правила этапа: ведущий экскаватор и самосвал в комплекте."""
    lead = WorkPosition(
        position="Экскаватор",
        kind=PositionKind.KIT,
        min_count=1,
        alternatives=(
            PositionAlternative(
                machine_type="Экскаватор",
                source=EquipmentSource.DETECTOR,
                detector_classes=(LEAD_MACHINE,),
            ),
        ),
        is_lead=True,
    )
    support = WorkPosition(
        position="Самосвал",
        kind=PositionKind.KIT,
        min_count=1,
        alternatives=(
            PositionAlternative(
                machine_type="Самосвал",
                source=EquipmentSource.DETECTOR,
                detector_classes=(SUPPORT_MACHINE,),
            ),
        ),
    )
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(lead, support))
    return rules


def _equipment(machine_type: str) -> ObservedEquipment:
    """Находка детектора по классу машины."""
    item = ObservedEquipment(
        machine_type=machine_type,
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.WORKING,
        count=1,
    )
    return item


def _frame(index: int, machines: tuple[str, ...]) -> FrameObservation:
    """Наблюдение по одному снимку серии."""
    observation = FrameObservation(
        frame_id=f"кадр-{index}",
        observed_on=SHIFT_DATE,
        equipment=tuple(_equipment(machine) for machine in machines),
    )
    return observation


def _motion(detected: bool) -> MotionObservation:
    """Сравнение пары кадров."""
    observation = MotionObservation(
        moved=detected,
        operator_present=False,
        working_body_changed=False,
        justification="проверка",
    )
    return observation


def _service() -> ShiftTimelineService:
    """Сервис разбора смены на слоты."""
    service = ShiftTimelineService(
        slot_minutes=SLOT_MINUTES,
        slots_per_shift=SLOTS_PER_SHIFT,
        shift_start_hour=SHIFT_START_HOUR,
    )
    return service


def _plan_entry() -> PlanEntry:
    """Пункт плана на день смены."""
    entry = PlanEntry(project_id=PROJECT_ID, work_id=WORK_ID, plan_date=SHIFT_DATE)
    return entry


def test_слот_с_тремя_признаками_засчитывается() -> None:
    # Arrange
    observations = (
        _frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),
        _frame(1, (LEAD_MACHINE,)),
    )
    motions = (None, _motion(True))

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, motions))

    # Assert
    assert timeline.slots[1].is_counted is True
    assert timeline.slots[1].stripes == (SlotStripe.EQUIPMENT, SlotStripe.KIT, SlotStripe.MOTION)


def test_комплект_засчитывается_всей_смене_даже_если_виден_один_раз() -> None:
    # Arrange
    observations = (
        _frame(0, (LEAD_MACHINE,)),
        _frame(1, (LEAD_MACHINE, SUPPORT_MACHINE)),
    )
    motions = (None, _motion(True))

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, motions))

    # Assert
    assert timeline.slots[0].has_kit is True


def test_первому_слоту_хватает_двух_признаков() -> None:
    # Arrange
    observations = (_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)
    motions = (None,)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, motions))

    # Assert
    assert timeline.slots[0].is_first is True
    assert timeline.slots[0].has_motion is False
    assert timeline.slots[0].is_counted is True


def test_без_движения_обычный_слот_не_засчитывается() -> None:
    # Arrange
    observations = (
        _frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),
        _frame(1, (LEAD_MACHINE,)),
    )
    motions = (None, _motion(False))

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, motions))

    # Assert
    assert timeline.slots[1].is_counted is False


def test_слот_без_снимка_остаётся_пустым() -> None:
    # Arrange
    observations = (_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    empty = timeline.slots[-1]
    assert empty.frame_id is None
    assert empty.is_counted is False
    assert len(timeline.slots) == SLOTS_PER_SHIFT


def test_время_слотов_идёт_с_шагом_в_двадцать_минут() -> None:
    # Arrange
    observations = (_frame(0, (LEAD_MACHINE,)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, ()))

    # Assert
    assert timeline.slots[0].starts_at.hour == SHIFT_START_HOUR
    assert timeline.slots[1].starts_at.minute == SLOT_MINUTES
    assert timeline.planned_minutes == SLOTS_PER_SHIFT * SLOT_MINUTES


def test_засчитанное_время_считается_по_слотам() -> None:
    # Arrange
    observations = (
        _frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),
        _frame(1, (LEAD_MACHINE,)),
        _frame(2, (LEAD_MACHINE,)),
    )
    motions = (None, _motion(True), _motion(True))

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, motions))

    # Assert
    assert timeline.counted_slots == 3
    assert timeline.counted_minutes == 3 * SLOT_MINUTES


def test_сопутствующая_машина_тоже_собирает_комплект() -> None:
    # Arrange
    lead = _rules().positions[0]
    accompanying = WorkPosition(
        position="Погрузчик",
        kind=PositionKind.ACCOMPANYING,
        min_count=1,
        alternatives=(
            PositionAlternative(
                machine_type="Погрузчик",
                source=EquipmentSource.DETECTOR,
                detector_classes=(SUPPORT_MACHINE,),
            ),
        ),
    )
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(lead, accompanying))
    observations = (_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)

    # Act
    timeline = _service().build_timeline(rules, _frames(observations, ()))

    # Assert
    assert timeline.slots[0].has_kit is True


def test_признак_работ_комплект_не_собирает() -> None:
    # Arrange
    lead = _rules().positions[0]
    evidence = WorkPosition(
        position="Монолитная плита",
        kind=PositionKind.WORK_EVIDENCE,
        min_count=1,
        alternatives=(
            PositionAlternative(
                machine_type="Монолитная плита",
                source=EquipmentSource.DETECTOR,
                detector_classes=(SUPPORT_MACHINE,),
            ),
        ),
    )
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(lead, evidence))
    observations = (_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)

    # Act
    timeline = _service().build_timeline(rules, _frames(observations, ()))

    # Assert
    assert timeline.slots[0].has_kit is False


def test_день_идёт_по_графику_когда_есть_закрытый_отрезок() -> None:
    # Arrange
    observations = (
        _frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),
        _frame(1, (LEAD_MACHINE,)),
    )
    motions = (None, _motion(True))

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, motions))

    # Assert
    assert timeline.is_on_schedule is True


def test_без_единого_закрытого_отрезка_день_не_по_графику() -> None:
    # Arrange
    observations = (_frame(0, (LEAD_MACHINE,)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    assert timeline.is_on_schedule is False


def test_техника_с_отклонёнными_рамками_не_считается_присутствующей() -> None:
    # Arrange
    rejected = ObservedEquipment(
        machine_type=LEAD_MACHINE,
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.NOT_APPLICABLE,
        count=0,
        rejected_boxes=((0.1, 0.1, 0.2, 0.2),),
    )
    observation = FrameObservation(frame_id="кадр-0", observed_on=SHIFT_DATE, equipment=(rejected,))

    # Act
    timeline = _service().build_timeline(_rules(), _frames((observation,), (None,)))

    # Assert
    assert timeline.slots[0].has_equipment is False
    assert timeline.slots[0].is_counted is False


def test_фасадный_слот_считает_здание_ячейки_и_изменение_состава() -> None:
    # Arrange
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(), facade_check=True)
    readings = (_readiness(10, 0, 0), _readiness(5, 5, 0))

    # Act
    timeline = _service().build_timeline(rules, _facade_frames(readings))

    # Assert
    first, second = timeline.slots[0], timeline.slots[1]
    assert (first.has_equipment, first.has_kit, first.has_motion) == (True, True, False)
    assert first.is_counted is True
    assert second.has_motion is True
    assert second.is_counted is True


def test_без_здания_в_кадре_фасадный_слот_пустой() -> None:
    # Arrange
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(), facade_check=True)

    # Act
    timeline = _service().build_timeline(rules, _facade_frames((None,)))

    # Assert
    assert timeline.slots[0].has_equipment is False
    assert timeline.slots[0].is_counted is False


def test_неизменный_состав_ячеек_движением_не_считается() -> None:
    # Arrange
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(), facade_check=True)
    readings = (_readiness(10, 0, 0), _readiness(10, 0, 0))

    # Act
    timeline = _service().build_timeline(rules, _facade_frames(readings))

    # Assert
    assert timeline.slots[1].has_motion is False
    assert timeline.slots[1].is_counted is False


def test_машина_из_комплекта_зажигает_жёлтую_полоску() -> None:
    # Arrange: ведущего экскаватора на кадре нет, есть только самосвал из комплекта
    observations = (_frame(0, (SUPPORT_MACHINE,)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    assert timeline.slots[0].has_equipment is True
    assert timeline.slots[0].has_kit is True
    assert timeline.slots[0].is_counted is True


def test_пустой_кадр_жёлтую_полоску_не_зажигает() -> None:
    # Arrange
    observations = (_frame(0, ()),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    assert timeline.slots[0].has_equipment is False


def _limited_frame(index: int, machines: tuple[str, ...]) -> FrameObservation:
    """Наблюдение по снимку, на котором фронт работ не виден."""
    observation = FrameObservation(
        frame_id=f"кадр-{index}",
        observed_on=SHIFT_DATE,
        equipment=tuple(_equipment(machine) for machine in machines),
        limited_view=True,
    )
    return observation


def test_снимок_вне_контроля_ии_не_засчитывается_даже_с_техникой() -> None:
    # Arrange: техника на кадре видна, но фронт работ в кадр не попал
    observations = (_limited_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    assert timeline.slots[0].limited_view is True
    assert timeline.slots[0].is_counted is False
    assert timeline.needs_manual_check is True
    assert timeline.limited_slots == 1


def test_при_полном_обзоре_ручная_проверка_не_требуется() -> None:
    # Arrange
    observations = (_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    assert timeline.needs_manual_check is False


def test_фасадный_слот_без_здания_помечается_вне_контроля() -> None:
    # Arrange
    rules = WorkEquipmentRules(work_id=WORK_ID, positions=(), facade_check=True)

    # Act
    timeline = _service().build_timeline(rules, _facade_frames((None,)))

    # Assert
    assert timeline.slots[0].limited_view is True
    assert timeline.needs_manual_check is True


def test_техника_не_по_этапу_отмечается_отклонением() -> None:
    # Arrange: на кадре ведущий экскаватор и посторонний автогрейдер
    alien = ObservedEquipment(
        machine_type="Motor grader",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.WORKING,
        count=1,
    )
    observation = FrameObservation(
        frame_id="кадр-0",
        observed_on=SHIFT_DATE,
        equipment=(_equipment(LEAD_MACHINE), _equipment(SUPPORT_MACHINE), alien),
    )

    # Act
    timeline = _service().build_timeline(_rules(), _frames((observation,), (None,)))

    # Assert: отклонение зафиксировано, но зачёту отрезка не мешает
    assert timeline.slots[0].foreign_equipment == ("Motor grader",)
    assert timeline.slots[0].is_counted is True
    assert timeline.foreign_slots == 1
    assert timeline.foreign_machines == ("Motor grader",)


def test_техника_из_правил_чужой_не_считается() -> None:
    # Arrange
    observations = (_frame(0, (LEAD_MACHINE, SUPPORT_MACHINE)),)

    # Act
    timeline = _service().build_timeline(_rules(), _frames(observations, (None,)))

    # Assert
    assert timeline.slots[0].foreign_equipment == ()
    assert timeline.foreign_slots == 0
