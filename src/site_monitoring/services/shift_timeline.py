"""Разбор смены на двадцатиминутные слоты.

Снимок приходит раз в двадцать минут. Полосок всегда три, но на фасадном этапе
у них свой смысл: там работает только фасадный пайплайн, техника не проверяется вовсе.

| Полоска | Обычный этап | Фасадный этап |
| --- | --- | --- |
| жёлтая | на кадре видна техника этапа | здание найдено на снимке |
| оранжевая | комплект собран за смену | ячейки фасада разобраны |
| зелёная | техника работала между кадрами | состав ячеек изменился с прошлым кадром |

Отдельно отмечается техника, которой на этапе быть не должно: на зачёт отрезка
она не влияет, но по требованиям это отклонение, и оно показывается.

Отдельно отмечаются отрезки, по которым фронт работ в кадр не попал: они не
засчитываются, но и в отставание не пишутся — по требованиям такой участок
считается вне контроля ИИ и требует ручной проверки. Судит об этом модель по самому
снимку, а сервис отклоняет её жалобу в одном случае: техника этапа найдена и её работа
между кадрами подтверждена. Раз видно и машину, и её работу, фронт работ в кадре есть.
Одной техники для этого мало: камера может смотреть машине в корму.

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
from .position_matching import is_same_equipment, match_position

logger = logging.getLogger(__name__)

NOTHING_FOUND = 0
FIRST_SLOT_INDEX = 0
SECONDS_IN_MINUTE = 60
# Доли ячеек ниже этого сдвига списываем на шум детектора, а не на работу.
FACADE_CHANGE_THRESHOLD = 0.05
# Ракурс сменился: сравнивать такой кадр не с чем, и работа по нему не измеряется.
SCENE_MISMATCH_REASON = "ракурс не совпадает со сценой смены"


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


def _foreign_equipment(
    rules: WorkEquipmentRules,
    observation: FrameObservation | None,
) -> tuple[str, ...]:
    """Отбирает технику, которой на этом этапе быть не должно.

    По требованию ТЗ появление такой машины — отклонение, а не просто шум:
    экскаватор на монтаже фасада означает, что на площадке идёт что-то другое.
    В зачёт отрезка она и так не шла, но молчать о ней нельзя.
    """
    if observation is None:
        return ()
    alternatives = [item for position in rules.positions for item in position.alternatives]
    foreign: list[str] = []
    for unit in observation.equipment:
        if unit.count <= NOTHING_FOUND:
            continue
        if any(is_same_equipment(alternative, unit) for alternative in alternatives):
            continue
        if unit.machine_type not in foreign:
            foreign.append(unit.machine_type)
    return tuple(foreign)


def _limited_by_scene(scene_mismatch: tuple[bool, ...], place: int | None) -> bool:
    """Снят ли кадр отрезка не с той сцены, что остальные кадры смены."""
    if place is None or place >= len(scene_mismatch):
        return False
    mismatch = scene_mismatch[place]
    return mismatch


def _is_view_limited(observation: FrameObservation | None, has_equipment: bool, has_motion: bool) -> bool:
    """Принимается ли жалоба модели на обзор.

    Жалоба отклоняется в одном случае: техника этапа на кадре найдена и сравнение
    с прошлым кадром показало, что она работает. Раз по снимку удалось увидеть
    и машину, и её работу, значит фронт работ в кадре и судить по нему можно.
    Одной техники мало: камера может смотреть машине в корму, и чем та занята,
    по такому кадру не скажешь.
    """
    if observation is None or not observation.limited_view:
        return False
    measurable = has_equipment and has_motion
    limited = not measurable
    return limited


def _limited_reason(observation: FrameObservation | None, off_scene: bool) -> str:
    """Выбирает объяснение для отрезка вне контроля ИИ.

    Смена ракурса важнее жалобы модели: если кадр пришёл с другого места,
    все прочие замечания к нему вторичны.
    """
    if off_scene:
        return SCENE_MISMATCH_REASON
    reason = observation.limited_reason if observation is not None else ""
    return reason


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
        places = self._places(frames)
        builder = self._facade_slot if frames.is_facade else self._equipment_slot
        slots = tuple(
            builder(index, rules, frames, places) for index in range(self._slots_per_shift)
        )
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

    def _equipment_slot(
        self, index: int, rules: WorkEquipmentRules, frames: ShiftFrames, places: dict[int, int]
    ) -> ShiftSlot:
        """Собирает слот обычного этапа: техника, комплект и её работа между кадрами."""
        observations = frames.observations
        place = places.get(index)
        observation = observations[place] if place is not None and place < len(observations) else None
        motion = frames.motions[place] if place is not None and place < len(frames.motions) else None
        # Комплект — признак всей смены: вторая или третья машина должна появиться
        # хотя бы раз за день, а не в каждом слоте отдельно.
        kit_collected = self._is_kit_collected(rules, observations)
        has_equipment = self._has_equipment(rules, observation)
        # Сцена сменилась — значит соседний кадр снят в другом месте, и разницу между
        # двумя разными местами легко принять за работу. Такой признак не засчитывается.
        off_scene = _limited_by_scene(frames.scene_mismatch, place)
        has_motion = motion is not None and motion.has_motion and not off_scene
        limited = off_scene or _is_view_limited(observation, has_equipment, has_motion)
        slot = ShiftSlot(
            index=index,
            starts_at=self._slot_start(frames, index),
            frame_id=observation.frame_id if observation is not None else None,
            has_equipment=has_equipment,
            # Комплект не бывает собран без главной машины: она в него и входит.
            # Дополнительная машина считается за смену, потому что цикличная техника
            # в каждый кадр не попадает, но без главной на кадре речи о комплекте нет.
            has_kit=kit_collected and has_equipment,
            has_motion=has_motion,
            is_first=index == FIRST_SLOT_INDEX,
            limited_view=limited,
            limited_reason=_limited_reason(observation, off_scene),
            scene_mismatch=off_scene,
            foreign_equipment=_foreign_equipment(rules, observation),
        )
        return slot

    def _facade_slot(
        self, index: int, rules: WorkEquipmentRules, frames: ShiftFrames, places: dict[int, int]
    ) -> ShiftSlot:
        """Собирает слот фасадного этапа: здание, ячейки и изменение их состава."""
        place = places.get(index)
        previous_place = places.get(index - 1)
        readiness = frames.facade[place] if place is not None and place < len(frames.facade) else None
        previous = (
            frames.facade[previous_place]
            if previous_place is not None and previous_place < len(frames.facade)
            else None
        )
        frame_id = frames.frame_ids[place] if place is not None and place < len(frames.frame_ids) else None
        off_scene = _limited_by_scene(frames.scene_mismatch, place)
        slot = ShiftSlot(
            index=index,
            starts_at=self._slot_start(frames, index),
            frame_id=frame_id,
            has_equipment=readiness is not None,
            has_kit=readiness is not None and readiness.cells_total > NOTHING_FOUND,
            # Кадр с другого ракурса сравнивать не с чем: изменение состава ячеек
            # между двумя разными зданиями ничего не значит.
            has_motion=_facade_changed(previous, readiness) and not off_scene,
            is_first=index == FIRST_SLOT_INDEX,
            # Здание в кадре не найдено — значит фронт работ в него не попал.
            limited_view=off_scene or (frame_id is not None and readiness is None),
            limited_reason=SCENE_MISMATCH_REASON if off_scene else "",
            scene_mismatch=off_scene,
        )
        return slot

    def _places(self, frames: ShiftFrames) -> dict[int, int]:
        """Раскладывает кадры по отрезкам смены: какой кадр в каком отрезке.

        Отрезок определяется временем съёмки, а не порядком кадра в списке. Разница
        видна, когда камера пропустила круг: при раскладке по порядку все последующие
        кадры сдвинулись бы влево, и пропуск в середине смены выглядел бы работой.

        Отсчёт идёт от первого кадра дня, а не от часа смены в настройках: когда именно
        на площадке началась смена, сервис не знает — он знает, когда её впервые увидел.
        """
        stamps = frames.captured_at
        if not stamps or all(item is None for item in stamps):
            return {index: index for index in range(len(frames.frame_ids))}
        base = next(item for item in stamps if item is not None)
        places: dict[int, int] = {}
        for position, stamp in enumerate(stamps):
            if stamp is None:
                continue
            offset = (stamp - base).total_seconds() / (self._slot_minutes * SECONDS_IN_MINUTE)
            index = round(offset)
            if FIRST_SLOT_INDEX <= index < self._slots_per_shift:
                places.setdefault(index, position)
        return places

    def _slot_start(self, frames: ShiftFrames, index: int) -> datetime:
        """Время начала слота внутри смены."""
        stamps = [item for item in frames.captured_at if item is not None]
        if stamps:
            return stamps[0] + timedelta(minutes=self._slot_minutes * index)
        opening = datetime.combine(frames.plan_entry.plan_date, datetime.min.time())
        start = opening + timedelta(hours=self._shift_start_hour, minutes=self._slot_minutes * index)
        return start

    def _has_equipment(
        self,
        rules: WorkEquipmentRules,
        observation: FrameObservation | None,
    ) -> bool:
        """Проверяет, видно ли на кадре того, кто делает работу.

        Это главная машина этапа — без экскаватора мусор не грузят, без подачи бетона
        не бетонируют, — либо бригада на фронте работ там, где работу делают руками.
        Прочие машины комплекта подтверждают организацию работ и считаются отдельно,
        за смену. Если ведущей позиции в правилах нет, годится любая машина комплекта.
        """
        if observation is None:
            return False
        positions = self._lead_positions(rules) or self._kit_positions(rules)
        found = any(_count_matched(position, observation) > NOTHING_FOUND for position in positions)
        return found

    def _lead_positions(self, rules: WorkEquipmentRules) -> tuple[WorkPosition, ...]:
        """Кто делает саму работу: главная машина или бригада на фронте работ.

        Бригада засчитывается наравне с машиной: арматуру вяжут и опалубку ставят
        люди, и техника при этом может простаивать — работа от этого идти не перестаёт.
        """
        positions = tuple(
            position
            for position in rules.positions
            if position.is_lead or position.kind is PositionKind.CREW
        )
        return positions

    def _kit_positions(self, rules: WorkEquipmentRules) -> tuple[WorkPosition, ...]:
        """Все машины комплекта этапа."""
        positions = tuple(
            position for position in rules.positions if position.kind is PositionKind.KIT
        )
        return positions

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
        """Машины комплекта кроме главной: без них работа не идёт.

        Берётся только комплект. Допустимая техника — прицеп, бульдозер, лишний
        экскаватор — на площадке бывает, отклонением не считается, но и комплект
        не закрывает: работу делают не они.
        """
        positions = tuple(
            position
            for position in rules.positions
            if position.kind is PositionKind.KIT and not position.is_lead
        )
        return positions
