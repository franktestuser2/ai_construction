"""Единственный публичный вход в домен контроля строительных площадок."""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from pathlib import Path

from .entity import (
    DayAssessment,
    Deviation,
    DeviationKind,
    FacadeReadiness,
    FrameObservation,
    MotionObservation,
    PlanEntry,
    ShiftFrames,
    ShiftTimeline,
    StageForecast,
    Work,
    WorkEquipmentRules,
)
from .mappers import map_frames_payload_to_observations
from .adapters.motion_observer import MotionObserver
from .services.equipment_recognition import EquipmentRecognitionService
from .services.facade_readiness import FacadeReadinessService
from .services.forecast import ForecastService
from .services.shift_timeline import ShiftTimelineService
from .services.plan_binding import PlanBindingService
from .services.rule_engine import RuleEngineService

logger = logging.getLogger(__name__)

OBSERVATION_DATE_KEY = "observation_date"
FRAMES_KEY = "frames"
FRAME_ID_KEY = "frame_id"
IMAGE_PATH_KEY = "image_path"
OUT_OF_PLAN_DESCRIPTION = "Дата не входит в календарный план проекта"
NO_RECOGNITION_DESCRIPTION = "Распознавание снимков не настроено: нет доступа к моделям"
NO_RULES_DESCRIPTION = "Для вида работ не заданы правила по технике"
UNKNOWN_WORK_ID = "не определена"
MIN_FRAMES_FOR_MOTION = 2
DEFAULT_PARALLEL_REQUESTS = 8
MIN_PARALLEL_REQUESTS = 1


