"""Преобразование сырых строк Excel и ответов внешних систем в DTO домена.

Единственное место, где живут сырые списки и словари: дальше по потоку
идут только объекты из entity.
"""

import logging
from datetime import date, timedelta

from .entity import (
    EquipmentSource,
    EquipmentStatus,
    FrameObservation,
    ObservedEquipment,
    PlanEntry,
    PositionAlternative,
    PositionKind,
    Work,
    WorkEquipmentRules,
    WorkPosition,
)

logger = logging.getLogger(__name__)

EXCEL_EPOCH = date(1899, 12, 30)
PLAN_HEADER_MARKER = "work_id"
PLAN_PROJECT_COLUMN = 0
PLAN_NAME_COLUMN = 1
PLAN_WORK_COLUMN = 2
PLAN_DATE_COLUMN = 3
MACHINE_WORK_COLUMN = 0
MACHINE_TYPE_COLUMN = 1
MIN_PLAN_COLUMNS = 4
MIN_MACHINE_COLUMNS = 2
RULES_WORKS_KEY = "works"
RULES_WORK_ID_KEY = "work_id"
RULES_POSITIONS_KEY = "positions"
RULES_FACADE_CHECK_KEY = "facade_check"
RULES_POSITION_KEY = "position"
RULES_KIND_KEY = "kind"
RULES_ALTERNATIVES_KEY = "alternatives"
RULES_LEAD_KEY = "lead"
RULES_MACHINE_TYPE_KEY = "machine_type"
RULES_SOURCE_KEY = "source"
RULES_MIN_COUNT_KEY = "min_count"
PLAN_STAGES_KEY = "stages"
PLAN_START_KEY = "start"
PLAN_FINISH_KEY = "finish"
PLAN_FULL_NAME_KEY = "full_name"
FRAME_BOXES_KEY = "boxes"
FRAME_REJECTED_BOXES_KEY = "rejected_boxes"
RULES_DETECTOR_CLASSES_KEY = "detector_classes"
RULES_QUESTION_KEY = "vlm_question"
FRAME_ID_KEY = "frame_id"
FRAME_DATE_KEY = "observed_on"
FRAME_EQUIPMENT_KEY = "equipment"
FRAME_LIMITED_VIEW_KEY = "limited_view"
FRAME_LIMITED_REASON_KEY = "limited_reason"
FRAME_STATUS_KEY = "status"
FRAME_COUNT_KEY = "count"
FRAME_CONFIDENCE_KEY = "confidence"
FRAME_JUSTIFICATION_KEY = "justification"
DEFAULT_EQUIPMENT_COUNT = 1
DEMO_PROJECT_KEY = "project_id"
DEMO_DAYS_KEY = "days"
DEMO_WORK_KEY = "work_id"
DEMO_DATE_KEY = "date"


def _excel_serial_to_date(serial_value: str) -> date | None:
    """Переводит серийный номер даты Excel в календарную дату."""
    try:
        days = int(float(serial_value))
    except ValueError:
        logger.warning("Дата плана не разобрана: %s", serial_value)
        return None
    converted = EXCEL_EPOCH + timedelta(days=days)
    return converted


def _find_header_index(rows: list[list[str]]) -> int:
    """Находит строку с названиями колонок, пропуская пояснения сверху листа."""
    for index, row in enumerate(rows):
        cleaned = [cell.strip() for cell in row]
        if PLAN_HEADER_MARKER in cleaned:
            return index
    return -1


def _data_rows(rows: list[list[str]], min_columns: int) -> list[list[str]]:
    """Отсекает заголовок и строки, в которых не хватает колонок."""
    header_index = _find_header_index(rows)
    if header_index < 0:
        return []
    body = rows[header_index + 1 :]
    filtered = [row for row in body if len(row) >= min_columns]
    return filtered


