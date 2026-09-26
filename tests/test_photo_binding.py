"""Тесты привязки снимков к этапам календарного плана."""

from datetime import date, datetime
from pathlib import Path

import pytest

from site_monitoring.adapters.uploaded_plan_reader import UploadedStage
from site_monitoring.services import photo_binding
from site_monitoring.services.photo_binding import BINDING_BY_ORDER, BINDING_BY_TIME, bind_photos

STAGES = (
    UploadedStage("W01", "Разработка грунта", date(2026, 6, 1), date(2026, 6, 5)),
    UploadedStage("W02", "Монтаж фасада", date(2026, 6, 6), date(2026, 6, 10)),
)


def _paths(count: int) -> tuple[Path, ...]:
    """Пути снимков, существование которых для привязки не важно."""
    return tuple(Path(f"кадр-{index}.jpg") for index in range(count))


@pytest.fixture
def times(monkeypatch):
    """Подменяет чтение времени съёмки на заданный список."""

    def _apply(values: list[tuple[datetime, bool]]):
        answers = dict(zip(_paths(len(values)), values))
        monkeypatch.setattr(photo_binding, "read_capture_time", lambda path: answers[path])

    return _apply


def test_снимки_ложатся_в_свои_периоды_по_времени(times) -> None:
    # Arrange
    times([
        (datetime(2026, 6, 2, 9, 0), True),
        (datetime(2026, 6, 8, 10, 0), True),
    ])

    # Act
    result = bind_photos(STAGES, _paths(2))

    # Assert
    assert result.method == BINDING_BY_TIME
    assert len(result.stages[0].photos) == 1
    assert len(result.stages[1].photos) == 1


def test_без_метаданных_снимки_делятся_по_порядку(times) -> None:
    # Arrange
    times([
        (datetime(2026, 6, 2, 9, 0), False),
        (datetime(2026, 6, 2, 9, 20), False),
        (datetime(2026, 6, 2, 9, 40), False),
    ])

    # Act
    result = bind_photos(STAGES, _paths(3))

    # Assert
    assert result.method == BINDING_BY_ORDER
    assert len(result.stages[0].photos) == 2
    assert len(result.stages[1].photos) == 1


def test_снимок_вне_периодов_плана_роняет_привязку_по_времени(times) -> None:
    # Arrange
    times([
        (datetime(2026, 6, 2, 9, 0), True),
        (datetime(2027, 1, 1, 9, 0), True),
    ])

    # Act
    result = bind_photos(STAGES, _paths(2))

    # Assert
    assert result.method == BINDING_BY_ORDER


def test_снимки_этапа_идут_по_возрастанию_времени(times) -> None:
    # Arrange
    times([
        (datetime(2026, 6, 3, 11, 0), True),
        (datetime(2026, 6, 2, 9, 0), True),
    ])

    # Act
    result = bind_photos(STAGES[:1], _paths(2))

    # Assert
    captured = [photo.captured_at.hour for photo in result.stages[0].photos]
    assert captured == [9, 11]
