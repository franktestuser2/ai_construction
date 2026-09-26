"""Сборка зависимостей домена контроля строительных площадок."""

import logging
from dataclasses import dataclass

from config import Settings

from .adapters.barrier_classifier import BarrierClassifier
from .adapters.detection_arbiter import DetectionArbiter
from .adapters.facade_detector import BuildingDetector, FacadeCellDetector
from .adapters.motion_observer import MotionObserver
from .adapters.equipment_detector import EquipmentDetector
from .adapters.calendar_plan_reader import CalendarPlanReader
from .adapters.camera_markup_reader import CameraMarkupReader
from .adapters.equipment_rules_reader import EquipmentRulesReader
from .adapters.excel_plan_reader import ExcelPlanReader
from .adapters.vlm_client import VlmClient
from .adapters.vlm_transport import VlmTransport
from .entity import VlmProvider, Work, WorkEquipmentRules
from .facade import SiteMonitoringFacade
from .mappers import (
    map_calendar_plan_to_entries,
    map_calendar_plan_to_works,
    map_plan_rows_to_entries,
    map_plan_rows_to_works,
    map_rules_payload_to_work_rules,
)
from .services.equipment_recognition import EquipmentRecognitionService
from .services.facade_readiness import FacadeReadinessService
from .services.forecast import ForecastService
from .services.plan_binding import PlanBindingService
from .services.rule_engine import RuleEngineService
from .services.shift_timeline import ShiftTimelineService

logger = logging.getLogger(__name__)

PLAN_SHEET_NAME = "07_План_график"


@dataclass(frozen=True)
class SiteMonitoringDependencies:
    """Готовые зависимости домена, собранные из настроек."""

    facade: SiteMonitoringFacade
    rules_by_work: dict[str, WorkEquipmentRules]
    works_by_id: dict[str, Work]


def build_dependencies(settings: Settings) -> SiteMonitoringDependencies:
    """Создаёт адаптеры, сервисы и фасад домена."""
    plan_reader = ExcelPlanReader(settings.workbook_path)
    rules_reader = EquipmentRulesReader(settings.equipment_rules_path)

    plan_rows = plan_reader.read_sheet(PLAN_SHEET_NAME)
    plan_entries = _load_plan_entries(settings, plan_rows)
    rules_by_work = map_rules_payload_to_work_rules(rules_reader.read_rules())

    works_by_id = _load_works(settings, plan_rows)
    facade = _build_domain_facade(settings, plan_entries, rules_by_work, works_by_id)
    logger.info("Зависимости собраны: работ в плане %d", len(rules_by_work))
    dependencies = SiteMonitoringDependencies(
        facade=facade,
        rules_by_work=rules_by_work,
        works_by_id=works_by_id,
    )
    return dependencies


def _build_domain_facade(
    settings: Settings,
    plan_entries,
    rules_by_work: dict[str, WorkEquipmentRules],
    works_by_id: dict[str, Work],
) -> SiteMonitoringFacade:
    """Собирает фасад домена со всеми сервисами и распознаванием."""
    facade = SiteMonitoringFacade(
        plan_binding=PlanBindingService(plan_entries),
        rule_engine=RuleEngineService(),
        forecast=ForecastService(),
        rules_by_work=rules_by_work,
        works_by_id=works_by_id,
        camera_markup=CameraMarkupReader(settings.camera_markup_path).read_boxes(),
        recognition=_build_recognition(settings),
        facade_readiness=build_facade_readiness(settings),
        motion_observer=build_motion_observer(settings),
        parallel_requests=settings.parallel_requests,
        shift_timeline=ShiftTimelineService(
            slot_minutes=settings.slot_minutes,
            slots_per_shift=settings.slots_per_shift,
            shift_start_hour=settings.shift_start_hour,
        ),
    )
    return facade