def map_plan_rows_to_entries(rows: list[list[str]], project_id: str) -> tuple[PlanEntry, ...]:
    """Собирает строки листа плана-графика в записи календарного плана."""
    entries = []
    for row in _data_rows(rows, MIN_PLAN_COLUMNS):
        if row[PLAN_PROJECT_COLUMN].strip() != project_id:
            continue
        plan_date = _excel_serial_to_date(row[PLAN_DATE_COLUMN])
        if plan_date is None:
            continue
        entry = PlanEntry(
            project_id=row[PLAN_PROJECT_COLUMN].strip(),
            work_id=row[PLAN_WORK_COLUMN].strip(),
            plan_date=plan_date,
        )
        entries.append(entry)
    logger.info("План проекта %s: записей %d", project_id, len(entries))
    result = tuple(entries)
    return result


def map_plan_rows_to_works(rows: list[list[str]]) -> tuple[Work, ...]:
    """Извлекает справочник видов работ из листа плана-графика."""
    names: dict[str, str] = {}
    for row in _data_rows(rows, MIN_PLAN_COLUMNS):
        work_id = row[PLAN_WORK_COLUMN].strip()
        if work_id and work_id not in names:
            names[work_id] = row[PLAN_NAME_COLUMN].strip()
    works = tuple(Work(work_id=key, full_name=value) for key, value in sorted(names.items()))
    return works


def map_machine_rows_to_types(rows: list[list[str]]) -> dict[str, tuple[str, ...]]:
    """Собирает соответствие «вид работ → типы машин» с листа справочника."""
    grouped: dict[str, list[str]] = {}
    for row in _data_rows(rows, MIN_MACHINE_COLUMNS):
        work_id = row[MACHINE_WORK_COLUMN].strip()
        machine_type = row[MACHINE_TYPE_COLUMN].strip()
        if not work_id or not machine_type:
            continue
        grouped.setdefault(work_id, []).append(machine_type)
    mapping = {key: tuple(value) for key, value in grouped.items()}
    return mapping


def _map_alternative(payload: dict[str, object]) -> PositionAlternative:
    """Превращает один способ закрыть позицию в DTO."""
    detector_classes = payload.get(RULES_DETECTOR_CLASSES_KEY) or []
    alternative = PositionAlternative(
        machine_type=str(payload[RULES_MACHINE_TYPE_KEY]),
        source=EquipmentSource(str(payload[RULES_SOURCE_KEY])),
        detector_classes=tuple(str(item) for item in detector_classes),  # type: ignore[union-attr]
        vlm_question=payload.get(RULES_QUESTION_KEY),  # type: ignore[arg-type]
    )
    return alternative


def _map_position(payload: dict[str, object]) -> WorkPosition:
    """Превращает описание одной позиции правил в DTO."""
    alternatives = tuple(_map_alternative(item) for item in payload[RULES_ALTERNATIVES_KEY])  # type: ignore[union-attr]
    position = WorkPosition(
        position=str(payload[RULES_POSITION_KEY]),
        kind=PositionKind(str(payload[RULES_KIND_KEY])),
        min_count=int(payload[RULES_MIN_COUNT_KEY]),  # type: ignore[arg-type]
        alternatives=alternatives,
        is_lead=bool(payload.get(RULES_LEAD_KEY, False)),
    )
    return position


def map_rules_payload_to_work_rules(payload: dict[str, object]) -> dict[str, WorkEquipmentRules]:
    """Собирает правила техники по видам работ из содержимого файла конфигурации."""
    works = payload.get(RULES_WORKS_KEY) or []
    rules_by_work = {}
    for work_payload in works:  # type: ignore[union-attr]
        work_id = str(work_payload[RULES_WORK_ID_KEY])
        positions = tuple(_map_position(item) for item in work_payload[RULES_POSITIONS_KEY])
        facade_check = bool(work_payload.get(RULES_FACADE_CHECK_KEY, False))
        rules_by_work[work_id] = WorkEquipmentRules(
            work_id=work_id,
            positions=positions,
            facade_check=facade_check,
        )
    logger.info("Правила техники разобраны для %d работ", len(rules_by_work))
    return rules_by_work


