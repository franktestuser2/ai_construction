"""Сверка наблюдаемой на снимках техники с требованиями календарного плана.

Правила проверяются по методике `docs/work_activity_methodology.md`: сначала
признак работ, затем комплект техники, и только потом сопутствующая техника.
Комплект проверяется целиком, если за день есть серия снимков; по одному кадру
в сутки комплект проверить нечем, поэтому гейтит только ведущая позиция.

"""

import logging

from ..entity import (
    DayAssessment,
    Deviation,
    DeviationKind,
    EquipmentStatus,
    FrameObservation,
    PlanEntry,
    PositionKind,
    WorkEquipmentRules,
    WorkPosition,
)
from .position_matching import match_position

logger = logging.getLogger(__name__)

MIN_FRAMES_FOR_KIT = 2
NO_DATA_DESCRIPTION = "За дату нет ни одного снимка с разобранными метаданными"
LIMITED_VIEW_DESCRIPTION = "Фронт работ перекрыт или не попадает в кадр: день не измерен"
MISSING_EVIDENCE_TEMPLATE = "Признак работ «{position}» на снимках не виден"
MISSING_LEAD_TEMPLATE = "Ведущая позиция комплекта «{position}» не подтверждена: {detail}"
INCOMPLETE_KIT_TEMPLATE = "Комплект неполон: позиция «{position}» не закрыта, {detail}"
NOT_VERIFIED_TEMPLATE = (
    "Позиция комплекта «{position}» не подтверждена: за день один снимок, "
    "цикличная техника в него может не попасть"
)
IDLE_TEMPLATE = "Ведущая позиция «{position}» на месте, но ни на одном снимке не работает"
SHORTAGE_DETAIL = "найдено {found} ед. из {required}"
NOTHING_DETAIL = "не найдена ни на одном снимке"
BLOCKING_KINDS = (
    DeviationKind.MISSING_EQUIPMENT,
    DeviationKind.MISSING_WORK_EVIDENCE,
    DeviationKind.INCOMPLETE_KIT,
    DeviationKind.IDLE_EQUIPMENT,
    DeviationKind.NO_DATA,
)


class RuleEngineService:
    """Выносит по каждому дню плана вердикт «соответствие» или «отклонение»."""

    def __init__(self, min_frames_for_kit: int = MIN_FRAMES_FOR_KIT) -> None:
        self._min_frames_for_kit = min_frames_for_kit

    def assess_day(
        self,
        plan_entry: PlanEntry,
        rules: WorkEquipmentRules,
        observations: tuple[FrameObservation, ...],
    ) -> DayAssessment:
        """Сверяет наблюдения за день с правилами этого вида работ."""
        if not observations:
            return self._no_data_assessment(plan_entry)
        limited = all(item.limited_view for item in observations)
        series = len(observations) >= self._min_frames_for_kit
        deviations: list[Deviation] = []
        confirmed: list[str] = []
        if limited:
            deviations.append(Deviation(DeviationKind.LIMITED_VIEW, None, LIMITED_VIEW_DESCRIPTION))
        for position in rules.positions:
            found = self._count_position(position, observations)
            working = self._is_working(position, observations)
            deviation = self._check_position(position, found, working, series)
            if deviation is None:
                confirmed.append(position.position)
                continue
            deviations.append(deviation)
        assessment = self._build_assessment(plan_entry, tuple(deviations), tuple(confirmed), not limited)
        return assessment

    def _no_data_assessment(self, plan_entry: PlanEntry) -> DayAssessment:
        """Формирует вердикт для дня, за который нет ни одного снимка."""
        no_data = Deviation(DeviationKind.NO_DATA, None, NO_DATA_DESCRIPTION)
        assessment = DayAssessment(
            plan_date=plan_entry.plan_date,
            work_id=plan_entry.work_id,
            is_compliant=False,
            deviations=(no_data,),
            is_verifiable=False,
        )
        return assessment

    def _build_assessment(
        self,
        plan_entry: PlanEntry,
        deviations: tuple[Deviation, ...],
        confirmed: tuple[str, ...],
        is_verifiable: bool,
    ) -> DayAssessment:
        """Собирает итоговый вердикт по дню с учётом серьёзности отклонений."""
        blocking = [item for item in deviations if item.kind in BLOCKING_KINDS]
        assessment = DayAssessment(
            plan_date=plan_entry.plan_date,
            work_id=plan_entry.work_id,
            is_compliant=not blocking,
            deviations=deviations,
            confirmed_equipment=confirmed,
            is_verifiable=is_verifiable,
        )
        logger.info(
            "День %s, работа %s: соответствие=%s, отклонений %d",
            plan_entry.plan_date,
            plan_entry.work_id,
            assessment.is_compliant,
            len(deviations),
        )
        return assessment

    def _check_position(
        self,
        position: WorkPosition,
        found: int,
        working: bool,
        series: bool,
    ) -> Deviation | None:
        """Возвращает отклонение, если позиция правил не закрыта."""
        if found >= position.min_count:
            if position.is_lead and not working:
                description = IDLE_TEMPLATE.format(position=position.position)
                return Deviation(DeviationKind.IDLE_EQUIPMENT, position.position, description)
            return None
        detail = self._shortage_detail(position, found)
        if position.kind is PositionKind.WORK_EVIDENCE:
            description = MISSING_EVIDENCE_TEMPLATE.format(position=position.position)
            return Deviation(DeviationKind.MISSING_WORK_EVIDENCE, position.position, description)
        # Сопутствующая техника на то и сопутствующая: она может быть на площадке,
        # а может не быть, и её отсутствие — не отклонение. Перечень таких машин широк,
        # иначе каждый кадр тонул бы в замечаниях вида «нет бульдозера».
        if position.kind in (PositionKind.ACCOMPANYING, PositionKind.CREW):
            return None
        kit_deviation = self._kit_deviation(position, detail, series)
        return kit_deviation

    def _kit_deviation(self, position: WorkPosition, detail: str, series: bool) -> Deviation:
        """Решает, чем считать незакрытую позицию комплекта: отклонением или непроверенным."""
        if position.is_lead:
            description = MISSING_LEAD_TEMPLATE.format(position=position.position, detail=detail)
            return Deviation(DeviationKind.MISSING_EQUIPMENT, position.position, description)
        if series:
            description = INCOMPLETE_KIT_TEMPLATE.format(position=position.position, detail=detail)
            return Deviation(DeviationKind.INCOMPLETE_KIT, position.position, description)
        description = NOT_VERIFIED_TEMPLATE.format(position=position.position)
        return Deviation(DeviationKind.NOT_VERIFIED, position.position, description)

    def _shortage_detail(self, position: WorkPosition, found: int) -> str:
        """Формулирует, чего именно не хватило позиции."""
        if found:
            return SHORTAGE_DETAIL.format(found=found, required=position.min_count)
        return NOTHING_DETAIL

    def _count_position(self, position: WorkPosition, observations: tuple[FrameObservation, ...]) -> int:
        """Считает, сколько единиц закрывают позицию: берётся лучший снимок дня."""
        best = 0
        for observation in observations:
            matched = match_position(position, observation.equipment)
            best = max(best, sum(item.count for item in matched))
        return best

    def _is_working(self, position: WorkPosition, observations: tuple[FrameObservation, ...]) -> bool:
        """Проверяет, что техника позиции хотя бы на одном снимке работает."""
        for observation in observations:
            matched = match_position(position, observation.equipment)
            if any(item.status is EquipmentStatus.WORKING for item in matched):
                return True
        return False
