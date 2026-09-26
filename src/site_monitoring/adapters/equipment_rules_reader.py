"""Чтение файла правил «вид работ → требуемая техника»."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EquipmentRulesReader:
    """Адаптер чтения правил из файла конфигурации.

    Путь приходит из контейнера, переменные окружения адаптер не читает.
    """

    def __init__(self, rules_path: Path) -> None:
        self._rules_path = rules_path

    def read_rules(self) -> dict[str, Any]:
        """Возвращает содержимое файла правил как разобранный JSON."""
        raw_text = self._rules_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        logger.info("Правила техники прочитаны из %s", self._rules_path.name)
        return payload
