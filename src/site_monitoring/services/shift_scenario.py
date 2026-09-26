"""Раскладка синтетической смены по 20-минутным слотам.

Сервис знает только про время и ожидаемые исходы слотов: с изображениями
и файлами он не работает.
"""

import logging

from ..entity import SlotOutcome, SyntheticShift, SyntheticSlot

logger = logging.getLogger(__name__)

SHIFT_START_HOUR = 8
SHIFT_HOURS = 8
SLOT_MINUTES = 20
SLOTS_PER_HOUR = 3
MINUTES_IN_HOUR = 60
SLOT_HOURS = SLOT_MINUTES / MINUTES_IN_HOUR

SCENARIO_FULL = "full_shift"
SCENARIO_LUNCH = "lunch_break"
SCENARIO_HALF = "half_day_idle"
SCENARIO_LEFT = "equipment_left"
SCENARIO_KIT = "incomplete_kit"
SCENARIO_WIND = "wind_only"

_TITLES = {
    SCENARIO_FULL: "Полная смена: комплект на месте, работа идёт весь день",
    SCENARIO_LUNCH: "Смена с обедом: простой с 12:00 до 13:00",
    SCENARIO_HALF: "Полсмены: после 12:00 техника стоит",
    SCENARIO_LEFT: "Техника уехала: после 13:00 площадка пуста",
    SCENARIO_KIT: "Неполный комплект: с 10:00 до 14:00 нет второй машины",
    SCENARIO_WIND: "Только ветер: техника стоит, камеру качает весь день",
}


class ShiftScenarioService:
    """Строит раскладку смены по названию сценария."""

    def build(self, scenario: str) -> SyntheticShift:
        """Возвращает слоты смены и ожидаемое число зачтённых часов."""
        title = _TITLES.get(scenario)
        if title is None:
            raise ValueError(f"Неизвестный сценарий смены: {scenario}")
        slots = tuple(self._build_slot(scenario, index) for index in range(SHIFT_HOURS * SLOTS_PER_HOUR))
        expected = self._expected_hours(slots)
        shift = SyntheticShift(scenario=scenario, title=title, slots=slots, expected_hours=expected)
        logger.info("Сценарий %s: слотов %d, ожидаем %.2f ч", scenario, len(slots), expected)
        return shift

    def _build_slot(self, scenario: str, index: int) -> SyntheticSlot:
        """Определяет состояние одного слота смены."""
        hour = SHIFT_START_HOUR + index // SLOTS_PER_HOUR
        clock = f"{hour:02d}:{(index % SLOTS_PER_HOUR) * SLOT_MINUTES:02d}"
        outcome = self._outcome(scenario, hour)
        lead_present = outcome is not SlotOutcome.ABSENT
        kit_present = lead_present and outcome is not SlotOutcome.INCOMPLETE_KIT
        slot = SyntheticSlot(
            index=index,
            clock=clock,
            outcome=outcome,
            lead_present=lead_present,
            kit_present=kit_present,
            machine_moves=outcome in (SlotOutcome.WORKING, SlotOutcome.INCOMPLETE_KIT),
            camera_shake=True,
        )
        return slot

    def _outcome(self, scenario: str, hour: int) -> SlotOutcome:
        """Сопоставляет часу смены ожидаемый исход слота."""
        if scenario == SCENARIO_WIND:
            return SlotOutcome.IDLE
        if scenario == SCENARIO_LUNCH and hour == 12:
            return SlotOutcome.IDLE
        if scenario == SCENARIO_HALF and hour >= 12:
            return SlotOutcome.IDLE
        if scenario == SCENARIO_LEFT and hour >= 13:
            return SlotOutcome.ABSENT
        if scenario == SCENARIO_KIT and 10 <= hour < 14:
            return SlotOutcome.INCOMPLETE_KIT
        return SlotOutcome.WORKING

    def _expected_hours(self, slots: tuple[SyntheticSlot, ...]) -> float:
        """Считает часы, которые должна зачесть методика: комплект полон и есть движение."""
        counted = [slot for slot in slots if slot.kit_present and slot.machine_moves]
        expected = round(len(counted) * SLOT_HOURS, 2)
        return expected
