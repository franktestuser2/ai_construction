"""Прогон смен по календарному плану, который загрузил пользователь.

Ядро сервиса привязывает снимок к работе через календарный план, поэтому
загруженный план сначала записывается в том же виде, что и план демонстрации,
и уже под него собираются зависимости домена.

Этапу достаётся код той работы, чьи правила по технике ему подошли по названию:
иначе правила не нашлись бы и разбирать было бы нечем.
"""

import json
import logging
from datetime import date
from pathlib import Path

from config import Settings

from .adapters.uploaded_plan_reader import UploadedStage
from .container import build_dependencies
from .entity import ShiftTimeline

logger = logging.getLogger(__name__)

PLAN_FILE_NAME = "calendar_plan.json"
FRAME_ID_KEY = "frame_id"
IMAGE_PATH_KEY = "image_path"
OBSERVATION_DATE_KEY = "observation_date"
FRAMES_KEY = "frames"
STAGES_KEY = "stages"


class UploadedPlanPipeline:
    """Собирает домен под загруженный план и разбирает по нему смены."""

    def __init__(self, settings: Settings, plan_dir: Path) -> None:
        self._settings = settings
        self._plan_dir = plan_dir
        self._facade = None

    def prepare(self, stages: tuple[UploadedStage, ...], matched: tuple[str | None, ...]) -> None:
        """Записывает план в формате сервиса и собирает зависимости под него."""
        payload = _build_plan_payload(self._settings.project_id, stages, matched)
        plan_path = self._plan_dir / PLAN_FILE_NAME
        plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        settings = self._settings.model_copy(update={"calendar_plan_path": plan_path})
        self._facade = build_dependencies(settings).facade
        logger.info("Зависимости собраны под загруженный план: этапов %d", len(payload[STAGES_KEY]))

    def run_shift(self, observation_date: date, photos: tuple[Path, ...]) -> ShiftTimeline | None:
        """Разбирает смену одного дня по его снимкам."""
        if self._facade is None:
            return None
        frames = [
            {FRAME_ID_KEY: path.name, IMAGE_PATH_KEY: str(path)}
            for path in photos
        ]
        payload = {OBSERVATION_DATE_KEY: observation_date.isoformat(), FRAMES_KEY: frames}
        timeline = self._facade.assess_shift(payload)
        return timeline


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
