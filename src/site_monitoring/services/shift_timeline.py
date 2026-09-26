"""Разбор смены на двадцатиминутные слоты.

Снимок приходит раз в двадцать минут. Полосок всегда три, но на фасадном этапе
у них свой смысл: там работает только фасадный пайплайн, техника не проверяется вовсе.

| Полоска | Обычный этап | Фасадный этап |
| --- | --- | --- |
| жёлтая | на кадре видна техника этапа | здание найдено на снимке |
| оранжевая | комплект собран за смену | ячейки фасада разобраны |
| зелёная | техника работала между кадрами | состав ячеек изменился с прошлым кадром |

Первый снимок смены сравнивать не с чем, поэтому там хватает двух признаков.
Слот, на который снимка не пришло, не засчитывается.
"""

import logging
from datetime import datetime, timedelta

from ..entity import (
    FacadeReadiness,
    FrameObservation,
    PlanEntry,
    PositionKind,
    ShiftFrames,
    ShiftSlot,
    ShiftTimeline,
    WorkEquipmentRules,
    WorkPosition,
)
from .position_matching import match_position

logger = logging.getLogger(__name__)

NOTHING_FOUND = 0
FIRST_SLOT_INDEX = 0
# Доли ячеек ниже этого сдвига списываем на шум детектора, а не на работу.
FACADE_CHANGE_THRESHOLD = 0.05


def _facade_changed(previous: FacadeReadiness | None, current: FacadeReadiness | None) -> bool:
    """Изменился ли состав ячеек фасада по сравнению с прошлым кадром.

    Считается по долям стадий: проём заложили или застеклили — доли сдвинулись.
    Порог отсекает дрожание детектора на одной и той же стене.
    """
    if previous is None or current is None:
        return False
    closed = abs(current.closed_share - previous.closed_share)
    glazed = abs(current.glazed_share - previous.glazed_share)
    changed = max(closed, glazed) >= FACADE_CHANGE_THRESHOLD
    return changed


def _count_matched(position: WorkPosition, observation: FrameObservation) -> int:
    """Считает подтверждённые единицы техники, закрывающие позицию.

    Смотреть на саму запись мало: у находки, все рамки которой отклонил арбитр,
    счётчик равен нулю, и засчитывать такую технику как присутствующую нельзя.
    """
    matched = match_position(position, observation.equipment)
    total = sum(item.count for item in matched)
    return total


