"""Приёмная основного сервиса: сюда контур наблюдения отдаёт снятые кадры.

Камеры не знают ни о календарном плане, ни о каталогах разбора: они присылают снимки
по HTTP, а сервис сам решает, когда и с каким планом их разбирать.

Вид работ руками не выбирается. У объекта есть календарный план, и этап определяется
датой съёмки: сегодня в плане такой-то этап, значит снятое сегодня разбирается по его
правилам. Именно так задача и поставлена — сверка факта с планом, а не наоборот.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from ingest_pages import render_ingest
from site_monitoring.adapters.uploaded_plan_reader import UploadedPlanReader, UploadedStage

logger = logging.getLogger(__name__)

INGEST_URL = "/ingest"
RUN_URL_TEMPLATE = "/runs/{run_id}"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
REDIRECT_CODE = 303
EMPTY_QUEUE_MESSAGE = "В очереди нет снимков"
NO_PLAN_MESSAGE = "Календарный план объекта не найден"
ACCEPTED_KEY = "accepted"
NOTHING = 0
StartRun = Callable[[bytes, str, list[tuple[str, bytes]]], str]


def build_ingest_router(inbox: Path, plan_path: Path, start_run: StartRun, note: str) -> APIRouter:
    """Собирает маршруты приёмной вокруг плана объекта и способа запускать разбор."""
    router = APIRouter()

    @router.post("/ingest/frames")
    async def accept_frames(
        camera_id: str = Form(...), photos: list[UploadFile] = File(...)
    ) -> dict[str, int]:
        """Принимает снимки одной камеры и кладёт их в очередь на разбор."""
        directory = inbox / Path(camera_id).name
        directory.mkdir(parents=True, exist_ok=True)
        accepted = NOTHING
        for photo in photos:
            name = Path(photo.filename or "").name
            if not name or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            (directory / name).write_bytes(await photo.read())
            accepted += 1
        logger.info("Приёмная: от камеры %s принято снимков %d", camera_id, accepted)
        return {ACCEPTED_KEY: accepted}

    @router.get(INGEST_URL, response_class=HTMLResponse)
    def ingest_page() -> HTMLResponse:
        """Страница приёмной: очередь, этап плана на сегодня и запуск разбора."""
        stages = read_plan(plan_path)
        page = render_ingest(_queue(inbox), stage_for(stages, date.today()), len(stages), note)
        return HTMLResponse(page)

    @router.post("/ingest/run")
    def run_queue() -> RedirectResponse:
        """Пускает накопленные кадры в разбор по календарному плану объекта."""
        run_id = run_pool(inbox, plan_path, start_run)
        if run_id is None:
            raise HTTPException(status_code=400, detail=EMPTY_QUEUE_MESSAGE)
        return RedirectResponse(RUN_URL_TEMPLATE.format(run_id=run_id), status_code=REDIRECT_CODE)

    return router


def run_pool(inbox: Path, plan_path: Path, start_run: StartRun) -> str | None:
    """Отдаёт накопленные снимки в разбор вместе с планом объекта.

    Этап каждому снимку выбирает сам разбор — по дате съёмки из метаданных.
    """
    photos = _collect_photos(inbox)
    if not photos:
        return None
    if not plan_path.exists():
        raise FileNotFoundError(NO_PLAN_MESSAGE)
    run_id = start_run(plan_path.read_bytes(), plan_path.name, photos)
    _clear_queue(inbox)
    logger.info("Снимки с камер пущены в разбор: прогон %s, кадров %d", run_id, len(photos))
    return run_id


def read_plan(plan_path: Path) -> tuple[UploadedStage, ...]:
    """Читает календарный план объекта."""
    if not plan_path.exists():
        logger.warning("Календарный план объекта не найден: %s", plan_path)
        return ()
    stages = UploadedPlanReader(plan_path).read_stages()
    return stages


def stage_for(stages: tuple[UploadedStage, ...], day: date) -> UploadedStage | None:
    """Этап плана, который приходится на заданный день."""
    found = next((stage for stage in stages if stage.start <= day <= stage.finish), None)
    return found


def prune_queue(inbox: Path, keep_after: datetime) -> int:
    """Убирает из очереди снимки старше срока хранения.

    Очередь чистится тем же сроком, что и архив: если разбор так и не запустили,
    вчерашние кадры сверять уже не с чем — смена кончилась.
    """
    if not inbox.exists():
        return NOTHING
    removed = NOTHING
    for directory in inbox.iterdir():
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            if _is_image(item) and datetime.fromtimestamp(item.stat().st_mtime) < keep_after:
                item.unlink()
                removed += 1
    if removed:
        logger.info("Очередь приёмной: убрано снимков старше срока хранения: %d", removed)
    return removed


def _queue(inbox: Path) -> dict[str, int]:
    """Сколько снимков ждёт разбора по каждой камере."""
    if not inbox.exists():
        return {}
    counts = {
        directory.name: sum(1 for item in directory.iterdir() if _is_image(item))
        for directory in inbox.iterdir()
        if directory.is_dir()
    }
    return {name: count for name, count in counts.items() if count}


def _collect_photos(inbox: Path) -> list[tuple[str, bytes]]:
    """Собирает все снимки очереди."""
    if not inbox.exists():
        return []
    photos = [
        (item.name, item.read_bytes())
        for directory in sorted(inbox.iterdir())
        if directory.is_dir()
        for item in sorted(directory.iterdir())
        if _is_image(item)
    ]
    return photos


def _clear_queue(inbox: Path) -> None:
    """Убирает разобранные снимки из очереди."""
    for directory in inbox.iterdir():
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            if _is_image(item):
                item.unlink()


def _is_image(path: Path) -> bool:
    """Похож ли файл на снимок."""
    found = path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    return found
