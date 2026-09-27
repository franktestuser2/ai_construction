"""Готовит календарный план объекта, на котором стоят камеры.

Камеры снимают сегодня, а план демонстрационного проекта расписан на следующий год, и
сегодняшнего дня в нём нет вовсе. Разбирать снятое было бы не с чем: сервис ищет в плане
этап, который приходится на дату съёмки.

Поэтому план объекта составляется от сегодняшнего дня: семь этапов подряд, по три дня на
каждый, и сегодня приходится на монолит надземной части — то, что и видно на камерах.
Пересобирается одной командой, когда даты уезжают.

Запуск: python scripts/build_site_plan.py
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SOURCE_PLAN = Path("config/calendar_plan_shift.json")
TARGET = Path("config/План_объекта.csv")
STAGES_KEY = "stages"
DAYS_PER_STAGE = 3
# Сегодняшний день приходится на шестой этап: монолит надземной части. Именно его
# видно на подключённых камерах, и на нём есть чему работать.
TODAY_STAGE_INDEX = 5
HEADER = "Вид работ;Дата начала;Дата окончания"
DATE_FORMAT = "%d.%m.%Y"


def build_rows(today: date) -> list[str]:
    """Собирает строки плана так, чтобы сегодня попало в нужный этап."""
    plan = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
    start = today - timedelta(days=TODAY_STAGE_INDEX * DAYS_PER_STAGE + 1)
    rows = []
    for number, stage in enumerate(plan[STAGES_KEY]):
        begins = start + timedelta(days=number * DAYS_PER_STAGE)
        ends = begins + timedelta(days=DAYS_PER_STAGE - 1)
        title = str(stage["full_name"]).split(" → ")[-1]
        rows.append(f"{title};{begins.strftime(DATE_FORMAT)};{ends.strftime(DATE_FORMAT)}")
    return rows


def main() -> int:
    """Пишет план объекта в файл."""
    today = date.today()
    rows = build_rows(today)
    TARGET.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    logger.info("План объекта записан: %s, этапов %d", TARGET, len(rows))
    for row in rows:
        logger.info("  %s", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
