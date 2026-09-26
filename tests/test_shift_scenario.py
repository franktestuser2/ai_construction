"""Проверки раскладки синтетической смены по сценариям."""

import pytest

from site_monitoring.entity import SlotOutcome
from site_monitoring.services.shift_scenario import (
    SCENARIO_FULL,
    SCENARIO_HALF,
    SCENARIO_KIT,
    SCENARIO_LEFT,
    SCENARIO_LUNCH,
    SCENARIO_WIND,
    ShiftScenarioService,
)

SLOTS_IN_SHIFT = 24


def test_full_shift_counts_whole_shift() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act
    shift = service.build(SCENARIO_FULL)

    # Assert
    assert len(shift.slots) == SLOTS_IN_SHIFT
    assert shift.expected_hours == 8.0


def test_lunch_break_loses_one_hour() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act
    shift = service.build(SCENARIO_LUNCH)

    # Assert
    assert shift.expected_hours == 7.0
    assert all(slot.outcome is SlotOutcome.IDLE for slot in shift.slots if slot.clock.startswith("12:"))


def test_incomplete_kit_does_not_count_hours_without_truck() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act
    shift = service.build(SCENARIO_KIT)

    # Assert
    incomplete = [slot for slot in shift.slots if not slot.kit_present]
    assert len(incomplete) == 12
    assert all(slot.machine_moves for slot in incomplete)
    assert shift.expected_hours == 4.0


def test_equipment_left_marks_absent_slots() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act
    shift = service.build(SCENARIO_LEFT)

    # Assert
    absent = [slot for slot in shift.slots if not slot.lead_present]
    assert len(absent) == 9
    assert shift.expected_hours == 5.0


def test_wind_only_gives_no_hours() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act
    shift = service.build(SCENARIO_WIND)

    # Assert
    assert shift.expected_hours == 0.0
    assert all(slot.camera_shake for slot in shift.slots)
    assert not any(slot.machine_moves for slot in shift.slots)


def test_half_day_idle_counts_half() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act
    shift = service.build(SCENARIO_HALF)

    # Assert
    assert shift.expected_hours == 4.0


def test_unknown_scenario_is_rejected() -> None:
    # Arrange
    service = ShiftScenarioService()

    # Act & Assert
    with pytest.raises(ValueError):
        service.build("нет такого сценария")
