"""Формирует файл календарного плана Calendar_plan_new.xlsx из config/calendar_plan_new.json.

Книга собирается напрямую в формате OOXML: сторонние пакеты работы с Excel
в стек проекта не входят.
"""

import json
import zipfile
from datetime import date
from pathlib import Path

PLAN_PATH = Path("config/calendar_plan_new.json")
OUTPUT_PATH = Path("Calendar_plan_new.xlsx")
SHEET_TITLE = "Календарный план"
HEADERS = ("Вид работ", "Дата начала", "Дата окончания")
COLUMN_WIDTHS = (120, 16, 18)
DATE_FORMAT = "%d.%m.%Y"
XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DOCUMENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
WORKSHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"


def escape(value: str) -> str:
    """Экранирует символы, недопустимые в теле XML."""
    safe = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return safe


def format_date(value: str) -> str:
    """Переводит дату из ISO-формата в привычный для плана вид."""
    parsed = date.fromisoformat(value)
    formatted = parsed.strftime(DATE_FORMAT)
    return formatted


def build_row(index: int, values: tuple[str, ...]) -> str:
    """Собирает строку листа из текстовых ячеек."""
    cells = []
    for position, value in enumerate(values):
        column = chr(ord("A") + position)
        cell = f'<c r="{column}{index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        cells.append(cell)
    row = f'<row r="{index}">{"".join(cells)}</row>'
    return row


def build_sheet(rows: list[tuple[str, ...]]) -> str:
    """Собирает XML листа с шапкой и строками плана."""
    columns = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(COLUMN_WIDTHS)
    )
    body = [build_row(1, HEADERS)]
    for number, values in enumerate(rows, start=2):
        body.append(build_row(number, values))
    sheet = (
        f'{XML_HEADER}<worksheet xmlns="{MAIN_NS}"><cols>{columns}</cols>'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    return sheet


def build_workbook() -> str:
    """Собирает XML книги с единственным листом плана."""
    workbook = (
        f'{XML_HEADER}<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
        f'<sheets><sheet name="{escape(SHEET_TITLE)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    return workbook


def build_package_parts(sheet_xml: str) -> dict[str, str]:
    """Собирает все части пакета xlsx в виде словаря «путь → содержимое»."""
    content_types = (
        f'{XML_HEADER}<Types xmlns="{CONTENT_TYPES_NS}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{DOCUMENT_TYPE}"/>'
        f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{WORKSHEET_TYPE}"/></Types>'
    )
    root_rels = (
        f'{XML_HEADER}<Relationships xmlns="{PACKAGE_REL_NS}">'
        f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    book_rels = (
        f'{XML_HEADER}<Relationships xmlns="{PACKAGE_REL_NS}">'
        f'<Relationship Id="rId1" Type="{REL_NS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    parts = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "xl/workbook.xml": build_workbook(),
        "xl/_rels/workbook.xml.rels": book_rels,
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    return parts


def read_rows() -> list[tuple[str, ...]]:
    """Читает этапы плана и готовит строки для листа."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    rows = [
        (stage["full_name"], format_date(stage["start"]), format_date(stage["finish"]))
        for stage in plan["stages"]
    ]
    return rows


def main() -> None:
    """Записывает книгу календарного плана на диск."""
    rows = read_rows()
    sheet_xml = build_sheet(rows)
    parts = build_package_parts(sheet_xml)
    with zipfile.ZipFile(OUTPUT_PATH, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content)
    print(f"Записан {OUTPUT_PATH}: строк {len(rows)}")


if __name__ == "__main__":
    main()
