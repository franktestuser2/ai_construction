"""HTTP-вход сервиса контроля строительных площадок.

Два режима работы. **Демонстрация** открывает готовый разбор из кеша мгновенно:
жюри видит отчёт сразу, не дожидаясь моделей. **Прогон** принимает календарный
план и снимки пользователя, считает их фоновой задачей и показывает прогресс —
разбор смены занимает минуты, и держать браузер в ожидании нельзя.
"""

import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from camera_routes import build_camera_router
from camera_watch.container import build_camera_watch
from config import Settings
from ingest_routes import build_ingest_router
from site_monitoring.adapters.plan_fact_cache import PlanFactCache
from site_monitoring.adapters.plan_fact_summarizer import PlanFactSummarizer
from site_monitoring.adapters.run_storage import STATUS_DONE, RunStorage
from site_monitoring.adapters.shift_timeline_reader import ShiftTimelineReader
from site_monitoring.container import build_dependencies, build_vlm_transport
from site_monitoring.services.analysis_run import AnalysisRunService
from site_monitoring.services.plan_fact_report import build_report, describe_stages, describe_summary
from site_monitoring.uploaded_plan_pipeline import UploadedPlanPipeline
from report_stand import StandBuilder, StandSources
from web_pages import render_dashboard, render_index, render_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

APP_TITLE = "Контроль строительных площадок"
HEALTH_STATUS_OK = "ok"
DEMO_DIR = Path("docs/stand")
DEMO_REPORT_PATH = DEMO_DIR / "index.html"
DEMO_PHOTOS_DIR = DEMO_DIR / "photos"
RUNS_PATH = Path("data/runs")
TIMELINES_PATH = Path("data/cache/shift_timelines.json")
SUMMARY_PATH = Path("data/cache/plan_fact_summary.json")
SAMPLE_PLAN_PATH = Path("data/sample/Календарный_план.xlsx")
SAMPLE_PHOTOS_PATH = Path("data/sample/Снимки_с_камер.zip")
DASHBOARD_URL = "/dashboard"
NO_PLAN_MESSAGE = "Не приложен календарный план"
NO_PHOTOS_MESSAGE = "Не приложено ни одного снимка: нужны изображения либо архив с ними"
NO_DEMO_MESSAGE = "Демонстрационный отчёт не собран: запустите scripts/build_demo_stand.py"
NO_RUN_MESSAGE = "Прогон не найден"
NO_REPORT_MESSAGE = "Отчёт этого прогона ещё не готов"
NO_MODEL_MESSAGE = "Доступ к языковой модели не настроен"
NO_SAMPLE_MESSAGE = "Демонстрационный набор не собран: запустите scripts/build_sample_package.py"
NO_PHOTO_MESSAGE = "Снимок не найден"
STAND_DIR_NAME = "stand"
STAND_INDEX_NAME = "index.html"
STAND_PHOTOS_NAME = "photos"
OBSERVATIONS_NAME = "observations.json"
RUN_PHOTO_URL_TEMPLATE = "/runs/{run_id}/photos/"
RUN_URL_TEMPLATE = "/runs/{run_id}"
REDIRECT_CODE = 303
GZIP_MIN_BYTES = 800
# На рисованных кадрах симулятора детектор техники честно не находит ничего: он обучен
# на фотографиях. Путь «камера → основной сервис» это не ломает, но предупредить надо.
SIMULATOR_NOTE = (
    "Кадры демонстрационных камер нарисованы генератором сцен из репозитория "
    "video-monitoring. Детектор техники обучен на фотографиях и на рисованной сцене "
    "находок не даёт — разбор пройдёт, но техники в нём не будет. Проверка охраны "
    "труда по этим кадрам работает: она сравнивает кадр с текстовыми описаниями."
)

settings = Settings()
dependencies = build_dependencies(settings)
storage = RunStorage(RUNS_PATH)
timeline_reader = ShiftTimelineReader(TIMELINES_PATH)
summary_cache = PlanFactCache(SUMMARY_PATH)
watch = build_camera_watch(settings)


