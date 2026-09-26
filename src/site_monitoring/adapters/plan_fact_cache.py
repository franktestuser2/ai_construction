"""Хранение заключения над план-фактом.

Заключение пишет языковая модель, и обращаться к ней на каждый показ страницы
незачем: текст меняется только вместе с числами. Поэтому он складывается в файл
и пересобирается по требованию.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PlanFactCache:
    """Адаптер чтения и записи заключения над план-фактом."""

    def __init__(self, cache_path: Path) -> None:
        self._cache_path = cache_path

    def read(self) -> dict[str, str] | None:
        """Возвращает сохранённое заключение, если оно есть."""
        if not self._cache_path.exists():
            return None
        payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in payload.items()}

    def write(self, conclusion: dict[str, str]) -> None:
        """Сохраняет заключение рядом с кешем прогона."""
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(conclusion, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Заключение над план-фактом сохранено")
