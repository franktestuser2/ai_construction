"""Тесты сквозного сценария фасада на календарном плане проекта."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import Settings  # noqa: E402
from site_monitoring.container import build_dependencies  # noqa: E402
from site_monitoring.entity import DeviationKind, StageStatus  # noqa: E402

FIRST_DAY = "2026-10-06"
SECOND_DAY = "2026-10-09"
DAY_OUTSIDE_PLAN = "2020-01-01"
CLEANUP_WORK_ID = "W01"


@pytest.fixture
def facade():
    """Фасад домена, собранный на реальных файлах проекта."""
    settings = Settings(
        workbook_path=PROJECT_ROOT / "materials" / "ЛТЦ_строительная_история_8_работ.xlsx",
        equipment_rules_path=PROJECT_ROOT / "config" / "equipment_rules_v3.json",
        calendar_plan_path=PROJECT_ROOT / "config" / "calendar_plan_new.json",
    )
    dependencies = build_dependencies(settings)
    return dependencies.facade


def _frame(equipment: list[dict[str, object]], frame_id: str = "frame-1") -> dict[str, object]:
    """Сырой снимок в том виде, в каком он приходит на вход фасада."""
    frame = {"frame_id": frame_id, "observed_on": FIRST_DAY, "equipment": equipment}
    return frame


def _detector_item(machine_type: str, status: str = "работает") -> dict[str, object]:
    """Находка детектора в сыром виде."""
    item = {"machine_type": machine_type, "source": "detector", "status": status, "count": 1}
    return item


def test_full_kit_day_is_compliant(facade) -> None:
    # Arrange
    equipment = [_detector_item("Excavator"), _detector_item("Dump truck")]
    payload = {"observation_date": FIRST_DAY, "frames": [_frame(equipment)]}

    # Act
    assessment = facade.assess_day(payload)

    # Assert
    assert assessment.work_id == CLEANUP_WORK_ID
    assert assessment.is_compliant is True


def test_single_frame_without_truck_is_not_a_deviation(facade) -> None:
    # Arrange
    equipment = [_detector_item("Excavator")]
    payload = {"observation_date": FIRST_DAY, "frames": [_frame(equipment)]}

    # Act
    assessment = facade.assess_day(payload)

    # Assert
    kinds = [item.kind for item in assessment.deviations]
    assert kinds == [DeviationKind.NOT_VERIFIED]
    assert assessment.is_compliant is True


def test_series_without_truck_breaks_kit(facade) -> None:
    # Arrange
    equipment = [_detector_item("Excavator")]
    frames = [_frame(equipment, "frame-1"), _frame(equipment, "frame-2")]
    payload = {"observation_date": FIRST_DAY, "frames": frames}

    # Act
    assessment = facade.assess_day(payload)

    # Assert
    kinds = [item.kind for item in assessment.deviations]
    assert DeviationKind.INCOMPLETE_KIT in kinds
    assert assessment.is_compliant is False


def test_missing_loading_machine_breaks_compliance(facade) -> None:
    # Arrange
    equipment = [_detector_item("Dump truck")]
    payload = {"observation_date": FIRST_DAY, "frames": [_frame(equipment)]}

    # Act
    assessment = facade.assess_day(payload)

    # Assert
    kinds = [item.kind for item in assessment.deviations]
    assert DeviationKind.MISSING_EQUIPMENT in kinds
    assert assessment.is_compliant is False


def test_date_outside_plan_is_rejected(facade) -> None:
    # Arrange
    payload = {"observation_date": DAY_OUTSIDE_PLAN, "frames": []}

    # Act
    assessment = facade.assess_day(payload)

    # Assert
    assert assessment.is_compliant is False
    assert assessment.deviations[0].kind is DeviationKind.NO_DATA


def test_stage_forecast_uses_compliant_days(facade) -> None:
    # Arrange
    equipment = [_detector_item("Excavator"), _detector_item("Dump truck")]
    payload = {"observation_date": FIRST_DAY, "frames": [_frame(equipment)]}
    assessment = facade.assess_day(payload)

    # Act
    forecast = facade.assess_stage(CLEANUP_WORK_ID, (assessment,))

    # Assert
    assert forecast is not None
    assert forecast.productive_days == 1
    assert forecast.status is StageStatus.ON_SCHEDULE


def test_forecast_for_unknown_stage_is_empty(facade) -> None:
    # Act
    forecast = facade.assess_stage("W999", ())

    # Assert
    assert forecast is None



def _domain_facade_with_spy(facade_check: bool, calls: list[str]):
    """Собирает фасад домена со шпионами вместо моделей."""
    from datetime import date

    from site_monitoring.entity import FrameObservation, PlanEntry, WorkEquipmentRules
    from site_monitoring.facade import SiteMonitoringFacade
    from site_monitoring.services.forecast import ForecastService
    from site_monitoring.services.plan_binding import PlanBindingService
    from site_monitoring.services.rule_engine import RuleEngineService

    class _SpyFacadeReadiness:
        def assess_frame(self, frame_id: str, image_path: Path):
            calls.append(frame_id)
            return None

    class _StubRecognition:
        def recognize_frame(self, frame_id, image_path, observed_on, work_name, rules):
            observation = FrameObservation(
                frame_id=frame_id,
                observed_on=observed_on,
                equipment=(),
            )
            return observation

    rules = WorkEquipmentRules(work_id=CLEANUP_WORK_ID, positions=(), facade_check=facade_check)
    entry = PlanEntry(project_id="EDU-DEMO-001", work_id=CLEANUP_WORK_ID, plan_date=date(2026, 10, 6))
    domain_facade = SiteMonitoringFacade(
        plan_binding=PlanBindingService((entry,)),
        rule_engine=RuleEngineService(),
        forecast=ForecastService(),
        rules_by_work={CLEANUP_WORK_ID: rules},
        works_by_id={},
        recognition=_StubRecognition(),
        facade_readiness=_SpyFacadeReadiness(),
    )
    return domain_facade


def _images_payload() -> dict[str, object]:
    """Вход с путём к снимку, как его принимает разбор по изображениям."""
    frame = {"frame_id": "frame-1", "image_path": "data/photos_v2/W07/W07_2027-07-15_frame1.jpg"}
    payload = {"observation_date": FIRST_DAY, "frames": [frame]}
    return payload


def test_фасадная_ветка_не_запускается_на_нефасадном_этапе() -> None:
    # Arrange
    calls: list[str] = []
    domain_facade = _domain_facade_with_spy(facade_check=False, calls=calls)

    # Act
    domain_facade.assess_day_from_images(_images_payload())

    # Assert
    assert calls == []


def test_фасадная_ветка_запускается_на_фасадном_этапе() -> None:
    # Arrange
    calls: list[str] = []
    domain_facade = _domain_facade_with_spy(facade_check=True, calls=calls)

    # Act
    domain_facade.assess_day_from_images(_images_payload())

    # Assert
    assert calls == ["frame-1"]