class ShiftTimelineService:
    """Собирает ленту слотов смены из наблюдений по снимкам и сравнений пар кадров."""

    def __init__(self, slot_minutes: int, slots_per_shift: int, shift_start_hour: int) -> None:
        self._slot_minutes = slot_minutes
        self._slots_per_shift = slots_per_shift
        self._shift_start_hour = shift_start_hour

    def build_timeline(self, rules: WorkEquipmentRules, frames: ShiftFrames) -> ShiftTimeline:
        """Раскладывает смену по слотам и отмечает, какие из них засчитаны."""
        builder = self._facade_slot if frames.is_facade else self._equipment_slot
        slots = tuple(builder(index, rules, frames) for index in range(self._slots_per_shift))
        timeline = ShiftTimeline(
            plan_date=frames.plan_entry.plan_date,
            work_id=frames.plan_entry.work_id,
            slot_minutes=self._slot_minutes,
            slots=slots,
        )
        logger.info(
            "Смена %s по работе %s: засчитано %d слотов из %d",
            frames.plan_entry.plan_date,
            frames.plan_entry.work_id,
            timeline.counted_slots,
            len(slots),
        )
        return timeline

    def _equipment_slot(self, index: int, rules: WorkEquipmentRules, frames: ShiftFrames) -> ShiftSlot:
        """Собирает слот обычного этапа: техника, комплект и её работа между кадрами."""
        observations = frames.observations
        observation = observations[index] if index < len(observations) else None
        motion = frames.motions[index] if index < len(frames.motions) else None
        # Комплект — признак всей смены: вторая или третья машина должна появиться
        # хотя бы раз за день, а не в каждом слоте отдельно.
        kit_collected = self._is_kit_collected(rules, observations)
        slot = ShiftSlot(
            index=index,
            starts_at=self._slot_start(frames.plan_entry, index),
            frame_id=observation.frame_id if observation is not None else None,
            has_equipment=self._has_equipment(rules, observation),
            has_kit=kit_collected and observation is not None,
            has_motion=motion is not None and motion.has_motion,
            is_first=index == FIRST_SLOT_INDEX,
        )
        return slot

    def _facade_slot(self, index: int, rules: WorkEquipmentRules, frames: ShiftFrames) -> ShiftSlot:
        """Собирает слот фасадного этапа: здание, ячейки и изменение их состава."""
        readiness = frames.facade[index] if index < len(frames.facade) else None
        previous = frames.facade[index - 1] if FIRST_SLOT_INDEX < index <= len(frames.facade) else None
        frame_id = frames.frame_ids[index] if index < len(frames.frame_ids) else None
        slot = ShiftSlot(
            index=index,
            starts_at=self._slot_start(frames.plan_entry, index),
            frame_id=frame_id,
            has_equipment=readiness is not None,
            has_kit=readiness is not None and readiness.cells_total > NOTHING_FOUND,
            has_motion=_facade_changed(previous, readiness),
            is_first=index == FIRST_SLOT_INDEX,
        )
        return slot

    def _slot_start(self, plan_entry: PlanEntry, index: int) -> datetime:
        """Время начала слота внутри смены."""
        opening = datetime.combine(plan_entry.plan_date, datetime.min.time())
        start = opening + timedelta(hours=self._shift_start_hour, minutes=self._slot_minutes * index)
        return start

    def _has_equipment(
        self,
        rules: WorkEquipmentRules,
        observation: FrameObservation | None,
    ) -> bool:
        """Проверяет, видна ли на кадре техника этапа — ведущая или любая другая.

        Полоска отвечает на вопрос «техника на площадке есть», а не «есть именно ведущая»:
        машина из комплекта подтверждает присутствие техники ничуть не хуже. Признак
        работ в счёт не идёт — это состояние объекта, а не машина.
        """
        if observation is None:
            return False
        machines = self._machine_positions(rules)
        found = any(_count_matched(position, observation) > NOTHING_FOUND for position in machines)
        return found

    def _is_kit_collected(
        self,
        rules: WorkEquipmentRules,
        observations: tuple[FrameObservation, ...],
    ) -> bool:
        """Проверяет, появилась ли за смену хотя бы одна машина комплекта кроме ведущей."""
        positions = self._support_positions(rules)
        if not positions:
            return False
        for observation in observations:
            found = any(_count_matched(position, observation) > NOTHING_FOUND for position in positions)
            if found:
                return True
        return False

    def _machine_positions(self, rules: WorkEquipmentRules) -> tuple[WorkPosition, ...]:
        """Позиции правил, за которыми стоит машина, а не состояние объекта."""
        positions = tuple(
            position for position in rules.positions if position.kind is not PositionKind.WORK_EVIDENCE
        )
        return positions

    def _support_positions(self, rules: WorkEquipmentRules) -> tuple[WorkPosition, ...]:
        """Вторая и третья машины этапа: всё, кроме ведущей и признака работ.

        Берутся и комплект, и сопутствующая техника. В правилах четырёх этапов из семи
        второй машины в комплекте нет вовсе, она записана сопутствующей, и по одному
        только комплекту оранжевая полоска не зажглась бы там никогда.
        Признак работ — состояние самого объекта, а не машина, и в счёт не идёт.
        """
        positions = tuple(
            position
            for position in rules.positions
            if position.kind is not PositionKind.WORK_EVIDENCE and not position.is_lead
        )
        return positions
