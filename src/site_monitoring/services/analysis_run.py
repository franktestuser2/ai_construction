"""Прогон загруженных пользователем данных: план и снимки → ленты смен.

Сервис ведёт прогон от начала до конца и по ходу обновляет его состояние, чтобы
страница показывала прогресс: разбор смены занимает минуты, и ждать молча нельзя.

Этапы плана связываются с правилами по технике по названию: сведений о технике
в календарном плане заказчика нет, это оговорено в требованиях.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from ..adapters.run_storage import STATUS_DONE, STATUS_FAILED, STATUS_RUNNING, RunState, RunStorage
from ..adapters.uploaded_plan_reader import UploadedPlanReader, UploadedStage
from ..entity import ShiftTimeline
from .photo_binding import BindingResult, bind_photos
from .plan_rule_matcher import match_stages

logger = logging.getLogger(__name__)

NOTHING = 0
NO_RULES_TITLE = "правила по технике не заданы"
FRAMES_KEY = "frames"
PLAN_FILE_GLOB = "*"


class ShiftPipeline(Protocol):
    """Прогон смен по загруженному плану.

    Сначала под план собираются зависимости — календарный план и правила, —
    затем по каждому этапу разбирается его смена.
    """

    def prepare(self, stages: tuple[UploadedStage, ...], matched: tuple[str | None, ...]) -> None:
        """Готовит зависимости под загруженный план."""

    def run_shift(self, observation_date: date, photos: tuple[Path, ...]) -> ShiftTimeline | None:
        """Разбирает смену одного дня по его снимкам."""


@dataclass(frozen=True)
class WorkOutcome:
    """Итог разбора одного этапа плана."""

    title: str
    work_id: str | None
    photo_count: int
    timeline: ShiftTimeline | None


class AnalysisRunService:
    """Разбирает загруженные план и снимки, обновляя состояние прогона."""

    def __init__(self, storage: RunStorage, pipeline: ShiftPipeline, known_titles: dict[str, str]) -> None:
        self._storage = storage
        self._pipeline = pipeline
        self._known_titles = known_titles

    def execute(self, run_id: str) -> None:
        """Прогоняет загруженные данные и записывает результат в состояние."""
        state = self._storage.load(run_id)
        if state is None:
            logger.warning("Прогон %s не найден", run_id)
            return
        try:
            self._run(state)
        except (ValueError, OSError, KeyError):
            logger.exception("Прогон %s не выполнен", run_id)
            state.status = STATUS_FAILED
            state.error = "Разобрать загруженные данные не удалось, подробности в журнале сервиса"
            self._storage.save(state)

    def _run(self, state: RunState) -> None:
        """Читает план, раскладывает снимки и разбирает каждый этап."""
        stages = self._read_plan(state.run_id)
        photos = tuple(sorted(self._storage.photos_dir(state.run_id).iterdir()))
        binding = bind_photos(stages, photos)
        matched = match_stages(tuple(stage.full_name for stage in stages), self._known_titles)
        self._pipeline.prepare(stages, matched)
        self._start(state, binding, matched)
        outcomes = self._process_stages(state, binding, matched)
        self._save_timelines(state.run_id, outcomes)
        state.works = [_describe(outcome) for outcome in outcomes]
        state.status = STATUS_DONE
        state.stage_title = ""
        self._storage.save(state)
        logger.info("Прогон %s завершён: этапов %d", state.run_id, len(outcomes))

    def _save_timelines(self, run_id: str, outcomes: tuple[WorkOutcome, ...]) -> None:
        """Складывает посчитанные ленты рядом с прогоном: по ним строятся его страницы."""
        payload = {
            outcome.work_id: asdict(outcome.timeline)
            for outcome in outcomes
            if outcome.work_id is not None and outcome.timeline is not None
        }
        path = self._storage.timelines_path(run_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        logger.info("Ленты прогона %s сохранены: смен %d", run_id, len(payload))

    def _read_plan(self, run_id: str) -> tuple[UploadedStage, ...]:
        """Читает загруженный календарный план."""
        files = sorted(self._storage.plan_dir(run_id).glob(PLAN_FILE_GLOB))
        reader = UploadedPlanReader(files[0])
        stages = reader.read_stages()
        return stages

    def _start(self, state: RunState, binding: BindingResult, matched: tuple[str | None, ...]) -> None:
        """Отмечает начало разбора и заполняет счётчики прогресса."""
        state.status = STATUS_RUNNING
        state.binding = binding.method
        state.stages_total = sum(1 for work_id in matched if work_id is not None)
        state.total_frames = sum(
            len(item.photos) for item, work_id in zip(binding.stages, matched) if work_id is not None
        )
        state.done_frames = NOTHING
        self._storage.save(state)

    def _process_stages(
        self,
        state: RunState,
        binding: BindingResult,
        matched: tuple[str | None, ...],
    ) -> tuple[WorkOutcome, ...]:
        """Разбирает по очереди те этапы, для которых нашлись правила."""
        outcomes = []
        for item, work_id in zip(binding.stages, matched):
            if work_id is None or not item.photos:
                outcomes.append(WorkOutcome(item.stage.full_name, work_id, len(item.photos), None))
                continue
            state.stage_title = item.stage.full_name
            self._storage.save(state)
            paths = tuple(photo.path for photo in item.photos)
            timeline = self._pipeline.run_shift(item.stage.start, paths)
            state.done_frames += len(item.photos)
            self._storage.save(state)
            outcomes.append(WorkOutcome(item.stage.full_name, work_id, len(item.photos), timeline))
        return tuple(outcomes)


def _describe(outcome: WorkOutcome) -> dict[str, object]:
    """Готовит итог этапа для записи в состояние прогона."""
    timeline = outcome.timeline
    described = {
        "title": outcome.title,
        "work_id": outcome.work_id or NO_RULES_TITLE,
        "limited_slots": timeline.limited_slots if timeline is not None else NOTHING,
        "foreign_slots": timeline.foreign_slots if timeline is not None else NOTHING,
        "photo_count": outcome.photo_count,
        "counted_slots": timeline.counted_slots if timeline is not None else NOTHING,
        "planned_slots": len(timeline.slots) if timeline is not None else NOTHING,
        "counted_minutes": timeline.counted_minutes if timeline is not None else NOTHING,
        "on_schedule": timeline.is_on_schedule if timeline is not None else False,
    }
    return described
