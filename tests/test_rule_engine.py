"""Тесты сверки наблюдаемой техники с правилами этапа."""

from datetime import date

from site_monitoring.entity import (
    DeviationKind,
    EquipmentSource,
    EquipmentStatus,
    FrameObservation,
    ObservedEquipment,
    PositionAlternative,
    PositionKind,
    WorkEquipmentRules,
    WorkPosition,
)
from site_monitoring.services.rule_engine import RuleEngineService

OBSERVED_DATE = date(2026, 10, 5)


def _frame(equipment: tuple[ObservedEquipment, ...], limited_view: bool = False) -> FrameObservation:
    """Собирает наблюдение по одному снимку."""
    observation = FrameObservation(
        frame_id="frame-1",
        observed_on=OBSERVED_DATE,
        equipment=equipment,
        limited_view=limited_view,
    )
    return observation


def _excavator(status: EquipmentStatus = EquipmentStatus.WORKING, count: int = 1) -> ObservedEquipment:
    """Наблюдение экскаватора, найденного детектором."""
    equipment = ObservedEquipment(
        machine_type="Excavator",
        source=EquipmentSource.DETECTOR,
        status=status,
        count=count,
        confidence=0.9,
    )
    return equipment


def _tower_crane(status: EquipmentStatus = EquipmentStatus.WORKING) -> ObservedEquipment:
    """Наблюдение башенного крана, подтверждённого моделью."""
    equipment = ObservedEquipment(
        machine_type="Башенный кран",
        source=EquipmentSource.VLM,
        status=status,
        count=1,
        justification="Виден башенный кран с горизонтальной стрелой",
    )
    return equipment


def _loader() -> ObservedEquipment:
    """Наблюдение фронтального погрузчика, найденного детектором."""
    equipment = ObservedEquipment(
        machine_type="Bucket loader Big",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.WORKING,
        count=1,
    )
    return equipment


def _single_position_rules(position: WorkPosition, work_id: str) -> WorkEquipmentRules:
    """Правила из одной позиции для точечной проверки."""
    rules = WorkEquipmentRules(work_id=work_id, positions=(position,))
    return rules


