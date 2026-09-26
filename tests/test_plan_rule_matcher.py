"""Тесты сопоставления этапов загруженного плана с правилами по технике."""

from site_monitoring.services.plan_rule_matcher import match_stages, match_work_id

KNOWN = {
    "W01": "Подготовка территории → Погрузка строительного мусора",
    "W03": "Земляные работы → Разработка грунта с креплением котлована",
    "W07": "Монтаж фасадной системы",
}


def test_этап_узнаётся_по_значимым_словам() -> None:
    # Arrange & Act
    work_id = match_work_id("Разработка грунта в котловане", KNOWN)

    # Assert
    assert work_id == "W03"


def test_служебные_слова_не_склеивают_разные_этапы() -> None:
    # Arrange & Act
    work_id = match_work_id("Выполнение строительно-монтажных работ", KNOWN)

    # Assert
    assert work_id is None


def test_незнакомый_этап_остаётся_без_правил() -> None:
    # Arrange & Act
    work_id = match_work_id("Благоустройство и озеленение", KNOWN)

    # Assert
    assert work_id is None


def test_одни_правила_не_достаются_двум_этапам() -> None:
    # Arrange
    titles = ("Разработка грунта с креплением котлована", "Разработка грунта, второй участок")

    # Act
    matched = match_stages(titles, KNOWN)

    # Assert
    assert matched[0] == "W03"
    assert matched[1] is None


def test_фасад_узнаётся_по_ключевому_слову() -> None:
    # Arrange & Act
    matched = match_stages(("Монтаж навесной фасадной системы",), KNOWN)

    # Assert
    assert matched == ("W07",)