def _map_boxes(payload: object) -> tuple[tuple[float, float, float, float], ...]:
    """Превращает список рамок из кеша в набор координат в долях снимка."""
    if not isinstance(payload, list):
        return ()
    boxes = tuple(tuple(float(value) for value in box) for box in payload)
    return boxes  # type: ignore[return-value]


def _map_observed_equipment(payload: dict[str, object]) -> ObservedEquipment:
    """Превращает описание одной единицы техники со снимка в DTO."""
    confidence = payload.get(FRAME_CONFIDENCE_KEY)
    equipment = ObservedEquipment(
        machine_type=str(payload[RULES_MACHINE_TYPE_KEY]),
        source=EquipmentSource(str(payload[RULES_SOURCE_KEY])),
        status=EquipmentStatus(str(payload[FRAME_STATUS_KEY])),
        count=int(payload.get(FRAME_COUNT_KEY, DEFAULT_EQUIPMENT_COUNT)),  # type: ignore[arg-type]
        confidence=float(confidence) if confidence is not None else None,  # type: ignore[arg-type]
        justification=payload.get(FRAME_JUSTIFICATION_KEY),  # type: ignore[arg-type]
        boxes=_map_boxes(payload.get(FRAME_BOXES_KEY)),
        rejected_boxes=_map_boxes(payload.get(FRAME_REJECTED_BOXES_KEY)),
    )
    return equipment


def map_frames_payload_to_observations(payload: list[dict[str, object]]) -> tuple[FrameObservation, ...]:
    """Собирает результаты разбора снимков в наблюдения домена."""
    observations = []
    for frame_payload in payload:
        observed_on = date.fromisoformat(str(frame_payload[FRAME_DATE_KEY]))
        equipment_payload = frame_payload.get(FRAME_EQUIPMENT_KEY) or []
        equipment = tuple(_map_observed_equipment(item) for item in equipment_payload)  # type: ignore[union-attr]
        observation = FrameObservation(
            frame_id=str(frame_payload[FRAME_ID_KEY]),
            observed_on=observed_on,
            equipment=equipment,
            limited_view=bool(frame_payload.get(FRAME_LIMITED_VIEW_KEY, False)),
            limited_reason=str(frame_payload.get(FRAME_LIMITED_REASON_KEY, "")),
        )
        observations.append(observation)
    result = tuple(observations)
    return result



def map_calendar_plan_to_works(payload: dict[str, object]) -> tuple[Work, ...]:
    """Собирает названия видов работ из календарного плана проекта.

    Названия нужны промптам моделей: без них в вопрос уходит код вида работ,
    и модель отвечает про него же вместо техники.
    """
    stages = payload.get(PLAN_STAGES_KEY) or []
    works = tuple(
        Work(work_id=str(stage[DEMO_WORK_KEY]), full_name=str(stage[PLAN_FULL_NAME_KEY]))
        for stage in stages  # type: ignore[union-attr]
    )
    return works


def map_calendar_plan_to_entries(payload: dict[str, object]) -> tuple[PlanEntry, ...]:
    """Разворачивает этапы календарного плана в записи по календарным дням."""
    project_id = str(payload.get(DEMO_PROJECT_KEY, ""))
    stages = payload.get(PLAN_STAGES_KEY) or []
    entries = []
    for stage_payload in stages:  # type: ignore[union-attr]
        work_id = str(stage_payload[DEMO_WORK_KEY])
        start = date.fromisoformat(str(stage_payload[PLAN_START_KEY]))
        finish = date.fromisoformat(str(stage_payload[PLAN_FINISH_KEY]))
        current = start
        while current <= finish:
            entries.append(PlanEntry(project_id=project_id, work_id=work_id, plan_date=current))
            current += timedelta(days=1)
    logger.info("Календарный план проекта %s: дней %d", project_id, len(entries))
    result = tuple(entries)
    return result
