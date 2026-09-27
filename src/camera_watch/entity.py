"""Сущности контура наблюдения за камерами.

Контур решает три задачи: показать картинку камеры онлайн, хранить снятое и с
заданной периодичностью снимать кадр, проверять его на нарушения охраны труда
и отдавать основному сервису. Здесь описано то, чем эти задачи оперируют.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Источник камеры — либо файл с роликом, либо адрес живого потока.
STREAM_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://")

PRESENT = "есть"
ABSENT = "нет"
UNCLEAR = "не ясно"
PHRASES_MODEL = "фразы"
CLASSIFIER_MODEL = "классификатор"
PERSON_SCOPE = "человек"
# Каска решается по голове, а не по всей фигуре: на фигуре целиком вырезку забивает
# спецовка, и модель отвечала «каска есть» даже там, где человек в вязаной шапке.
HEAD_SCOPE = "голова"
FRAME_SCOPE = "кадр"
# Два способа найти людей в кадре: обученный детектор и вычитание фона. Выбор за камерой,
# потому что ни один из них не годится и там, и там.
MOTION_SOURCE = "движение"
DETECTOR_SOURCE = "детектор"


@dataclass(frozen=True, slots=True)
class Camera:
    """Камера площадки: источник картинки и правила съёмки по ней."""

    camera_id: str
    title: str
    place: str
    source: str
    capture_period_minutes: int
    safety_enabled: bool = True
    people_source: str = MOTION_SOURCE
    origin: str = ""
    notes: str = ""

    @property
    def is_live(self) -> bool:
        """Живой поток или ролик на диске."""
        live = self.source.startswith(STREAM_SCHEMES)
        return live


@dataclass(frozen=True, slots=True)
class PersonRegion:
    """Область кадра, в которой предположительно находится человек."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        """Рамка области в пикселях кадра."""
        corners = (self.left, self.top, self.right, self.bottom)
        return corners

    @property
    def area(self) -> int:
        """Площадь области в пикселях."""
        size = max(0, self.right - self.left) * max(0, self.bottom - self.top)
        return size


@dataclass(frozen=True, slots=True)
class SafetyCheck:
    """Проверка охраны труда: набор фраз «за» против набора фраз «против».

    Порог и минимальный отрыв — часть определения проверки, а не общая настройка:
    у каждой формулировки своя разделяющая способность, измеренная отдельно.
    """

    key: str
    title: str
    scope: str
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    threshold: float
    strict_threshold: float
    min_margin: float
    # Чем решается проверка: обученной сетью или сравнением текстовых фраз.
    model: str = PHRASES_MODEL
    weights: str = ""
    measured_on: str = ""


@dataclass(frozen=True, slots=True)
class SafetyFinding:
    """Результат одной проверки на одном кадре или на одной области кадра.

    Исхода три, а не два: малый отрыв означает «сравнение не разделило фразы»,
    и записывать это в «нарушения нет» нельзя — модель просто не ответила.
    """

    check_key: str
    title: str
    verdict: str
    confidence: float
    margin: float
    best_positive: str
    best_negative: str
    box: tuple[int, int, int, int] | None = None
    confident: bool = False

    @property
    def is_violation(self) -> bool:
        """Считается ли находка нарушением охраны труда."""
        found = self.verdict == PRESENT
        return found


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """Снятый по расписанию кадр со всем, что о нём известно."""

    camera_id: str
    captured_at: datetime
    file_name: str
    source_second: float
    people: tuple[PersonRegion, ...] = ()
    findings: tuple[SafetyFinding, ...] = ()
    clip_name: str = ""
    sent_at: datetime | None = None

    @property
    def violations(self) -> tuple[SafetyFinding, ...]:
        """Находки, признанные нарушениями."""
        found = tuple(item for item in self.findings if item.is_violation)
        return found

    @property
    def unclear(self) -> tuple[SafetyFinding, ...]:
        """Находки, по которым модель не дала разделения."""
        found = tuple(item for item in self.findings if item.verdict == UNCLEAR)
        return found


@dataclass(frozen=True, slots=True)
class CameraState:
    """Состояние камеры для списка: когда снимали и что нашли."""

    camera: Camera
    frames_stored: int = 0
    last_photo: str = ""
    last_captured_at: datetime | None = None
    last_violation_at: datetime | None = None
    violations_total: int = 0
    unsent_frames: int = 0


@dataclass
class CaptureOutcome:
    """Итог одной съёмки: кадр, путь к файлу и что с ним дальше делать."""

    frame: CapturedFrame
    photo_path: Path
    clip_path: Path | None = None
    notes: list[str] = field(default_factory=list)
