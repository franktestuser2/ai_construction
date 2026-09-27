"""Приёмная основного сервиса: сюда контур наблюдения отдаёт снятые кадры.

Камеры не знают ни о календарном плане, ни о каталогах разбора: они присылают снимки
по HTTP, а сервис сам решает, когда и с каким планом их разбирать.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from ingest_pages import render_ingest

logger = logging.getLogger(__name__)

INGEST_URL = "/ingest"
RUN_URL_TEMPLATE = "/runs/{run_id}"
PLAN_FILE_NAME = "План_по_снимкам_с_камер.csv"
PLAN_HEADER = "Вид работ;Дата начала;Дата окончания"
PLAN_DATE_FORMAT = "%d.%m.%Y"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
REDIRECT_CODE = 303
EMPTY_QUEUE_MESSAGE = "В очереди нет снимков"
UNKNOWN_WORK_MESSAGE = "Такого вида работ нет в справочнике"
ACCEPTED_KEY = "accepted"
NOTHING = 0
StartRun = Callable[[bytes, str, list[tuple[str, bytes]]], str]


def build_ingest_router(inbox: Path, start_run: StartRun, works: dict[str, str], note: str) -> APIRouter:
    """Собирает маршруты приёмной вокруг способа запускать разбор."""
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
        """Страница приёмной: очередь и запуск разбора."""
        page = render_ingest(_queue(inbox), works, note)
        return HTMLResponse(page)

    @router.post("/ingest/run")
    def run_queue(work_id: str = Form(...)) -> RedirectResponse:
        """Пускает накопленные кадры в разбор с планом на сегодняшний день."""
        photos = _collect_photos(inbox)
        if not photos:
            raise HTTPException(status_code=400, detail=EMPTY_QUEUE_MESSAGE)
        title = works.get(work_id)
        if title is None:
            raise HTTPException(status_code=400, detail=UNKNOWN_WORK_MESSAGE)
        plan = _build_plan(title, date.today())
        run_id = start_run(plan, PLAN_FILE_NAME, photos)
        _clear_queue(inbox)
        return RedirectResponse(RUN_URL_TEMPLATE.format(run_id=run_id), status_code=REDIRECT_CODE)

    return router


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


def _build_plan(title: str, day: date) -> bytes:
    """Составляет календарный план на один день под снятое камерами."""
    stamp = day.strftime(PLAN_DATE_FORMAT)
    text = f"{PLAN_HEADER}\n{title};{stamp};{stamp}\n"
    return text.encode("utf-8")


def _is_image(path: Path) -> bool:
    """Похож ли файл на снимок."""
    found = path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    return found
