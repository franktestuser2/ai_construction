"""Чтение календарного плана, загруженного пользователем.

По требованиям заказчика план подаётся таблицей: вид работ и даты производства,
без сведений о технике. Принимаются две формы записи — книга Excel и CSV;
внутри обе сводятся к одному перечню этапов.

Колонки ищутся по заголовку, а не по позиции: в выгрузках заказчика порядок
столбцов не гарантирован. Даты принимаются и в российской записи, и в ISO.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path

from .excel_plan_reader import ExcelPlanReader

logger = logging.getLogger(__name__)

EXCEL_SUFFIXES = (".xlsx", ".xlsm")
CSV_SUFFIXES = (".csv", ".txt")
CSV_DELIMITERS = ";,\t"
NAME_HEADERS = ("вид работ", "работа", "этап", "наименование")
START_HEADERS = ("дата начала", "начало", "старт")
FINISH_HEADERS = ("дата окончания", "окончание", "финиш", "конец")
DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y")
WORK_ID_TEMPLATE = "W{number:02d}"
MIN_COLUMNS = 3
UNSUPPORTED_MESSAGE = "Поддерживаются только книги Excel и файлы CSV"
NO_ROWS_MESSAGE = "В файле плана не нашлось ни одного этапа с датами"
NO_HEADER_MESSAGE = "В файле плана не нашлось заголовка с видом работ и датами"


@dataclass(frozen=True)
class UploadedStage:
    """Один этап календарного плана, прочитанный из загруженного файла."""

    work_id: str
    full_name: str
    start: date
    finish: date


def _read_date(value: str) -> date | None:
    """Разбирает дату в любой из принятых записей."""
    text = value.strip()
    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format).date()
            return parsed
        except ValueError:
            continue
    return None


def _read_csv_rows(path: Path) -> list[list[str]]:
    """Читает CSV, определяя разделитель по содержимому файла."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=CSV_DELIMITERS)
    except csv.Error:
        dialect = csv.excel
    rows = [list(row) for row in csv.reader(StringIO(text), dialect)]
    return rows


def _read_rows(path: Path) -> list[list[str]]:
    """Достаёт строки таблицы из книги Excel либо из CSV."""
    suffix = path.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        reader = ExcelPlanReader(path)
        return reader.read_sheet("")
    if suffix in CSV_SUFFIXES:
        return _read_csv_rows(path)
    raise ValueError(UNSUPPORTED_MESSAGE)


def _column_index(header: list[str], names: tuple[str, ...]) -> int | None:
    """Ищет колонку по началу её заголовка."""
    for index, cell in enumerate(header):
        title = cell.strip().lower()
        if any(title.startswith(name) for name in names):
            return index
    return None


def _find_header(rows: list[list[str]]) -> tuple[int, tuple[int, int, int]] | None:
    """Находит строку заголовка и номера нужных колонок."""
    for index, row in enumerate(rows):
        if len(row) < MIN_COLUMNS:
            continue
        name = _column_index(row, NAME_HEADERS)
        start = _column_index(row, START_HEADERS)
        finish = _column_index(row, FINISH_HEADERS)
        if name is not None and start is not None and finish is not None:
            return index, (name, start, finish)
    return None


class UploadedPlanReader:
    """Адаптер чтения календарного плана из файла пользователя."""

    def __init__(self, plan_path: Path) -> None:
        self._plan_path = plan_path

    def read_stages(self) -> tuple[UploadedStage, ...]:
        """Возвращает этапы плана в порядке их следования в файле."""
        rows = _read_rows(self._plan_path)
        found = _find_header(rows)
        if found is None:
            raise ValueError(NO_HEADER_MESSAGE)
        header_index, columns = found
        stages = self._collect_stages(rows[header_index + 1 :], columns)
        if not stages:
            raise ValueError(NO_ROWS_MESSAGE)
        logger.info("План пользователя прочитан: этапов %d", len(stages))
        return stages

    def _collect_stages(
        self,
        rows: list[list[str]],
        columns: tuple[int, int, int],
    ) -> tuple[UploadedStage, ...]:
        """Собирает строки таблицы в этапы, пропуская строки без дат."""
        name_column, start_column, finish_column = columns
        stages = []
        for row in rows:
            if len(row) <= finish_column:
                continue
            start = _read_date(row[start_column])
            finish = _read_date(row[finish_column])
            name = row[name_column].strip()
            if start is None or finish is None or not name:
                continue
            work_id = WORK_ID_TEMPLATE.format(number=len(stages) + 1)
            stages.append(UploadedStage(work_id=work_id, full_name=name, start=start, finish=finish))
        return tuple(stages)
