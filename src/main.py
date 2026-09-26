"""HTTP-вход сервиса контроля строительных площадок.

Два режима работы. **Демонстрация** открывает готовый разбор из кеша мгновенно:
жюри видит отчёт сразу, не дожидаясь моделей. **Прогон** принимает календарный
план и снимки пользователя, считает их фоновой задачей и показывает прогресс —
разбор смены занимает минуты, и держать браузер в ожидании нельзя.
"""

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from config import Settings
from site_monitoring.adapters.plan_fact_cache import PlanFactCache
from site_monitoring.adapters.plan_fact_summarizer import PlanFactSummarizer
from site_monitoring.adapters.run_storage import RunStorage
from site_monitoring.adapters.shift_timeline_reader import ShiftTimelineReader
from site_monitoring.container import build_dependencies, build_vlm_transport
from site_monitoring.services.analysis_run import AnalysisRunService
from site_monitoring.services.plan_fact_report import build_report, describe_stages, describe_summary
from site_monitoring.uploaded_plan_pipeline import UploadedPlanPipeline
from web_pages import render_dashboard, render_index, render_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

APP_TITLE = "Контроль строительных площадок"
HEALTH_STATUS_OK = "ok"
DEMO_REPORT_PATH = Path("docs/demo_stand.html")
RUNS_PATH = Path("data/runs")
TIMELINES_PATH = Path("data/cache/shift_timelines.json")
SUMMARY_PATH = Path("data/cache/plan_fact_summary.json")
DASHBOARD_URL = "/dashboard"
NO_PLAN_MESSAGE = "Не приложен календарный план"
NO_PHOTOS_MESSAGE = "Не приложено ни одного снимка"
NO_DEMO_MESSAGE = "Демонстрационный отчёт не собран: запустите scripts/build_demo_stand.py"
NO_RUN_MESSAGE = "Прогон не найден"
NO_REPORT_MESSAGE = "Отчёт этого прогона ещё не готов"
NO_MODEL_MESSAGE = "Доступ к языковой модели не настроен"
RUN_URL_TEMPLATE = "/runs/{run_id}"
REDIRECT_CODE = 303

settings = Settings()
dependencies = build_dependencies(settings)
storage = RunStorage(RUNS_PATH)
timeline_reader = ShiftTimelineReader(TIMELINES_PATH)
summary_cache = PlanFactCache(SUMMARY_PATH)
app = FastAPI(title=APP_TITLE)


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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Отвечает на главный вопрос: идём ли мы по календарному графику."""
    report = _build_report()
    page = render_dashboard(report, summary_cache.read())
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
    for photo in photos:
        name = Path(photo.filename or "").name
        if name:
            storage.save_upload(storage.photos_dir(state.run_id) / name, await photo.read())
    state.plan_file = Path(plan.filename).name
    state.photo_count = len(photos)
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


def _build_report():
    """Считает план-факт по разобранным сменам из кеша."""
    titles = {
        work_id: work.full_name.split(" → ")[-1]
        for work_id, work in dependencies.works_by_id.items()
    }
    report = build_report(timeline_reader.read_timelines(), titles, settings.slots_per_shift)
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
