"""Тесты чтения книги Excel с календарным планом демо-проекта."""

from datetime import date

from site_monitoring.adapters.excel_plan_reader import ExcelPlanReader
from site_monitoring.mappers import (
    map_machine_rows_to_types,
    map_plan_rows_to_entries,
    map_plan_rows_to_works,
)

PLAN_SHEET = "07_План_график"
MACHINE_SHEET = "04_Работы_машины"
PROJECT_ID = "EDU-DEMO-001"
EXPECTED_PLAN_DAYS = 294
EXPECTED_WORKS = 8
FIRST_PLAN_DATE = date(2026, 10, 5)
LAST_PLAN_DATE = date(2027, 7, 25)


def test_plan_sheet_is_parsed_into_entries(workbook_path) -> None:
    # Arrange
    reader = ExcelPlanReader(workbook_path)

    # Act
    rows = reader.read_sheet(PLAN_SHEET)
    entries = map_plan_rows_to_entries(rows, PROJECT_ID)

    # Assert
    assert len(entries) == EXPECTED_PLAN_DAYS
    assert entries[0].plan_date == FIRST_PLAN_DATE
    assert entries[-1].plan_date == LAST_PLAN_DATE


def test_every_plan_date_has_single_work(workbook_path) -> None:
    # Arrange
    reader = ExcelPlanReader(workbook_path)

    # Act
    entries = map_plan_rows_to_entries(reader.read_sheet(PLAN_SHEET), PROJECT_ID)

    # Assert
    dates = [entry.plan_date for entry in entries]
    assert len(dates) == len(set(dates))


def test_works_reference_is_extracted(workbook_path) -> None:
    # Arrange
    reader = ExcelPlanReader(workbook_path)

    # Act
    works = map_plan_rows_to_works(reader.read_sheet(PLAN_SHEET))

    # Assert
    assert len(works) == EXPECTED_WORKS
    assert works[0].work_id == "W001"
    assert works[0].full_name != ""


def test_machine_reference_is_grouped_by_work(workbook_path) -> None:
    # Arrange
    reader = ExcelPlanReader(workbook_path)

    # Act
    machines = map_machine_rows_to_types(reader.read_sheet(MACHINE_SHEET))

    # Assert
    assert len(machines) == EXPECTED_WORKS
    assert machines["W008"] == ("Асфальтоукладчик", "Дорожный каток", "Самосвал")


def test_unknown_sheet_raises_lookup_error(workbook_path) -> None:
    # Arrange
    reader = ExcelPlanReader(workbook_path)

    # Act / Assert
    try:
        reader.read_sheet("нет такого листа")
    except LookupError:
        return
    raise AssertionError("Ожидалась ошибка LookupError для несуществующего листа")
