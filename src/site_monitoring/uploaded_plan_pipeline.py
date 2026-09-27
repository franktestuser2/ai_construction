"""Прогон смен по календарному плану, который загрузил пользователь.

Ядро сервиса привязывает снимок к работе через календарный план, поэтому
загруженный план сначала записывается в том же виде, что и план демонстрации,
и уже под него собираются зависимости домена.

Этапу достаётся код той работы, чьи правила по технике ему подошли по названию:
иначе правила не нашлись бы и разбирать было бы нечем.
"""

import json
import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path

from config import Settings

from .adapters.uploaded_plan_reader import UploadedStage
from .container import build_dependencies
from .entity import ShiftFrames, ShiftTimeline
from .adapters.photo_timestamp_reader import read_capture_time
from .services.camera_grouping import group_by_camera
from .services.multi_camera_shift import merge_timelines

logger = logging.getLogger(__name__)

PLAN_FILE_NAME = "calendar_plan.json"
OBSERVATIONS_FILE_NAME = "observations.json"
FRAME_ID_KEY = "frame_id"
IMAGE_PATH_KEY = "image_path"
CAPTURED_AT_KEY = "captured_at"
OBSERVATION_DATE_KEY = "observation_date"
FRAMES_KEY = "frames"
STAGES_KEY = "stages"


class UploadedPlanPipeline:
    """Собирает домен под загруженный план и разбирает по нему смены."""

    def __init__(self, settings: Settings, plan_dir: Path) -> None:
        self._settings = settings
        self._plan_dir = plan_dir
        self._facade = None
        self._dependencies = None

    def prepare(self, stages: tuple[UploadedStage, ...], matched: tuple[str | None, ...]) -> None:
        """Записывает план в формате сервиса и собирает зависимости под него."""
        payload = _build_plan_payload(self._settings.project_id, stages, matched)
        plan_path = self._plan_dir / PLAN_FILE_NAME
        plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        settings = self._settings.model_copy(update={"calendar_plan_path": plan_path})
        self._dependencies = build_dependencies(settings)
        self._facade = self._dependencies.facade
        logger.info("Зависимости собраны под загруженный план: этапов %d", len(payload[STAGES_KEY]))

    def run_shift(self, observation_date: date, photos: tuple[Path, ...]) -> ShiftTimeline | None:
        """Разбирает смену одного дня по снимкам всех камер объекта.

        Каждая камера разбирается своим рядом, и только готовые ленты сводятся в одну:
        работа между кадрами определяется сравнением соседних снимков одной камеры.
        Отрезок засчитан, если работа подтверждена хотя бы на одной из них.

        Сырые наблюдения складываются рядом: по ним страница показывает, что
        именно модели нашли на каждом кадре.
        """
        if self._facade is None:
            return None
        by_camera = group_by_camera(photos)
        observed = self._observe_cameras(observation_date, by_camera)
        if not observed:
            return None
        self._store_observations(observed)
        rules = self._rules(next(iter(observed.values())).plan_entry.work_id)
        timelines = {name: self._timeline(rules, raw) for name, raw in observed.items()}
        merged = merge_timelines(timelines)
        return merged

    def _observe_cameras(
        self, observation_date: date, by_camera: dict[str, tuple[Path, ...]]
    ) -> dict[str, ShiftFrames]:
        """Разбирает снимки каждой камеры отдельным рядом."""
        observed: dict[str, ShiftFrames] = {}
        for name, paths in by_camera.items():
            frames = [_frame_payload(path) for path in paths]
            payload = {OBSERVATION_DATE_KEY: observation_date.isoformat(), FRAMES_KEY: frames}
            raw = self._facade.observe_shift(payload)
            if raw is not None:
                observed[name] = raw
        return observed

    def _rules(self, work_id: str):
        """Правила вида работ, собранные под загруженный план."""
        return self._dependencies.rules_by_work[work_id]

    def _timeline(self, rules, frames):
        """Лента смены по разобранным кадрам."""
        timeline = self._dependencies.facade._shift_timeline.build_timeline(rules, frames)
        return timeline

    def _store_observations(self, observed: dict[str, ShiftFrames]) -> None:
        """Дописывает сырые наблюдения смены в общий файл прогона.

        Кадры всех камер идут одним перечнем: страница ищет разбор по имени снимка,
        а имя несёт в себе камеру.
        """
        first = next(iter(observed.values()))
        path = self._plan_dir / OBSERVATIONS_FILE_NAME
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        stored[first.plan_entry.work_id] = {
            "plan_date": first.plan_entry.plan_date.isoformat(),
            "cameras": sorted(observed),
            "frame_ids": [name for frames in observed.values() for name in frames.frame_ids],
            "observations": [
                asdict(item) for frames in observed.values() for item in frames.observations
            ],
            "motions": [
                asdict(item) if item is not None else None
                for frames in observed.values()
                for item in frames.motions
            ],
            "facade": [
                asdict(item) if item is not None else None
                for frames in observed.values()
                for item in frames.facade
            ],
        }
        path.write_text(json.dumps(stored, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _frame_payload(path: Path) -> dict[str, object]:
    """Готовит кадр к разбору: путь и время съёмки из его метаданных."""
    captured_at, _ = read_capture_time(path)
    payload = {
        FRAME_ID_KEY: path.name,
        IMAGE_PATH_KEY: str(path),
        CAPTURED_AT_KEY: captured_at.isoformat(),
    }
    return payload


def _build_plan_payload(
    project_id: str,
    stages: tuple[UploadedStage, ...],
    matched: tuple[str | None, ...],
) -> dict[str, object]:
    """Переводит загруженный план в формат календарного плана сервиса."""
    written = []
    for stage, work_id in zip(stages, matched):
        if work_id is None:
            continue
        written.append(
            {
                "work_id": work_id,
                "code": "",
                "full_name": stage.full_name,
                "short_name": stage.full_name.split(" → ")[-1],
                "start": stage.start.isoformat(),
                "finish": stage.finish.isoformat(),
                "photos": [],
            }
        )
    payload = {
        "project_id": project_id,
        "object": "Объект пользователя",
        "direction": "",
        "start": written[0]["start"] if written else "",
        "finish": written[-1]["finish"] if written else "",
        "duration_days": len(written),
        STAGES_KEY: written,
    }
    return payload
