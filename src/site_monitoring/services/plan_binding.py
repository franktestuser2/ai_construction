"""Привязка календарного плана к датам наблюдений."""

import logging
from datetime import date

from ..entity import PlanEntry

logger = logging.getLogger(__name__)


class PlanBindingService:
    """Отвечает на вопрос, какая работа активна в конкретный день проекта."""

    def __init__(self, entries: tuple[PlanEntry, ...]) -> None:
        self._entries = entries
        self._by_date: dict[date, PlanEntry] = {entry.plan_date: entry for entry in entries}

    def entry_for_date(self, observation_date: date) -> PlanEntry | None:
        """Находит запись плана на указанную дату."""
        entry = self._by_date.get(observation_date)
        if entry is None:
            logger.info("На дату %s работ в плане нет", observation_date)
        return entry

    def planned_dates(self, work_id: str) -> tuple[date, ...]:
        """Возвращает все плановые даты одного вида работ."""
        dates = tuple(entry.plan_date for entry in self._entries if entry.work_id == work_id)
        return dates

    def planned_duration(self, work_id: str) -> int:
        """Считает плановую длительность вида работ в календарных днях."""
        duration = len(self.planned_dates(work_id))
        return duration

    def stage_start(self, work_id: str) -> date | None:
        """Определяет плановую дату начала вида работ."""
        dates = self.planned_dates(work_id)
        if not dates:
            return None
        start = min(dates)
        return start

    def stage_finish(self, work_id: str) -> date | None:
        """Определяет плановую дату окончания вида работ."""
        dates = self.planned_dates(work_id)
        if not dates:
            return None
        finish = max(dates)
        return finish
