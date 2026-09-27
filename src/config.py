"""Настройки сервиса контроля строительных площадок."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from site_monitoring.entity import VlmProvider

DEFAULT_WORKBOOK_PATH = Path("materials/ЛТЦ_строительная_история_8_работ.xlsx")
DEFAULT_RULES_PATH = Path("config/equipment_rules_v3.json")
DEFAULT_CALENDAR_PLAN_PATH = Path("config/calendar_plan_new.json")
DEFAULT_OBSERVATIONS_CACHE_PATH = Path("data/cache/demo_v2_observations.json")
DEFAULT_PHOTOS_PATH = Path("data/photos_v2")
DEFAULT_PROJECT_ID = "EDU-DEMO-001"
DEFAULT_VLM_PROVIDER = VlmProvider.DEEPSEEK
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_YC_VLM_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
DEFAULT_YC_VLM_MODEL = "qwen3.6-35b-a3b"
DEFAULT_VLM_MAX_TOKENS = 6000
# Модель даёт низкие абсолютные скоры: в прогонах авторов верные находки
# подписаны 0.05-0.10, поэтому порог отсчитывается от этого уровня.
DEFAULT_DETECTOR_THRESHOLD = 0.05
DEFAULT_IDLE_STREAK_DAYS = 3
# Смена демонстрации: снимок раз в двадцать минут, три часа работ в день.
DEFAULT_SLOT_MINUTES = 20
DEFAULT_SHIFT_HOURS = 3
DEFAULT_SHIFT_START_HOUR = 9
# Запросы к модели независимы друг от друга, поэтому идут пачкой.
DEFAULT_PARALLEL_REQUESTS = 8
DEFAULT_SLOT_PHOTOS_PATH = Path("data/photos_slots")
DEFAULT_CAMERA_MARKUP_PATH = Path("config/camera_markup.json")
MINUTES_IN_HOUR = 60
DEFAULT_DETECTOR_WEIGHTS_PATH = Path("models/rt_detr/weights/unpacked/checkpoint-12573")
DEFAULT_FACADE_CELL_WEIGHTS_PATH = Path("models/facade/weights/torchvision/facade_cells.pt")
DEFAULT_BUILDING_WEIGHTS_PATH = Path("models/facade/weights/torchvision/building.pt")
DEFAULT_BARRIER_WEIGHTS_PATH = Path("models/facade/weights/torchvision/barrier_resnet18.pt")
# Пороги взяты из рабочей конфигурации авторов фасадных моделей, не подобраны нами.
DEFAULT_FACADE_CELL_THRESHOLD = 0.35
DEFAULT_BUILDING_THRESHOLD = 0.85
DEFAULT_BARRIER_THRESHOLD = 0.94
# Контур наблюдения за камерами: описание камер, проверки охраны труда и место под архив.
DEFAULT_CAMERAS_PATH = Path("config/cameras.json")
DEFAULT_SAFETY_CHECKS_PATH = Path("config/safety_checks.json")
DEFAULT_CLIP_MODELS_PATH = Path("materials/external/video-monitoring-master/data/models/clip")
DEFAULT_CLIP_PHRASE_CACHE_PATH = Path("data/cache/clip_phrases")
DEFAULT_CAMERA_ARCHIVE_PATH = Path("data/cameras/archive")
DEFAULT_CAMERA_INBOX_PATH = Path("data/cameras/inbox")
DEFAULT_MAIN_SERVICE_URL = "http://127.0.0.1:8090"
DEFAULT_ONNX_THREADS = 2
# Часовой ход съёмки: планировщик просыпается чаще периода, чтобы не проспать границу слота.
DEFAULT_CAPTURE_TICK_SECONDS = 60


class Settings(BaseSettings):
    """Конфигурация сервиса, собираемая из переменных окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    workbook_path: Path = DEFAULT_WORKBOOK_PATH
    equipment_rules_path: Path = DEFAULT_RULES_PATH
    calendar_plan_path: Path = DEFAULT_CALENDAR_PLAN_PATH
    observations_cache_path: Path = DEFAULT_OBSERVATIONS_CACHE_PATH
    use_calendar_plan: bool = True
    photos_path: Path = DEFAULT_PHOTOS_PATH
    detector_weights_path: Path = DEFAULT_DETECTOR_WEIGHTS_PATH
    project_id: str = DEFAULT_PROJECT_ID

    # Провайдер VLM переключается одной переменной: прежняя модель остаётся
    # рабочим запасным вариантом на случай отказа основной.
    vlm_provider: VlmProvider = DEFAULT_VLM_PROVIDER
    deepseek_api_key: str = ""
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    yc_api_key: str = ""
    yc_folder_id: str = ""
    yc_vlm_base_url: str = DEFAULT_YC_VLM_BASE_URL
    yc_vlm_model: str = DEFAULT_YC_VLM_MODEL
    vlm_max_tokens: int = DEFAULT_VLM_MAX_TOKENS

    facade_cell_weights_path: Path = DEFAULT_FACADE_CELL_WEIGHTS_PATH
    building_weights_path: Path = DEFAULT_BUILDING_WEIGHTS_PATH
    barrier_weights_path: Path = DEFAULT_BARRIER_WEIGHTS_PATH
    facade_cell_threshold: float = DEFAULT_FACADE_CELL_THRESHOLD
    building_threshold: float = DEFAULT_BUILDING_THRESHOLD
    barrier_threshold: float = DEFAULT_BARRIER_THRESHOLD

    detector_confidence_threshold: float = DEFAULT_DETECTOR_THRESHOLD
    idle_streak_days: int = DEFAULT_IDLE_STREAK_DAYS
    slot_minutes: int = DEFAULT_SLOT_MINUTES
    shift_hours: int = DEFAULT_SHIFT_HOURS
    shift_start_hour: int = DEFAULT_SHIFT_START_HOUR
    parallel_requests: int = DEFAULT_PARALLEL_REQUESTS
    slot_photos_path: Path = DEFAULT_SLOT_PHOTOS_PATH
    camera_markup_path: Path = DEFAULT_CAMERA_MARKUP_PATH

    cameras_path: Path = DEFAULT_CAMERAS_PATH
    safety_checks_path: Path = DEFAULT_SAFETY_CHECKS_PATH
    clip_models_path: Path = DEFAULT_CLIP_MODELS_PATH
    clip_phrase_cache_path: Path = DEFAULT_CLIP_PHRASE_CACHE_PATH
    camera_archive_path: Path = DEFAULT_CAMERA_ARCHIVE_PATH
    camera_inbox_path: Path = DEFAULT_CAMERA_INBOX_PATH
    main_service_url: str = DEFAULT_MAIN_SERVICE_URL
    onnx_threads: int = DEFAULT_ONNX_THREADS
    capture_enabled: bool = True
    capture_tick_seconds: int = DEFAULT_CAPTURE_TICK_SECONDS

    @property
    def slots_per_shift(self) -> int:
        """Сколько двадцатиминутных слотов укладывается в смену."""
        count = self.shift_hours * MINUTES_IN_HOUR // self.slot_minutes
        return count
