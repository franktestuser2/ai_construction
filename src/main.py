"""HTTP-вход сервиса контроля строительных площадок."""

import logging
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI

from config import Settings
from site_monitoring.container import build_dependencies

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_TITLE = "Контроль строительных площадок"
HEALTH_STATUS_OK = "ok"

settings = Settings()
dependencies = build_dependencies(settings)
app = FastAPI(title=APP_TITLE)


@app.get("/health")
def health() -> dict[str, str]:
    """Сообщает, что сервис поднят и конфигурация прочитана."""
    payload = {"status": HEALTH_STATUS_OK, "project_id": settings.project_id}
    return payload


@app.post("/assessments/day")
def assess_day(payload: dict[str, Any]) -> dict[str, Any]:
    """Выносит вердикт по одному дню плана на основе снимков за этот день."""
    assessment = dependencies.facade.assess_day(payload)
    response = asdict(assessment)
    return response
