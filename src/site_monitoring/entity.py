"""Структуры данных домена контроля строительных площадок."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class EquipmentSource(str, Enum):
    """Источник сведений о единице техники на снимке."""

    DETECTOR = "detector"
    VLM = "vlm"


class EquipmentStatus(str, Enum):
    """Состояние техники, определённое визуально-языковой моделью."""

    WORKING = "работает"
    IDLE = "простаивает"
    NOT_ENGAGED = "не задействована"
    NOT_APPLICABLE = "не применимо"


class VlmProvider(str, Enum):
    """Поставщик мультимодальной модели.

    Различия провайдеров сводятся к заголовку авторизации, виду имени модели
    и способу потребовать JSON; на промпты и разбор ответа выбор не влияет.
    """

    DEEPSEEK = "deepseek"
    YANDEX = "yandex"


class PositionKind(str, Enum):
    """Вид позиции в правилах этапа.

    Признак работ — состояние самого объекта, комплект — техника, без которой
    работа физически не идёт, сопутствующая — та, что может быть, а может не быть.
    """

    WORK_EVIDENCE = "признак_работ"
    KIT = "комплект"
    ACCOMPANYING = "сопутствующая"


class FacadeCellKind(str, Enum):
    """Стадия готовности ячейки фасада.

    Ячейка это один оконный проём со стеной вокруг него. Стадии выстроены
    лестницей: сначала голый проём в монолите, затем кладка, затем остекление.
    """

    MONOLITH = "монолит"
    BLOCK = "блок"
    WINDOW = "окно"


class DeviationKind(str, Enum):
    """Виды отклонений факта от календарного плана."""

    MISSING_EQUIPMENT = "отсутствует_обязательная_техника"
    MISSING_AUXILIARY = "нехватка_сопутствующей_техники"
    MISSING_WORK_EVIDENCE = "нет_признака_работ"
    INCOMPLETE_KIT = "неполный_комплект"
    NOT_VERIFIED = "не_проверено"
    IDLE_EQUIPMENT = "простой_техники"
    NO_DATA = "нет_данных"
    LIMITED_VIEW = "обзор_ограничен"


class StageStatus(str, Enum):
    """Итоговый статус этапа относительно календарного графика."""

    ON_SCHEDULE = "соответствие"
    RISK_OF_DELAY = "риск_отставания"
    DELAYED = "отставание"


@dataclass(frozen=True)
class Work:
    """Вид работ из справочника проекта."""

    work_id: str
    full_name: str


@dataclass(frozen=True)
class PlanEntry:
    """Одна строка календарного плана: какая работа активна в конкретный день."""

    project_id: str
    work_id: str
    plan_date: date


@dataclass(frozen=True)
class PositionAlternative:
    """Один способ закрыть позицию правил: конкретная машина и источник признака."""

    machine_type: str
    source: EquipmentSource
    detector_classes: tuple[str, ...] = field(default_factory=tuple)
    vlm_question: str | None = None


@dataclass(frozen=True)
class WorkPosition:
    """Позиция правил этапа: чем её закрыть и обязательна ли она.

    Позиция считается закрытой, если сработала любая из альтернатив: подачу бетона
    одинаково подтверждают миксер, бетононасос и автокран.
    """

    position: str
    kind: PositionKind
    min_count: int
    alternatives: tuple[PositionAlternative, ...]
    is_lead: bool = False


@dataclass(frozen=True)
class WorkEquipmentRules:
    """Набор позиций правил для одного вида работ."""

    work_id: str
    positions: tuple[WorkPosition, ...]
    # Этап, на котором здание уже стоит и разбор фасада осмыслен. Для котлована,
    # свай и плиты фасада ещё нет, и гонять по ним фасадные модели незачем.
    facade_check: bool = False


@dataclass(frozen=True)
class ObservedEquipment:
    """Единица техники, зафиксированная на снимке."""

    machine_type: str
    source: EquipmentSource
    status: EquipmentStatus
    count: int
    confidence: float | None = None
    justification: str | None = None
    boxes: tuple[tuple[float, float, float, float], ...] = ()
    rejected_boxes: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class ArbitrationResult:
    """Вывод арбитра по одной рамке детектора."""

    confirmed: bool
    actual_class: str
    status: EquipmentStatus
    justification: str


@dataclass(frozen=True)
class FrameObservation:
    """Результат разбора одного снимка площадки."""

    frame_id: str
    observed_on: date
    equipment: tuple[ObservedEquipment, ...]
    limited_view: bool = False


@dataclass(frozen=True)
class Deviation:
    """Зафиксированное отклонение от плана за конкретный день."""

    kind: DeviationKind
    machine_type: str | None
    description: str


@dataclass(frozen=True)
class DayAssessment:
    """Вердикт по одному дню плана: соответствие или отклонение."""

    plan_date: date
    work_id: str
    is_compliant: bool
    deviations: tuple[Deviation, ...] = field(default_factory=tuple)
    confirmed_equipment: tuple[str, ...] = field(default_factory=tuple)
    # Обзор перекрыт или снимков за день слишком мало: день не измерен,
    # и его нельзя записывать подрядчику в отставание.
    is_verifiable: bool = True
    # Разбор фасада по снимкам дня. Это отдельное измерение готовности,
    # на соответствие дня плану оно не влияет.
    facade_readiness: tuple["FacadeReadiness", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StageForecast:
    """Прогноз завершения этапа по накопленным продуктивным суткам."""

    work_id: str
    planned_days: int
    elapsed_days: int
    productive_days: int
    pace: float
    lag_days: int
    status: StageStatus
    forecast_finish: date | None


class SlotOutcome(str, Enum):
    """Ожидаемый исход слота синтетической смены."""

    WORKING = "работа"
    IDLE = "простой"
    ABSENT = "техники нет"
    INCOMPLETE_KIT = "неполный комплект"


@dataclass(frozen=True)
class SyntheticSlot:
    """Плановый слот синтетической смены: что должно быть на кадре и что ждём от правил."""

    index: int
    clock: str
    outcome: SlotOutcome
    lead_present: bool
    kit_present: bool
    machine_moves: bool
    camera_shake: bool


@dataclass(frozen=True)
class SyntheticShift:
    """Раскладка синтетической смены по слотам с ожидаемым числом рабочих часов."""

    scenario: str
    title: str
    slots: tuple[SyntheticSlot, ...]
    expected_hours: float


@dataclass(frozen=True)
class FacadeCell:
    """Одна ячейка фасада, найденная детектором."""

    kind: FacadeCellKind
    box: tuple[float, float, float, float]
    score: float


@dataclass(frozen=True)
class BuildingBox:
    """Здание, найденное на снимке."""

    box: tuple[float, float, float, float]
    score: float


@dataclass(frozen=True)
class FacadeReadiness:
    """Готовность фасада, измеренная по одному снимку.

    Считается доля ячеек каждой стадии: голый проём в монолите, проём с кладкой,
    остеклённый проём. Нарушения ОТиПБ по ограждениям идут отдельным счётчиком.
    """

    frame_id: str
    building_score: float
    cells_total: int
    monolith: int
    block: int
    window: int
    rows: int
    barrier_checked: int
    barrier_violations: int
    # Рамки в пикселях исходного кадра: нужны показу, чтобы разбор фасада
    # можно было увидеть на снимке, а не только в счётчиках.
    building_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    cells: tuple[FacadeCell, ...] = ()

    @property
    def closed_share(self) -> float:
        """Доля проёмов, которые уже заполнены кладкой или остеклены."""
        if self.cells_total == 0:
            return 0.0
        share = (self.block + self.window) / self.cells_total
        return share

    @property
    def glazed_share(self) -> float:
        """Доля остеклённых проёмов."""
        if self.cells_total == 0:
            return 0.0
        share = self.window / self.cells_total
        return share


class SlotStripe(str, Enum):
    """Признак, засчитанный слоту смены.

    Три признака показываются полосками: техника на месте, комплект собран,
    техника действительно работает. Все три вместе закрывают слот.
    """

    EQUIPMENT = "техника"
    KIT = "комплект"
    MOTION = "движение"


@dataclass(frozen=True)
class MotionObservation:
    """Сравнение двух соседних снимков: работает техника или просто стоит."""

    moved: bool
    operator_present: bool
    working_body_changed: bool
    justification: str

    @property
    def has_motion(self) -> bool:
        """Признак работы: сдвинулась машина, сменил положение рабочий орган или виден оператор."""
        detected = self.moved or self.operator_present or self.working_body_changed
        return detected


@dataclass(frozen=True)
class ShiftSlot:
    """Один двадцатиминутный отрезок смены."""

    index: int
    starts_at: datetime
    frame_id: str | None
    has_equipment: bool
    has_kit: bool
    has_motion: bool
    # Первый снимок смены не с чем сравнивать: предыдущего кадра нет.
    # Движение по нему не измеряется и для зачёта не требуется.
    is_first: bool
    # Фронт работ не попал в кадр: снимок вне контроля ИИ и требует ручной проверки.
    # Такой отрезок не засчитывается, но и в отставание подрядчику не пишется.
    limited_view: bool = False

    @property
    def stripes(self) -> tuple[SlotStripe, ...]:
        """Полоски, набранные слотом."""
        collected = []
        if self.has_equipment:
            collected.append(SlotStripe.EQUIPMENT)
        if self.has_kit:
            collected.append(SlotStripe.KIT)
        if self.has_motion:
            collected.append(SlotStripe.MOTION)
        return tuple(collected)

    @property
    def is_counted(self) -> bool:
        """Засчитан ли слот в отработанное время."""
        if self.frame_id is None or self.limited_view:
            return False
        if self.is_first:
            counted = self.has_equipment and self.has_kit
            return counted
        full = self.has_equipment and self.has_kit and self.has_motion
        return full


@dataclass(frozen=True)
class ShiftTimeline:
    """Смена одного дня, разложенная по слотам."""

    plan_date: date
    work_id: str
    slot_minutes: int
    slots: tuple[ShiftSlot, ...]

    @property
    def counted_slots(self) -> int:
        """Число засчитанных слотов."""
        counted = sum(1 for slot in self.slots if slot.is_counted)
        return counted

    @property
    def counted_minutes(self) -> int:
        """Отработанное время, засчитанное сервисом."""
        minutes = self.counted_slots * self.slot_minutes
        return minutes

    @property
    def planned_minutes(self) -> int:
        """Плановая длительность смены."""
        minutes = len(self.slots) * self.slot_minutes
        return minutes

    @property
    def limited_slots(self) -> int:
        """Число отрезков, по которым фронт работ не виден."""
        limited = sum(1 for slot in self.slots if slot.limited_view)
        return limited

    @property
    def needs_manual_check(self) -> bool:
        """Требует ли смена ручной проверки: часть площадки вне контроля ИИ."""
        needed = self.limited_slots > 0
        return needed

    @property
    def is_on_schedule(self) -> bool:
        """Идёт ли день по графику.

        День засчитывается, когда хотя бы один отрезок смены закрыт полностью:
        на площадке ведущая машина, за смену собран комплект, техника работала.
        """
        on_schedule = self.counted_slots > 0
        return on_schedule


@dataclass(frozen=True)
class ShiftFrames:
    """Разобранные снимки смены до применения правил зачёта.

    Смена идёт по одному из двух путей и никогда по обоим сразу: на этапах с техникой
    заполняются наблюдения и сравнения пар кадров, на фасадном этапе — разбор фасада.
    """

    plan_entry: PlanEntry
    frame_ids: tuple[str, ...]
    observations: tuple[FrameObservation, ...] = ()
    motions: tuple["MotionObservation | None", ...] = ()
    facade: tuple["FacadeReadiness | None", ...] = ()

    @property
    def is_facade(self) -> bool:
        """Шла ли смена по фасадному пути."""
        facade_path = len(self.facade) > 0
        return facade_path
