"""Тесты чтения булевых значений из ответа модели."""

import pytest

from site_monitoring.adapters.model_answer_reader import read_bool, read_status
from site_monitoring.entity import EquipmentStatus


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("True", True),
        (" да ", True),
        ("нет", False),
        ("", False),
    ],
)
def test_строковая_запись_булева_читается_верно(value: object, expected: bool) -> None:
    # Arrange & Act
    result = read_bool(value)

    # Assert
    assert result is expected


def test_отсутствующее_значение_даёт_умолчание() -> None:
    # Arrange & Act
    result = read_bool(None, default=True)

    # Assert
    assert result is True


def test_непонятная_строка_не_становится_истиной_сама_собой() -> None:
    # Arrange & Act
    result = read_bool("затрудняюсь ответить")

    # Assert
    assert result is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("работает", EquipmentStatus.WORKING),
        ("Простаивает", EquipmentStatus.IDLE),
        ("работает — самосвал под погрузкой, ковш подан к кузову", EquipmentStatus.WORKING),
        ("на снимке техника простаивает у бытовки", EquipmentStatus.IDLE),
    ],
)
def test_статус_с_пояснением_приводится_к_перечислению(value: str, expected) -> None:
    # Arrange & Act
    result = read_status(value)

    # Assert
    assert result is expected


def test_неизвестный_статус_даёт_умолчание() -> None:
    # Arrange & Act
    result = read_status("затрудняюсь сказать")

    # Assert
    assert result is EquipmentStatus.NOT_APPLICABLE