def _capture_loop() -> None:
    """Снимает камеры по расписанию и передаёт снятое основному сервису."""
    while True:
        time.sleep(settings.capture_tick_seconds)
        try:
            outcomes = watch.capture_due(datetime.now())
        except OSError:
            logger.exception("Съёмка по расписанию сорвалась")
            continue
        for camera_id in {item.frame.camera_id for item in outcomes}:
            sent, note = watch.send_to_main_service(camera_id)
            logger.info("Камера %s снята по расписанию: %s", camera_id, note)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Поднимает съёмку по расписанию вместе с сервисом."""
    if settings.capture_enabled:
        worker = threading.Thread(target=_capture_loop, daemon=True)
        worker.start()
        logger.info("Съёмка по расписанию запущена, шаг %d с", settings.capture_tick_seconds)
    else:
        logger.info("Съёмка по расписанию выключена настройкой")
    yield


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
# Страницы уходят текстом и сжимаются в разы: канал до пользователя может быть узким.
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES)
if DEMO_PHOTOS_DIR.exists():
    # Снимки стенда отдаются файлами, а не вшиты в страницу: так она грузится быстро.
    app.mount("/demo/photos", StaticFiles(directory=DEMO_PHOTOS_DIR), name="demo-photos")


def _start_run_from_frames(plan: bytes, plan_name: str, photos: list[tuple[str, bytes]]) -> str:
    """Заводит прогон по снимкам, пришедшим с камер, и пускает разбор в фоне."""
    state = storage.create()
    storage.save_upload(storage.plan_dir(state.run_id) / plan_name, plan)
    saved = sum(storage.save_photos(state.run_id, name, content) for name, content in photos)
    state.plan_file = plan_name
    state.photo_count = saved
    storage.save(state)
    worker = threading.Thread(target=_execute_run, args=(state.run_id,), daemon=True)
    worker.start()
    return state.run_id


def _known_work_titles() -> dict[str, str]:
    """Виды работ, у которых заданы правила по технике."""
    titles = {
        work_id: work.full_name.split(" → ")[-1]
        for work_id, work in dependencies.works_by_id.items()
        if work_id in dependencies.rules_by_work
    }
    return titles


app.include_router(build_camera_router(watch))
app.include_router(
    build_ingest_router(settings.camera_inbox_path, _start_run_from_frames, _known_work_titles(), SIMULATOR_NOTE)
)


@app.get("/health")
def health() -> dict[str, str]:
    """Сообщает, что сервис поднят и конфигурация прочитана."""
    payload = {"status": HEALTH_STATUS_OK, "project_id": settings.project_id}
    return payload


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Главная страница: демонстрация, загрузка своих данных и список прогонов."""
    page = render_index(storage.list_runs(), DEMO_REPORT_PATH.exists())
    return HTMLResponse(page)


@app.get("/demo", response_class=HTMLResponse)
def demo() -> FileResponse:
    """Отдаёт готовый демонстрационный отчёт из кеша."""
    if not DEMO_REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail=NO_DEMO_MESSAGE)
    response = FileResponse(DEMO_REPORT_PATH)
    return response


@app.get("/sample/plan")
def sample_plan() -> FileResponse:
    """Отдаёт демонстрационный календарный план книгой Excel."""
    if not SAMPLE_PLAN_PATH.exists():
        raise HTTPException(status_code=404, detail=NO_SAMPLE_MESSAGE)
    return FileResponse(SAMPLE_PLAN_PATH, filename=SAMPLE_PLAN_PATH.name)


