"""Сведение нескольких камер объекта в один ряд слотов.

На объекте стоит несколько камер, и каждая видит свой угол площадки. Работа, не попавшая
в одну камеру, вполне могла попасть в другую, поэтому правило простое: **отрезок засчитан,
если работа подтверждена хотя бы на одной камере**. Так же решается и всё остальное —
техника найдена, если найдена хоть где-то; комплект собран, если собран хоть на одной.

Обратное правило у ограниченного обзора: отрезок считается невидимым, только если фронт
работ не попал ни в одну камеру. Достаточно одной камеры, которая площадку видит, — и
отрезок разбирается по ней, а не списывается на ручную проверку.

Почему ленты сводятся уже готовыми, а не кадры до разбора: работа между кадрами
определяется сравнением соседних снимков **одной и той же камеры**. Смешать кадры разных
камер в один ряд значило бы принять смену ракурса за перемещение техники — на этом уже
обжигались в сентябре.
"""

import logging
from dataclasses import replace

from ..entity import ShiftSlot, ShiftTimeline

logger = logging.getLogger(__name__)

NO_TIMELINES_MESSAGE = "Нет ни одной ленты для сведения"


def merge_timelines(timelines: dict[str, ShiftTimeline]) -> ShiftTimeline:
    """Сводит ленты камер одного объекта в общую ленту смены."""
    if not timelines:
        raise ValueError(NO_TIMELINES_MESSAGE)
    ordered = [timelines[name] for name in sorted(timelines)]
    base = ordered[0]
    if len(ordered) == 1:
        return base
    slots = tuple(
        _merge_slots(index, ordered, sorted(timelines))
        for index in range(max(len(item.slots) for item in ordered))
    )
    merged = ShiftTimeline(
        plan_date=base.plan_date,
        work_id=base.work_id,
        slot_minutes=base.slot_minutes,
        slots=slots,
    )
    logger.info(
        "Камер сведено: %d, засчитано отрезков %d из %d",
        len(ordered),
        merged.counted_slots,
        len(merged.slots),
    )
    return merged


def _merge_slots(index: int, timelines: list[ShiftTimeline], names: list[str]) -> ShiftSlot:
    """Сводит один и тот же отрезок по всем камерам."""
    found = [
        (name, timeline.slots[index])
        for name, timeline in zip(names, timelines)
        if index < len(timeline.slots)
    ]
    seen = [(name, slot) for name, slot in found if slot.frame_id is not None]
    if not seen:
        return found[0][1]
    winner = _leading_slot(seen)
    merged = replace(
        winner,
        has_equipment=any(slot.has_equipment for _, slot in seen),
        has_kit=any(slot.has_kit for _, slot in seen),
        has_motion=any(slot.has_motion for _, slot in seen),
        # Отрезок невидим, только если площадку не видит ни одна камера.
        limited_view=all(slot.limited_view for _, slot in seen),
        foreign_equipment=_union_foreign(seen),
    )
    return merged


def _leading_slot(seen: list[tuple[str, ShiftSlot]]) -> ShiftSlot:
    """Берёт за основу отрезок той камеры, которая дала больше всего признаков.

    От неё в общий отрезок попадают снимок и время: показывать надо тот кадр, по
    которому работа и засчитана, иначе в разборе окажется кадр соседней камеры,
    где не видно ничего.
    """
    best = max(seen, key=lambda item: (len(item[1].stripes), not item[1].limited_view))
    return best[1]


def _union_foreign(seen: list[tuple[str, ShiftSlot]]) -> tuple[str, ...]:
    """Собирает чужую технику со всех камер отрезка без повторов."""
    machines: list[str] = []
    for _, slot in seen:
        machines.extend(name for name in slot.foreign_equipment if name not in machines)
    return tuple(machines)
