"""Тесты прогноза завершения этапа и расчёта отставания."""

from datetime import date

from site_monitoring.entity import StageStatus
from site_monitoring.services.forecast import ForecastService

STAGE_START = date(2026, 10, 5)
PLANNED_DAYS = 60


def test_full_pace_gives_no_lag() -> None:
    # Arrange
    service = ForecastService()

    # Act
    forecast = service.build_forecast("W001", PLANNED_DAYS, STAGE_START, 30, 30)

    # Assert
    assert forecast.pace == 1.0
    assert forecast.lag_days == 0
    assert forecast.status is StageStatus.ON_SCHEDULE


def test_small_slowdown_gives_risk_status() -> None:
    # Arrange
    service = ForecastService()

    # Act
    forecast = service.build_forecast("W001", PLANNED_DAYS, STAGE_START, 30, 29)

    # Assert
    assert forecast.lag_days > 0
    assert forecast.status is StageStatus.RISK_OF_DELAY


def test_significant_slowdown_gives_delay_status() -> None:
    # Arrange
    service = ForecastService()

    # Act
    forecast = service.build_forecast("W001", PLANNED_DAYS, STAGE_START, 30, 20)

    # Assert
    assert forecast.status is StageStatus.DELAYED
    assert forecast.forecast_finish == date(2027, 1, 2)


def test_zero_pace_has_no_finish_date() -> None:
    # Arrange
    service = ForecastService()

    # Act
    forecast = service.build_forecast("W001", PLANNED_DAYS, STAGE_START, 30, 0)

    # Assert
    assert forecast.forecast_finish is None
    assert forecast.lag_days == PLANNED_DAYS
    assert forecast.status is StageStatus.DELAYED


def test_single_day_stage_does_not_break_pace() -> None:
    # Arrange
    service = ForecastService()

    # Act
    forecast = service.build_forecast("W001", 1, STAGE_START, 1, 1)

    # Assert
    assert forecast.pace == 1.0
    assert forecast.forecast_finish == STAGE_START
    assert forecast.status is StageStatus.ON_SCHEDULE
