"""Тесты расписания съёмки: сетка периодов и положение ролика во времени."""

from datetime import datetime

from camera_watch.services.capture_planner import (
    capture_position,
    is_due,
    next_capture_at,
    position_seconds,
    slot_start,
)

PERIOD_MINUTES = 20


def test_период_начинается_на_границе_сетки() -> None:
    # Arrange
    moment = datetime(2026, 9, 27, 9, 37, 42)

    # Act
    start = slot_start(moment, PERIOD_MINUTES)

    # Assert
    assert start == datetime(2026, 9, 27, 9, 20)


def test_без_единой_съёмки_снимать_пора() -> None:
    # Arrange
    moment = datetime(2026, 9, 27, 9, 5)

    # Act
    due = is_due(None, moment, PERIOD_MINUTES)

    # Assert
    assert due is True


def test_в_том_же_периоде_второй_раз_не_снимаем() -> None:
    # Arrange
    captured = datetime(2026, 9, 27, 9, 21)
    moment = datetime(2026, 9, 27, 9, 39)

    # Act
    due = is_due(captured, moment, PERIOD_MINUTES)

    # Assert
    assert due is False


def test_в_новом_периоде_снимаем_снова() -> None:
    # Arrange
    captured = datetime(2026, 9, 27, 9, 21)
    moment = datetime(2026, 9, 27, 9, 41)

    # Act
    due = is_due(captured, moment, PERIOD_MINUTES)

    # Assert
    assert due is True


def test_следующая_съёмка_на_границе_следующего_периода() -> None:
    # Arrange
    captured = datetime(2026, 9, 27, 9, 21)
    moment = datetime(2026, 9, 27, 9, 30)

    # Act
    planned = next_capture_at(captured, moment, PERIOD_MINUTES)

    # Assert
    assert planned == datetime(2026, 9, 27, 9, 40)


def test_положение_ролика_повторяется_по_кругу() -> None:
    # Arrange
    duration = 60.0
    moment = datetime(2026, 9, 27, 9, 30, 25)
    later = datetime(2026, 9, 27, 9, 31, 25)

    # Act
    first = position_seconds(moment, duration)
    second = position_seconds(later, duration)

    # Assert
    assert abs(first - second) < 0.001


def test_пустой_ролик_даёт_нулевое_положение() -> None:
    # Arrange
    moment = datetime(2026, 9, 27, 9, 30)

    # Act
    position = position_seconds(moment, 0.0)

    # Assert
    assert position == 0.0


def test_соседние_съёмки_берут_разные_секунды_ролика() -> None:
    # Arrange
    duration = 60.0
    first = datetime(2026, 9, 27, 9, 20)
    second = datetime(2026, 9, 27, 9, 40)

    # Act
    early = capture_position(first, duration, PERIOD_MINUTES)
    late = capture_position(second, duration, PERIOD_MINUTES)

    # Assert
    assert early != late
