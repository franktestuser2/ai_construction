"""План-факт по календарному графику: идём ли мы по нему.

Это главный вопрос сервиса, и считается он намеренно просто, чтобы вывод
можно было проверить на бумаге.

**План** задаёт календарный график: длительность смены в отрезках умножается
на число дней этапа. **Факт** — отрезки, по которым собраны все признаки работы.

Отрезки, где фронт работ не попал в кадр, **вычитаются из плана**, а не считаются
невыполненными: иначе сервис записывал бы в отставание плохо поставленную камеру.
Поэтому доля выполнения считается от измеренного объёма, а неизмеренное
показывается отдельным числом.
"""

import logging
from dataclasses import dataclass

from ..entity import ShiftTimeline, StageStatus

logger = logging.getLogger(__name__)

NOTHING = 0
FULL_SHARE = 1.0
# Ниже этой доли выполнения этап считается отстающим, выше — идущим с опережением.
BEHIND_SHARE = 0.9
AHEAD_SHARE = 1.0
DAY_ROUNDING = 1


@dataclass(frozen=True)
class StageFact:
    """План и факт по одному этапу календарного графика."""

    work_id: str
    title: str
    plan_date: str
    planned_slots: int
    counted_slots: int
    limited_slots: int
    slot_minutes: int
    empty_slots: int = NOTHING

    @property
    def measured_slots(self) -> int:
        """Отрезки, по которым вообще можно судить: план без неизмеренного.

        Не измерены две вещи: отрезки, где фронт работ не виден, и отрезки, на которые
        снимка не пришло вовсе. Ни те, ни другие не говорят о работе подрядчика, и
        держать их в знаменателе значит записывать в отставание пробелы съёмки.
        """
        measured = self.planned_slots - self.limited_slots - self.empty_slots
        return max(measured, NOTHING)

    @property
    def completion(self) -> float:
        """Доля выполнения от измеренного объёма."""
        if self.measured_slots == NOTHING:
            return NOTHING
        share = self.counted_slots / self.measured_slots
        return share

    @property
    def lag_slots(self) -> int:
        """Сколько измеренных отрезков не подтверждено работой."""
        lag = self.measured_slots - self.counted_slots
        return max(lag, NOTHING)

    @property
    def status(self) -> StageStatus:
        """Статус этапа относительно графика."""
        if self.measured_slots == NOTHING:
            return StageStatus.RISK_OF_DELAY
        if self.completion >= AHEAD_SHARE:
            return StageStatus.ON_SCHEDULE
        if self.completion >= BEHIND_SHARE:
            return StageStatus.RISK_OF_DELAY
        return StageStatus.DELAYED


@dataclass(frozen=True)
class PlanFact:
    """Сводка план-факта по объекту целиком."""

    stages: tuple[StageFact, ...]
    slots_per_shift: int

    @property
    def planned_slots(self) -> int:
        """Плановый объём в отрезках."""
        total = sum(stage.planned_slots for stage in self.stages)
        return total

    @property
    def measured_slots(self) -> int:
        """Объём, который удалось измерить."""
        total = sum(stage.measured_slots for stage in self.stages)
        return total

    @property
    def counted_slots(self) -> int:
        """Подтверждённый работой объём."""
        total = sum(stage.counted_slots for stage in self.stages)
        return total

    @property
    def limited_slots(self) -> int:
        """Отрезки вне контроля ИИ: требуют ручной проверки."""
        total = sum(stage.limited_slots for stage in self.stages)
        return total

    @property
    def completion(self) -> float:
        """Доля выполнения по объекту от измеренного объёма."""
        if self.measured_slots == NOTHING:
            return NOTHING
        share = self.counted_slots / self.measured_slots
        return share

    @property
    def lag_days(self) -> float:
        """Отставание в днях: неподтверждённый объём, делённый на длину смены."""
        if self.slots_per_shift == NOTHING:
            return NOTHING
        lag = (self.measured_slots - self.counted_slots) / self.slots_per_shift
        return round(max(lag, NOTHING), DAY_ROUNDING)

    @property
    def status(self) -> StageStatus:
        """Итоговый вывод по объекту."""
        if self.measured_slots == NOTHING:
            return StageStatus.RISK_OF_DELAY
        if self.completion >= AHEAD_SHARE:
            return StageStatus.ON_SCHEDULE
        if self.completion >= BEHIND_SHARE:
            return StageStatus.RISK_OF_DELAY
        return StageStatus.DELAYED


def build_stage_fact(timeline: ShiftTimeline, title: str, planned_slots: int) -> StageFact:
    """Считает план-факт одного этапа по разобранной смене."""
    fact = StageFact(
        work_id=timeline.work_id,
        title=title,
        plan_date=timeline.plan_date.isoformat(),
        planned_slots=planned_slots,
        counted_slots=timeline.counted_slots,
        limited_slots=timeline.limited_slots,
        slot_minutes=timeline.slot_minutes,
        empty_slots=timeline.empty_slots,
    )
    return fact


def build_plan_fact(stages: tuple[StageFact, ...], slots_per_shift: int) -> PlanFact:
    """Собирает сводку по объекту и пишет её в журнал."""
    summary = PlanFact(stages=stages, slots_per_shift=slots_per_shift)
    logger.info(
        "План-факт: выполнено %.0f%% от измеренного, отставание %.1f дня, вне контроля ИИ %d отрезков",
        summary.completion * 100,
        summary.lag_days,
        summary.limited_slots,
    )
    return summary
