"""Чтение календарного плана проекта из файла конфигурации."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CalendarPlanReader:
    """Адаптер чтения календарного плана с этапами и их периодами.

    Путь приходит из контейнера, переменные окружения адаптер не читает.
    """

    def __init__(self, plan_path: Path) -> None:
        self._plan_path = plan_path

    def read_plan(self) -> dict[str, Any]:
        """Возвращает содержимое файла плана как разобранный JSON."""
        raw_text = self._plan_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        logger.info("Календарный план прочитан из %s", self._plan_path.name)
        return payload
