"""Чтение книги Excel с календарным планом и справочниками проекта.

Формат xlsx разбирается средствами стандартной библиотеки: книга — это zip
с XML внутри, сторонний пакет для такой задачи не нужен.
"""

import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELATION_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
SHARED_STRINGS_PATH = "xl/sharedStrings.xml"
WORKBOOK_PATH = "xl/workbook.xml"
WORKBOOK_RELS_PATH = "xl/_rels/workbook.xml.rels"
SHARED_STRING_TYPE = "s"
INLINE_STRING_TYPE = "inlineStr"
ALPHABET_SIZE = 26
LETTER_OFFSET = 64
COLUMN_LETTERS_PATTERN = re.compile(r"[A-Z]+")


def _column_index(cell_reference: str) -> int:
    """Переводит буквенную часть адреса ячейки в порядковый номер столбца."""
    letters_match = COLUMN_LETTERS_PATTERN.match(cell_reference)
    if letters_match is None:
        return 0
    position = 0
    for letter in letters_match.group(0):
        position = position * ALPHABET_SIZE + ord(letter) - LETTER_OFFSET
    index = position - 1
    return index


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Собирает общий словарь строк книги."""
    if SHARED_STRINGS_PATH not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read(SHARED_STRINGS_PATH))
    strings = []
    for item in root.findall(f"{SHEET_NS}si"):
        parts = [node.text or "" for node in item.iter(f"{SHEET_NS}t")]
        strings.append("".join(parts))
    return strings


def _read_sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    """Сопоставляет названия листов с путями их XML внутри книги."""
    relations_root = ElementTree.fromstring(archive.read(WORKBOOK_RELS_PATH))
    relations = {node.get("Id"): node.get("Target", "") for node in relations_root}
    workbook_root = ElementTree.fromstring(archive.read(WORKBOOK_PATH))
    sheets_node = workbook_root.find(f"{SHEET_NS}sheets")
    sheets = list(sheets_node) if sheets_node is not None else []
    targets = {}
    for sheet in sheets:
        relation_id = sheet.get(f"{RELATION_NS}id")
        target = relations.get(relation_id, "").lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        targets[sheet.get("name", "")] = target
    return targets


def _cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str | None:
    """Достаёт текстовое значение одной ячейки с учётом её типа."""
    cell_type = cell.get("t")
    if cell_type == INLINE_STRING_TYPE:
        parts = [node.text or "" for node in cell.iter(f"{SHEET_NS}t")]
        inline_text = "".join(parts)
        return inline_text
    value_node = cell.find(f"{SHEET_NS}v")
    if value_node is None or value_node.text is None:
        return None
    if cell_type == SHARED_STRING_TYPE:
        shared_index = int(value_node.text)
        return shared_strings[shared_index]
    return value_node.text


def _read_sheet_rows(archive: zipfile.ZipFile, target: str, shared_strings: list[str]) -> list[list[str]]:
    """Читает лист построчно, сохраняя позиции столбцов."""
    root = ElementTree.fromstring(archive.read(target))
    rows = []
    for row_node in root.iter(f"{SHEET_NS}row"):
        cells: dict[int, str] = {}
        for cell in row_node.findall(f"{SHEET_NS}c"):
            text = _cell_text(cell, shared_strings)
            if text is not None:
                cells[_column_index(cell.get("r", ""))] = text
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(index, "") for index in range(width)])
    return rows


class ExcelPlanReader:
    """Адаптер чтения книги Excel с планом работ.

    Путь к книге приходит из контейнера, переменные окружения адаптер не читает.
    """

    def __init__(self, workbook_path: Path) -> None:
        self._workbook_path = workbook_path

    def read_sheet(self, sheet_name: str) -> list[list[str]]:
        """Возвращает строки листа, найденного по вхождению имени."""
        with zipfile.ZipFile(self._workbook_path) as archive:
            shared_strings = _read_shared_strings(archive)
            targets = _read_sheet_targets(archive)
            target = self._resolve_target(targets, sheet_name)
            rows = _read_sheet_rows(archive, target, shared_strings)
        logger.info("Лист %s прочитан, строк: %d", sheet_name, len(rows))
        return rows

    def _resolve_target(self, targets: dict[str, str], sheet_name: str) -> str:
        """Ищет путь листа по точному имени, затем по вхождению подстроки."""
        exact = targets.get(sheet_name)
        if exact is not None:
            return exact
        for name, target in targets.items():
            if sheet_name in name:
                return target
        raise LookupError(f"Лист {sheet_name} не найден в книге {self._workbook_path.name}")