class SiteMonitoringFacade:
    """Координирует разбор снимков за день и сверку с календарным планом."""

    def __init__(
        self,
        plan_binding: PlanBindingService,
        rule_engine: RuleEngineService,
        forecast: ForecastService,
        rules_by_work: dict[str, WorkEquipmentRules],
        works_by_id: dict[str, Work],
        recognition: EquipmentRecognitionService | None = None,
        facade_readiness: FacadeReadinessService | None = None,
        motion_observer: MotionObserver | None = None,
        shift_timeline: ShiftTimelineService | None = None,
        parallel_requests: int = DEFAULT_PARALLEL_REQUESTS,
        camera_markup: dict[str, tuple[float, float, float, float]] | None = None,
    ) -> None:
        self._plan_binding = plan_binding
        self._rule_engine = rule_engine
        self._forecast = forecast
        self._rules_by_work = rules_by_work
        self._works_by_id = works_by_id
        self._recognition = recognition
        self._facade_readiness = facade_readiness
        self._motion_observer = motion_observer
        self._shift_timeline = shift_timeline
        self._parallel_requests = max(parallel_requests, MIN_PARALLEL_REQUESTS)
        self._camera_markup = camera_markup or {}

    def assess_day(self, payload: dict[str, object]) -> DayAssessment:
        """Выносит вердикт по одному дню плана на основе снимков за этот день."""
        # 1. Сырой вход превращаем в наблюдения домена.
        observation_date = date.fromisoformat(str(payload[OBSERVATION_DATE_KEY]))
        frames_payload = payload.get(FRAMES_KEY) or []
        observations = map_frames_payload_to_observations(frames_payload)  # type: ignore[arg-type]

        # 2. Определяем, какая работа активна в этот день по графику.
        plan_entry = self._plan_binding.entry_for_date(observation_date)
        if plan_entry is None:
            out_of_plan = self._reject_day(observation_date, UNKNOWN_WORK_ID, OUT_OF_PLAN_DESCRIPTION)
            return out_of_plan

        # 3. Берём правила по технике для этого вида работ.
        rules = self._rules_by_work.get(plan_entry.work_id)
        if rules is None:
            no_rules = self._reject_day(observation_date, plan_entry.work_id, NO_RULES_DESCRIPTION)
            return no_rules

        # 4. Сверяем факт с требованиями плана.
        assessment = self._rule_engine.assess_day(plan_entry, rules, observations)
        return assessment

    def assess_day_from_images(self, payload: dict[str, object]) -> DayAssessment:
        """Выносит вердикт по дню, самостоятельно разбирая снимки моделями."""
        # 1. Определяем работу и правила для даты наблюдения.
        observation_date = date.fromisoformat(str(payload[OBSERVATION_DATE_KEY]))
        plan_entry = self._plan_binding.entry_for_date(observation_date)
        if plan_entry is None:
            out_of_plan = self._reject_day(observation_date, UNKNOWN_WORK_ID, OUT_OF_PLAN_DESCRIPTION)
            return out_of_plan
        rules = self._rules_by_work.get(plan_entry.work_id)
        if rules is None or self._recognition is None:
            description = NO_RULES_DESCRIPTION if rules is None else NO_RECOGNITION_DESCRIPTION
            rejected = self._reject_day(observation_date, plan_entry.work_id, description)
            return rejected

        # 2. Каждый снимок разбираем детектором и моделью.
        frames_payload = payload.get(FRAMES_KEY) or []
        observations = self._recognize_frames(frames_payload, observation_date, rules)  # type: ignore[arg-type]

        # 3. Сверяем полученные наблюдения с требованиями плана.
        assessment = self._rule_engine.assess_day(plan_entry, rules, observations)

        # 4. Для фасадных этапов добавляем отдельное измерение готовности фасада.
        readiness = self._assess_facade(frames_payload, rules)  # type: ignore[arg-type]
        if not readiness:
            return assessment
        with_facade = replace(assessment, facade_readiness=readiness)
        return with_facade

    def _recognize_frames(
        self,
        frames_payload: list[dict[str, object]],
        observation_date: date,
        rules: WorkEquipmentRules,
    ) -> tuple[FrameObservation, ...]:
        """Прогоняет снимки дня через распознавание техники.

        Снимки разбираются пачкой: каждый кадр это несколько обращений к модели,
        и ждать их по очереди незачем — друг от друга они не зависят.
        """
        work = self._works_by_id.get(rules.work_id)
        work_name = work.full_name if work is not None else rules.work_id

        def recognize(frame_payload: dict[str, object]) -> FrameObservation:
            observation = self._recognition.recognize_frame(  # type: ignore[union-attr]
                frame_id=str(frame_payload[FRAME_ID_KEY]),
                image_path=Path(str(frame_payload[IMAGE_PATH_KEY])),
                observed_on=observation_date,
                work_name=work_name,
                rules=rules,
            )
            return observation

        observations = self._run_in_parallel(recognize, frames_payload)
        return observations

    def _run_in_parallel(self, action, items: list) -> tuple:
        """Выполняет действие над каждым элементом пачкой, сохраняя порядок."""
        if not items:
            return ()
        workers = min(self._parallel_requests, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = tuple(pool.map(action, items))
        return results

    def observe_shift(self, payload: dict[str, object]) -> ShiftFrames | None:
        """Разбирает снимки смены моделями и отдаёт сырые наблюдения.

        Путь выбирается по пункту плана: на фасадном этапе работают только фасадные
        модели, пайплайн по технике там не запускается вовсе. Отделено от сборки ленты,
        чтобы правила зачёта можно было менять и пересчитывать по кешу.
        """
        # 1. Определяем работу дня и её правила.
        observation_date = date.fromisoformat(str(payload[OBSERVATION_DATE_KEY]))
        plan_entry = self._plan_binding.entry_for_date(observation_date)
        rules = self._rules_by_work.get(plan_entry.work_id) if plan_entry is not None else None
        if plan_entry is None or rules is None:
            logger.info("Смена %s не разбирается: нет пункта плана или правил", observation_date)
            return None

        # 2. Фасадный этап идёт своим путём.
        frames_payload = payload.get(FRAMES_KEY) or []
        frame_ids = tuple(str(item[FRAME_ID_KEY]) for item in frames_payload)  # type: ignore[union-attr]
        if rules.facade_check:
            facade = self._observe_facade(frames_payload, rules.work_id)  # type: ignore[arg-type]
            return ShiftFrames(plan_entry=plan_entry, frame_ids=frame_ids, facade=facade)

        # 3. На прочих этапах снимок разбирается детектором и моделью,
        #    а соседние кадры сравниваются между собой.
        equipment = self._observe_equipment(plan_entry, frame_ids, frames_payload, rules)  # type: ignore[arg-type]
        return equipment

    def _observe_equipment(
        self,
        plan_entry: PlanEntry,
        frame_ids: tuple[str, ...],
        frames_payload: list[dict[str, object]],
        rules: WorkEquipmentRules,
    ) -> ShiftFrames | None:
        """Разбирает смену обычного этапа: техника на кадрах и её работа между кадрами."""
        if self._recognition is None:
            logger.info("Смена %s не разбирается: нет распознавания", plan_entry.plan_date)
            return None
        observations = self._recognize_frames(frames_payload, plan_entry.plan_date, rules)
        motions = self._observe_motion(frames_payload, rules)
        frames = ShiftFrames(
            plan_entry=plan_entry,
            frame_ids=frame_ids,
            observations=observations,
            motions=motions,
        )
        return frames

    def _observe_facade(
        self,
        frames_payload: list[dict[str, object]],
        work_id: str,
    ) -> tuple[FacadeReadiness | None, ...]:
        """Разбирает фасад по каждому снимку смены."""
        if self._facade_readiness is None:
            return ()
        marked_box = self._camera_markup.get(work_id)

        def assess(frame_payload: dict[str, object]) -> FacadeReadiness | None:
            readiness = self._facade_readiness.assess_frame(  # type: ignore[union-attr]
                frame_id=str(frame_payload[FRAME_ID_KEY]),
                image_path=Path(str(frame_payload[IMAGE_PATH_KEY])),
                marked_box=marked_box,
            )
            return readiness

        measured = self._run_in_parallel(assess, frames_payload)
        return measured

    def assess_shift(self, payload: dict[str, object]) -> ShiftTimeline | None:
        """Раскладывает смену одного дня по двадцатиминутным слотам.

        Снимки на входе идут по времени съёмки: первый кадр открывает смену,
        каждый следующий приходит через двадцать минут.
        """
        frames = self.observe_shift(payload)
        if frames is None or self._shift_timeline is None:
            return None
        rules = self._rules_by_work[frames.plan_entry.work_id]
        timeline = self._shift_timeline.build_timeline(rules, frames)
        return timeline

    def _observe_motion(
        self,
        frames_payload: list[dict[str, object]],
        rules: WorkEquipmentRules,
    ) -> tuple[MotionObservation | None, ...]:
        """Сравнивает каждый кадр смены с предыдущим.

        Результат выравнивается по слотам: у первого кадра предыдущего нет,
        поэтому его слот остаётся без признака движения. Пары независимы
        и считаются одновременно.
        """
        if self._motion_observer is None or len(frames_payload) < MIN_FRAMES_FOR_MOTION:
            return ()
        work = self._works_by_id.get(rules.work_id)
        work_name = work.full_name if work is not None else rules.work_id
        pairs = list(zip(frames_payload, frames_payload[1:]))

        def compare(pair: tuple[dict[str, object], dict[str, object]]) -> MotionObservation:
            earlier, later = pair
            motion = self._motion_observer.compare(  # type: ignore[union-attr]
                earlier_path=Path(str(earlier[IMAGE_PATH_KEY])),
                later_path=Path(str(later[IMAGE_PATH_KEY])),
                work_name=work_name,
            )
            return motion

        compared = self._run_in_parallel(compare, pairs)
        aligned = (None,) + compared
        return aligned

    def _assess_facade(
        self,
        frames_payload: list[dict[str, object]],
        rules: WorkEquipmentRules,
    ) -> tuple[FacadeReadiness, ...]:
        """Разбирает фасад по снимкам дня, если этап того требует.

        Гейт двойной: сначала календарный план — на котловане и сваях фасада ещё нет,
        затем детектор зданий внутри самого разбора.
        """
        if not rules.facade_check or self._facade_readiness is None:
            return ()
        measurements = []
        for frame_payload in frames_payload:
            image_path = Path(str(frame_payload[IMAGE_PATH_KEY]))
            readiness = self._facade_readiness.assess_frame(
                frame_id=str(frame_payload[FRAME_ID_KEY]),
                image_path=image_path,
            )
            if readiness is not None:
                measurements.append(readiness)
        result = tuple(measurements)
        return result

    def assess_stage(self, work_id: str, assessments: tuple[DayAssessment, ...]) -> StageForecast | None:
        """Строит прогноз по этапу из накопленных дневных вердиктов."""
        # 1. Плановые границы этапа берём из календарного плана.
        stage_start = self._plan_binding.stage_start(work_id)
        planned_days = self._plan_binding.planned_duration(work_id)
        if stage_start is None or planned_days == 0:
            logger.info("Этап %s отсутствует в плане, прогноз не строится", work_id)
            return None

        # 2. Продуктивные сутки — дни, признанные соответствующими плану.
        stage_assessments = [item for item in assessments if item.work_id == work_id]
        productive_days = sum(1 for item in stage_assessments if item.is_compliant)

        # 3. Считаем темп, прогнозную дату завершения и отставание.
        forecast = self._forecast.build_forecast(
            work_id=work_id,
            planned_days=planned_days,
            stage_start=stage_start,
            elapsed_days=len(stage_assessments),
            productive_days=productive_days,
        )
        return forecast

    def _reject_day(self, observation_date: date, work_id: str, description: str) -> DayAssessment:
        """Формирует отрицательный вердикт, когда сверка невозможна."""
        deviation = Deviation(DeviationKind.NO_DATA, None, description)
        assessment = DayAssessment(
            plan_date=observation_date,
            work_id=work_id,
            is_compliant=False,
            deviations=(deviation,),
        )
        logger.info("День %s отклонён: %s", observation_date, description)
        return assessment
