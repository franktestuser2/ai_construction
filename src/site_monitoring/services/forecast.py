"""Прогноз завершения этапа и расчёт отставания от графика.

Реализует §11 методики: темп этапа считается как доля продуктивных суток,
прогноз завершения — через плановую длительность, делённую на темп.
"""

import logging
import math
from datetime import date, timedelta

from ..entity import StageForecast, StageStatus

logger = logging.getLogger(__name__)

RISK_THRESHOLD_SHARE = 0.1
ZERO_PACE = 0.0


class ForecastService:
    """Считает темп этапа, дату завершения и отставание в сутках."""

    def build_forecast(
        self,
        work_id: str,
        planned_days: int,
        stage_start: date,
        elapsed_days: int,
        productive_days: int,
    ) -> StageForecast:
        """Строит прогноз по этапу на основе накопленных продуктивных суток."""
        pace = self._calculate_pace(productive_days, elapsed_days)
        forecast_finish = self._calculate_finish(stage_start, planned_days, pace)
        lag_days = self._calculate_lag(stage_start, planned_days, forecast_finish)
        status = self._resolve_status(lag_days, planned_days)
        forecast = StageForecast(
            work_id=work_id,
            planned_days=planned_days,
            elapsed_days=elapsed_days,
            productive_days=productive_days,
            pace=pace,
            lag_days=lag_days,
            status=status,
            forecast_finish=forecast_finish,
        )
        logger.info("Этап %s: темп %.2f, отставание %d сут., статус %s", work_id, pace, lag_days, status.value)
        return forecast

    def _calculate_pace(self, productive_days: int, elapsed_days: int) -> float:
        """Считает фактический темп как долю продуктивных суток."""
        if elapsed_days <= 0:
            return ZERO_PACE
        pace = productive_days / elapsed_days
        return pace

    def _calculate_finish(self, stage_start: date, planned_days: int, pace: float) -> date | None:
        """Определяет прогнозную дату завершения этапа при текущем темпе."""
        if pace <= ZERO_PACE:
            return None
        required_days = math.ceil(planned_days / pace)
        finish = stage_start + timedelta(days=required_days - 1)
        return finish

    def _calculate_lag(self, stage_start: date, planned_days: int, forecast_finish: date | None) -> int:
        """Считает отставание в сутках относительно плановой даты окончания."""
        planned_finish = stage_start + timedelta(days=planned_days - 1)
        if forecast_finish is None:
            return planned_days
        lag = (forecast_finish - planned_finish).days
        return lag

    def _resolve_status(self, lag_days: int, planned_days: int) -> StageStatus:
        """Переводит отставание в статус этапа по порогам методики."""
        if lag_days <= 0:
            return StageStatus.ON_SCHEDULE
        risk_limit = planned_days * RISK_THRESHOLD_SHARE
        if lag_days <= risk_limit:
            return StageStatus.RISK_OF_DELAY
        return StageStatus.DELAYED