@app.get("/sample/photos")
def sample_photos() -> FileResponse:
    """Отдаёт демонстрационные снимки архивом: у каждого дата съёмки в метаданных."""
    if not SAMPLE_PHOTOS_PATH.exists():
        raise HTTPException(status_code=404, detail=NO_SAMPLE_MESSAGE)
    return FileResponse(SAMPLE_PHOTOS_PATH, filename=SAMPLE_PHOTOS_PATH.name)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Отвечает на главный вопрос: идём ли мы по календарному графику."""
    timelines = timeline_reader.read_timelines()
    report = _build_report(timelines)
    foreign = sum(timeline.foreign_slots for timeline in timelines.values())
    page = render_dashboard(report, summary_cache.read(), foreign)
    return HTMLResponse(page)


@app.get("/dashboard/summary")
def dashboard_summary() -> RedirectResponse:
    """Просит языковую модель изложить посчитанный план-факт словами."""
    report = _build_report()
    transport = build_vlm_transport(settings)
    if transport is None:
        raise HTTPException(status_code=503, detail=NO_MODEL_MESSAGE)
    summarizer = PlanFactSummarizer(transport)
    conclusion = summarizer.summarize(
        describe_summary(report, settings.slot_minutes),
        describe_stages(report),
    )
    summary_cache.write(conclusion)
    return RedirectResponse(DASHBOARD_URL, status_code=REDIRECT_CODE)


@app.post("/runs")
async def create_run(
    background: BackgroundTasks,
    plan: UploadFile = File(...),
    photos: list[UploadFile] = File(...),
) -> RedirectResponse:
    """Принимает календарный план и снимки, ставит разбор в очередь."""
    if plan.filename is None:
        raise HTTPException(status_code=400, detail=NO_PLAN_MESSAGE)
    if not photos:
        raise HTTPException(status_code=400, detail=NO_PHOTOS_MESSAGE)
    state = storage.create()
    storage.save_upload(storage.plan_dir(state.run_id) / Path(plan.filename).name, await plan.read())
    saved = 0
    for photo in photos:
        name = Path(photo.filename or "").name
        if name:
            saved += storage.save_photos(state.run_id, name, await photo.read())
    if saved == 0:
        storage.remove(state.run_id)
        raise HTTPException(status_code=400, detail=NO_PHOTOS_MESSAGE)
    state.plan_file = Path(plan.filename).name
    state.photo_count = saved
    storage.save(state)
    background.add_task(_execute_run, state.run_id)
    return RedirectResponse(RUN_URL_TEMPLATE.format(run_id=state.run_id), status_code=REDIRECT_CODE)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def show_run(run_id: str) -> HTMLResponse:
    """Страница прогона: прогресс либо готовый итог."""
    state = storage.load(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=NO_RUN_MESSAGE)
    page = render_run(state)
    return HTMLResponse(page)


@app.get("/runs/{run_id}/dashboard", response_class=HTMLResponse)
def run_dashboard(run_id: str) -> HTMLResponse:
    """Сводка план-факта по данным конкретного прогона."""
    state = storage.load(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=NO_RUN_MESSAGE)
    reader = ShiftTimelineReader(storage.timelines_path(run_id))
    titles = {str(work["work_id"]): str(work["title"]).split(" → ")[-1] for work in state.works}
    timelines = reader.read_timelines()
    report = build_report(timelines, titles, settings.slots_per_shift)
    foreign = sum(timeline.foreign_slots for timeline in timelines.values())
    page = render_dashboard(report, None, foreign)
    return HTMLResponse(page)


@app.get("/runs/{run_id}/report", response_class=HTMLResponse)
def run_report(run_id: str) -> FileResponse:
    """Страница смен по слотам, собранная по данным этого прогона."""
    target = storage.directory(run_id) / STAND_DIR_NAME / STAND_INDEX_NAME
    if not target.exists():
        raise HTTPException(status_code=404, detail=NO_REPORT_MESSAGE)
    return FileResponse(target)


@app.get("/runs/{run_id}/photos/{name}")
def run_photo(run_id: str, name: str) -> FileResponse:
    """Снимок со страницы прогона: имя берётся без пути, наружу выйти нельзя."""
    target = storage.directory(run_id) / STAND_DIR_NAME / STAND_PHOTOS_NAME / Path(name).name
    if not target.exists():
        raise HTTPException(status_code=404, detail=NO_PHOTO_MESSAGE)
    return FileResponse(target)


@app.get("/runs/{run_id}/state")
def run_state(run_id: str) -> dict[str, Any]:
    """Состояние прогона для обновления страницы без перезагрузки."""
    state = storage.load(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=NO_RUN_MESSAGE)
    payload = asdict(state) | {"percent": state.percent}
    return payload


@app.post("/assessments/day")
def assess_day(payload: dict[str, Any]) -> dict[str, Any]:
    """Выносит вердикт по одному дню плана на основе готовых наблюдений."""
    assessment = dependencies.facade.assess_day(payload)
    response = asdict(assessment)
    return response


def _build_report(timelines=None):
    """Считает план-факт по разобранным сменам из кеша."""
    titles = {
        work_id: work.full_name.split(" → ")[-1]
        for work_id, work in dependencies.works_by_id.items()
    }
    source = timeline_reader.read_timelines() if timelines is None else timelines
    report = build_report(source, titles, settings.slots_per_shift)
    return report


def _execute_run(run_id: str) -> None:
    """Выполняет разбор загруженных данных в фоне."""
    pipeline = UploadedPlanPipeline(settings, storage.plan_dir(run_id))
    # Сопоставлять этап плана можно только с той работой, у которой заданы правила
    # по технике: справочник работ шире правил, и без отбора этап уходил бы в пустоту.
    known_titles = {
        work_id: work.full_name
        for work_id, work in dependencies.works_by_id.items()
        if work_id in dependencies.rules_by_work
    }
    service = AnalysisRunService(storage=storage, pipeline=pipeline, known_titles=known_titles)
    service.execute(run_id)
    _build_run_stand(run_id)


def _build_run_stand(run_id: str) -> None:
    """Собирает страницу смен по данным прогона: ту же, что и у демонстрации."""
    state = storage.load(run_id)
    if state is None or state.status != STATUS_DONE:
        return
    titles = {str(work["work_id"]): str(work["title"]) for work in state.works}
    sources = StandSources(
        timelines_path=storage.timelines_path(run_id),
        observations_path=storage.plan_dir(run_id) / OBSERVATIONS_NAME,
        photos_dir=storage.photos_dir(run_id),
        titles=titles,
        output_dir=storage.directory(run_id) / STAND_DIR_NAME,
        photo_url_prefix=RUN_PHOTO_URL_TEMPLATE.format(run_id=run_id),
        photos_by_work=False,
    )
    StandBuilder(sources).build()
