"""Общие фикстуры тестов сервиса контроля строительных площадок."""

import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from site_monitoring.entity import (  # noqa: E402
    EquipmentSource,
    PlanEntry,
    PositionAlternative,
    PositionKind,
    WorkEquipmentRules,
    WorkPosition,
)

DEMO_PROJECT_ID = "EDU-DEMO-001"
DEMO_WORK_ID = "W01"
DEMO_DATE = date(2026, 10, 5)


@pytest.fixture
def plan_entry() -> PlanEntry:
    """Запись календарного плана на первый день демо-проекта."""
    entry = PlanEntry(project_id=DEMO_PROJECT_ID, work_id=DEMO_WORK_ID, plan_date=DEMO_DATE)
    return entry


@pytest.fixture
def work_rules() -> WorkEquipmentRules:
    """Правила этапа: ведущий экскаватор от детектора и башенный кран от модели."""
    excavator = PositionAlternative(
        machine_type="Экскаватор",
        source=EquipmentSource.DETECTOR,
        detector_classes=("Excavator",),
    )
    crane = PositionAlternative(
        machine_type="Башенный кран",
        source=EquipmentSource.VLM,
        vlm_question="Есть ли на снимке башенный кран?",
    )
    lead_position = WorkPosition(
        position="Экскаватор",
        kind=PositionKind.KIT,
        min_count=1,
        alternatives=(excavator,),
        is_lead=True,
    )
    crane_position = WorkPosition(
        position="Башенный кран",
        kind=PositionKind.KIT,
        min_count=1,
        alternatives=(crane,),
    )
    rules = WorkEquipmentRules(work_id=DEMO_WORK_ID, positions=(lead_position, crane_position))
    return rules


@pytest.fixture
def workbook_path() -> Path:
    """Путь к книге Excel с демонстрационным планом."""
    path = PROJECT_ROOT / "materials" / "ЛТЦ_строительная_история_8_работ.xlsx"
    return path