def _load_works(settings: Settings, plan_rows: list[list[str]]) -> dict[str, Work]:
    """Собирает названия видов работ: из календарного плана и из книги Excel.

    Коды в книге и в плане проекта разные (W001 против W01), поэтому одной книги мало:
    без названия из плана в промпт модели уходит код вида работ вместо его имени.
    """
    works = {work.work_id: work for work in map_plan_rows_to_works(plan_rows)}
    if settings.use_calendar_plan and settings.calendar_plan_path.exists():
        plan_reader = CalendarPlanReader(settings.calendar_plan_path)
        works |= {work.work_id: work for work in map_calendar_plan_to_works(plan_reader.read_plan())}
    return works


def _load_plan_entries(settings: Settings, plan_rows: list[list[str]]):
    """Выбирает план: календарный план проекта либо полный из книги Excel."""
    if settings.use_calendar_plan and settings.calendar_plan_path.exists():
        plan_reader = CalendarPlanReader(settings.calendar_plan_path)
        plan_entries = map_calendar_plan_to_entries(plan_reader.read_plan())
        return plan_entries
    full_entries = map_plan_rows_to_entries(plan_rows, settings.project_id)
    return full_entries


def _build_recognition(settings: Settings) -> EquipmentRecognitionService | None:
    """Собирает сервис распознавания, если заданы доступы к моделям."""
    transport = build_vlm_transport(settings)
    if transport is None:
        logger.info("Доступ к VLM не задан, распознавание снимков отключено")
        return None
    detector = EquipmentDetector(settings.detector_weights_path, settings.detector_confidence_threshold)
    vlm_client = VlmClient(transport)
    arbiter = DetectionArbiter(transport)
    recognition = EquipmentRecognitionService(detector, vlm_client, arbiter)
    return recognition


def build_vlm_transport(settings: Settings) -> VlmTransport | None:
    """Собирает транспорт к модели выбранного провайдера, если задан его ключ."""
    if settings.vlm_provider is VlmProvider.YANDEX:
        yandex = _build_yandex_transport(settings)
        return yandex
    if not settings.deepseek_api_key:
        return None
    deepseek = VlmTransport(
        provider=VlmProvider.DEEPSEEK,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        max_tokens=settings.vlm_max_tokens,
    )
    return deepseek


def _build_yandex_transport(settings: Settings) -> VlmTransport | None:
    """Собирает транспорт к прежней модели Yandex Cloud AI Studio."""
    if not settings.yc_api_key or not settings.yc_folder_id:
        return None
    transport = VlmTransport(
        provider=VlmProvider.YANDEX,
        base_url=settings.yc_vlm_base_url,
        api_key=settings.yc_api_key,
        model=settings.yc_vlm_model,
        max_tokens=settings.vlm_max_tokens,
        folder_id=settings.yc_folder_id,
    )
    return transport


def build_facade_readiness(settings: Settings) -> FacadeReadinessService | None:
    """Собирает разбор фасада, если перенесённые веса лежат на месте."""
    weights = (
        settings.building_weights_path,
        settings.facade_cell_weights_path,
        settings.barrier_weights_path,
    )
    if not all(path.exists() for path in weights):
        logger.info("Веса фасадных моделей не найдены, разбор фасада отключён")
        return None
    building_detector = BuildingDetector(settings.building_weights_path, settings.building_threshold)
    cell_detector = FacadeCellDetector(settings.facade_cell_weights_path, settings.facade_cell_threshold)
    barrier_classifier = BarrierClassifier(settings.barrier_weights_path, settings.barrier_threshold)
    service = FacadeReadinessService(
        building_detector=building_detector,
        cell_detector=cell_detector,
        barrier_classifier=barrier_classifier,
    )
    return service


def build_motion_observer(settings: Settings) -> MotionObserver | None:
    """Собирает сравнение пар кадров, если доступ к модели задан."""
    transport = build_vlm_transport(settings)
    if transport is None:
        return None
    observer = MotionObserver(transport=transport, slot_minutes=settings.slot_minutes)
    return observer
