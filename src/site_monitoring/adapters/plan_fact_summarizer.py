"""Заключение языковой модели над план-фактом.

Требование заказчика: результирующий вывод над календарно-сетевым графиком,
и он прямо допускает для этого языковые модели. Модель получает уже посчитанные
числа и только излагает их словами — считать ей ничего не дают, иначе вывод
перестал бы быть проверяемым.
"""

import logging
from typing import Any

from .vlm_transport import VlmTransport

logger = logging.getLogger(__name__)

SCHEMA_NAME = "заключение_план_факт"
VERDICT_KEY = "вердикт"
SUMMARY_KEY = "заключение"
RISK_KEY = "на_что_смотреть"
VERDICTS = ("отставание", "соответствие", "опережение")

PROMPT_TEMPLATE = (
    "Ты пишешь короткое заключение для отчёта о ходе строительных работ.\n\n"
    "Посчитанные данные по объекту:\n{summary}\n\n"
    "По этапам:\n{stages}\n\n"
    "Напиши заключение в два-три предложения деловым языком, для руководителя стройки.\n"
    "Используй **только приведённые числа**, ничего не досчитывай и не придумывай.\n"
    "Назови, какие этапы тянут вниз и чем именно: не подтверждена работа техники "
    "либо часть отрезков не измерена.\n"
    "Отрезки вне контроля ИИ — это не вина подрядчика, а непросматриваемый участок: "
    "если их много, скажи, что данные требуют ручной проверки.\n"
    "В поле «на_что_смотреть» назови один этап, которым стоит заняться в первую очередь.\n"
    "Рассуждай кратко: ответ важнее размышлений."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        VERDICT_KEY: {"type": "string", "enum": list(VERDICTS)},
        SUMMARY_KEY: {"type": "string"},
        RISK_KEY: {"type": "string"},
    },
    "required": [VERDICT_KEY, SUMMARY_KEY, RISK_KEY],
}


class PlanFactSummarizer:
    """Адаптер обращения к модели за заключением над план-фактом."""

    def __init__(self, transport: VlmTransport) -> None:
        self._transport = transport

    def summarize(self, summary: str, stages: str) -> dict[str, str]:
        """Просит модель изложить посчитанный план-факт словами."""
        prompt = PROMPT_TEMPLATE.format(summary=summary, stages=stages)
        content = [{"type": "text", "text": prompt}]
        answer = self._transport.complete_json(content, RESPONSE_SCHEMA, SCHEMA_NAME)
        conclusion = {
            VERDICT_KEY: str(answer.get(VERDICT_KEY, "")),
            SUMMARY_KEY: str(answer.get(SUMMARY_KEY, "")),
            RISK_KEY: str(answer.get(RISK_KEY, "")),
        }
        logger.info("Заключение над план-фактом получено: %s", conclusion[VERDICT_KEY])
        return conclusion
