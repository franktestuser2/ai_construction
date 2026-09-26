"""Сборка сводки план-факта для показа.

Держит в одном месте перевод разобранных смен в числа плана и факта и подготовку
этих чисел для языковой модели: считает сервис, модель только излагает словами.
"""

import logging

from ..entity import ShiftTimeline
from .plan_fact import PlanFact, build_plan_fact, build_stage_fact

logger = logging.getLogger(__name__)

SUMMARY_TEMPLATE = (
    "плановый объём {planned} отрезков по {minutes} минут; измерено {measured}; "
    "подтверждено работой {counted}; вне контроля ИИ {limited}; "
    "выполнение {completion:.0f}% от измеренного; отставание {lag} дня"
)
STAGE_TEMPLATE = (
    "- {title}: план {planned}, измерено {measured}, подтверждено {counted}, "
    "вне контроля {limited}, выполнение {completion:.0f}%"
)
PERCENT = 100


def build_report(
    timelines: dict[str, ShiftTimeline],
    titles: dict[str, str],
    slots_per_shift: int,
) -> PlanFact:
    """Считает план-факт по разобранным сменам."""
    facts = tuple(
        build_stage_fact(timeline, titles.get(work_id, work_id), slots_per_shift)
        for work_id, timeline in sorted(timelines.items())
    )
    report = build_plan_fact(facts, slots_per_shift)
    return report


def describe_summary(report: PlanFact, slot_minutes: int) -> str:
    """Готовит сводку по объекту для языковой модели."""
    text = SUMMARY_TEMPLATE.format(
        planned=report.planned_slots,
        minutes=slot_minutes,
        measured=report.measured_slots,
        counted=report.counted_slots,
        limited=report.limited_slots,
        completion=report.completion * PERCENT,
        lag=report.lag_days,
    )
    return text


def describe_stages(report: PlanFact) -> str:
    """Готовит перечень этапов для языковой модели."""
    lines = [
        STAGE_TEMPLATE.format(
            title=stage.title,
            planned=stage.planned_slots,
            measured=stage.measured_slots,
            counted=stage.counted_slots,
            limited=stage.limited_slots,
            completion=stage.completion * PERCENT,
        )
        for stage in report.stages
    ]
    text = "\n".join(lines)
    return text