def test_full_kit_gives_compliance(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()
    observations = (_frame((_excavator(), _tower_crane())),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    assert assessment.is_compliant is True
    assert assessment.deviations == ()
    assert set(assessment.confirmed_equipment) == {"Экскаватор", "Башенный кран"}


def test_single_frame_does_not_gate_on_rest_of_kit(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()
    observations = (_frame((_excavator(),)),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    assert assessment.deviations[0].kind is DeviationKind.NOT_VERIFIED
    assert assessment.is_compliant is True


def test_series_gates_on_whole_kit(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()
    observations = (_frame((_excavator(),)), _frame((_excavator(),)))

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    assert assessment.deviations[0].kind is DeviationKind.INCOMPLETE_KIT
    assert assessment.is_compliant is False


def test_missing_lead_machine_breaks_compliance(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()
    observations = (_frame((_tower_crane(),)),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    kinds = [item.kind for item in assessment.deviations]
    assert DeviationKind.MISSING_EQUIPMENT in kinds
    assert assessment.is_compliant is False


def test_idle_lead_machine_breaks_compliance(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()
    observations = (_frame((_excavator(status=EquipmentStatus.IDLE), _tower_crane())),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    kinds = [item.kind for item in assessment.deviations]
    assert DeviationKind.IDLE_EQUIPMENT in kinds
    assert assessment.is_compliant is False


def test_day_without_frames_is_not_verifiable(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()

    # Act
    assessment = service.assess_day(plan_entry, work_rules, ())

    # Assert
    assert assessment.deviations[0].kind is DeviationKind.NO_DATA
    assert assessment.is_verifiable is False


def test_limited_view_marks_day_as_not_measured(plan_entry, work_rules) -> None:
    # Arrange: фронт работ перекрыт, техники этапа на снимке не нашлось
    service = RuleEngineService()
    observations = (_frame((), limited_view=True),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    assert assessment.deviations[0].kind is DeviationKind.LIMITED_VIEW
    assert assessment.is_verifiable is False


def test_найденная_техника_не_отменяет_ограниченный_обзор(plan_entry, work_rules) -> None:
    # Arrange: камера уткнулась в саму машину — техника видна, а фронт работ нет
    service = RuleEngineService()
    observations = (_frame((_excavator(), _tower_crane()), limited_view=True),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    kinds = [item.kind for item in assessment.deviations]
    assert DeviationKind.LIMITED_VIEW in kinds
    assert assessment.is_verifiable is False


def test_position_is_closed_by_any_alternative(plan_entry) -> None:
    # Arrange
    service = RuleEngineService()
    excavator = PositionAlternative(
        machine_type="Экскаватор",
        source=EquipmentSource.DETECTOR,
        detector_classes=("Excavator",),
    )
    loader = PositionAlternative(
        machine_type="Фронтальный погрузчик",
        source=EquipmentSource.DETECTOR,
        detector_classes=("Bucket loader Big",),
    )
    position = WorkPosition(
        position="Погрузочная машина",
        kind=PositionKind.KIT,
        min_count=1,
        alternatives=(excavator, loader),
        is_lead=True,
    )
    rules = _single_position_rules(position, plan_entry.work_id)
    observations = (_frame((_loader(),)),)

    # Act
    assessment = service.assess_day(plan_entry, rules, observations)

    # Assert
    assert assessment.is_compliant is True
    assert assessment.confirmed_equipment == ("Погрузочная машина",)


def test_missing_work_evidence_breaks_compliance(plan_entry) -> None:
    # Arrange
    service = RuleEngineService()
    evidence = PositionAlternative(
        machine_type="Монолитная плита",
        source=EquipmentSource.VLM,
        vlm_question="Видны ли признаки устройства монолитной плиты?",
    )
    position = WorkPosition(
        position="Монолитная плита",
        kind=PositionKind.WORK_EVIDENCE,
        min_count=1,
        alternatives=(evidence,),
    )
    rules = _single_position_rules(position, plan_entry.work_id)
    observations = (_frame((_excavator(),)),)

    # Act
    assessment = service.assess_day(plan_entry, rules, observations)

    # Assert
    assert assessment.deviations[0].kind is DeviationKind.MISSING_WORK_EVIDENCE
    assert assessment.is_compliant is False


def test_отсутствие_сопутствующей_машины_не_даёт_отклонения(plan_entry) -> None:
    # Arrange
    service = RuleEngineService()
    truck = PositionAlternative(
        machine_type="Самосвал",
        source=EquipmentSource.DETECTOR,
        detector_classes=("Dump truck",),
    )
    position = WorkPosition(
        position="Самосвал",
        kind=PositionKind.ACCOMPANYING,
        min_count=1,
        alternatives=(truck,),
    )
    rules = _single_position_rules(position, plan_entry.work_id)
    observations = (_frame((_excavator(),)),)

    # Act
    assessment = service.assess_day(plan_entry, rules, observations)

    # Assert: сопутствующая машина может быть, а может не быть — это не замечание
    assert assessment.deviations == ()
    assert assessment.is_compliant is True


def test_shortage_of_counted_position_names_found_and_required(plan_entry) -> None:
    # Arrange
    service = RuleEngineService()
    excavator = PositionAlternative(
        machine_type="Экскаватор",
        source=EquipmentSource.DETECTOR,
        detector_classes=("Excavator",),
    )
    position = WorkPosition(
        position="Экскаватор",
        kind=PositionKind.KIT,
        min_count=2,
        alternatives=(excavator,),
        is_lead=True,
    )
    rules = _single_position_rules(position, plan_entry.work_id)
    observations = (_frame((_excavator(count=1),)),)

    # Act
    assessment = service.assess_day(plan_entry, rules, observations)

    # Assert
    assert assessment.is_compliant is False
    assert "найдено 1 ед. из 2" in assessment.deviations[0].description


def test_detector_class_outside_rules_is_not_counted(plan_entry, work_rules) -> None:
    # Arrange
    service = RuleEngineService()
    bulldozer = ObservedEquipment(
        machine_type="Bulldozer",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.WORKING,
        count=1,
    )
    observations = (_frame((bulldozer, _tower_crane())),)

    # Act
    assessment = service.assess_day(plan_entry, work_rules, observations)

    # Assert
    missing = [item.machine_type for item in assessment.deviations]
    assert "Экскаватор" in missing
