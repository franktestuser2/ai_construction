"""Собирает страницу с лентой слотов смены по каждому виду работ.

Страница самодостаточная: данные берутся из кеша прогона, сеть при открытии
не нужна. Каждый слот показан тремя полосками — техника, комплект, движение —
и синим прямоугольником, когда слот засчитан.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CACHE_PATH = Path("data/cache/shift_timelines.json")
PLAN_PATH = Path("config/calendar_plan_new.json")
OUTPUT_PATH = Path("docs/shift_timeline.html")
SLOTS_KEY = "slots"
STAGES_KEY = "stages"
WORK_ID_KEY = "work_id"
FULL_NAME_KEY = "full_name"
SLOT_MINUTES_KEY = "slot_minutes"
PLAN_DATE_KEY = "plan_date"
TIME_FORMAT = "%H:%M"
FIRST_SLOT_STRIPES = 2
FULL_STRIPES = 3

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Смены по слотам</title>
<style>
  :root {{
    --fg: #1a1a1a; --muted: #6b6b6b; --line: #d8d8d8; --bg: #ffffff;
    --equipment: #e8b800; --kit: #e87b00; --motion: #2fa84f; --counted: #1f6fd0;
    --empty: #ececec;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --fg: #ececec; --muted: #9a9a9a; --line: #3a3a3a; --bg: #161616; --empty: #2a2a2a;
    }}
  }}
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 24px 16px; background: var(--bg); color: var(--fg);
         font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }}
  .wrap {{ max-width: 1040px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .lead {{ color: var(--muted); margin: 0 0 24px; }}
  .work {{ border-top: 1px solid var(--line); padding: 18px 0; }}
  .work h2 {{ font-size: 16px; margin: 0 0 2px; font-weight: 600; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}
  .track {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .slot {{ width: 96px; }}
  .box {{ border: 2px solid transparent; border-radius: 6px; padding: 5px;
          background: var(--empty); }}
  .box.counted {{ border-color: var(--counted); background: color-mix(in srgb, var(--counted) 14%, transparent); }}
  .stripe {{ height: 10px; border-radius: 2px; margin-bottom: 4px; background: transparent;
             border: 1px dashed var(--line); }}
  .stripe:last-child {{ margin-bottom: 0; }}
  .stripe.on {{ border: none; }}
  .stripe.equipment.on {{ background: var(--equipment); }}
  .stripe.kit.on {{ background: var(--kit); }}
  .stripe.motion.on {{ background: var(--motion); }}
  .time {{ font-size: 12px; color: var(--muted); margin-top: 5px; text-align: center; }}
  .total {{ margin-top: 10px; font-size: 14px; }}
  .legend {{ display: flex; gap: 18px; flex-wrap: wrap; margin: 0 0 20px;
             font-size: 13px; color: var(--muted); }}
  .chip {{ display: inline-block; width: 22px; height: 8px; border-radius: 2px;
           margin-right: 6px; vertical-align: middle; }}
  .note {{ color: var(--muted); font-size: 13px; margin-top: 18px;
           border-top: 1px solid var(--line); padding-top: 14px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Смены по слотам</h1>
  <p class="lead">Снимок приходит раз в {slot_minutes} минут. Слот засчитывается, когда собраны
  три признака; у первого снимка смены предыдущего кадра нет, поэтому там хватает двух.</p>
  <div class="legend">
    <span><i class="chip" style="background: var(--equipment)"></i>техника на месте</span>
    <span><i class="chip" style="background: var(--kit)"></i>комплект собран за смену</span>
    <span><i class="chip" style="background: var(--motion)"></i>техника работала</span>
    <span><i class="chip" style="background: var(--counted)"></i>слот засчитан</span>
  </div>
  {works}
  <p class="note">{note}</p>
</div>
</body>
</html>
"""

WORK_TEMPLATE = """  <section class="work">
    <h2>{work_id} · {work_name}</h2>
    <div class="meta">смена {plan_date}</div>
    <div class="track">{slots}</div>
    <div class="total">{total}</div>
  </section>
"""

SLOT_TEMPLATE = """<div class="slot">
      <div class="box{counted}">
        <div class="stripe equipment{equipment}"></div>
        <div class="stripe kit{kit}"></div>
        <div class="stripe motion{motion}"></div>
      </div>
      <div class="time">{time}</div>
    </div>"""

NOTE = (
    "Серия каждой смены собрана из одной сцены: опорный снимок площадки и дорисованные "
    "из него кадры. Слоты без снимка показаны пустыми — это не отклонение, а отсутствие данных."
)


def load_work_names() -> dict[str, str]:
    """Читает названия работ из календарного плана."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    names = {str(stage[WORK_ID_KEY]): str(stage[FULL_NAME_KEY]) for stage in plan[STAGES_KEY]}
    return names


def is_counted(slot: dict[str, object]) -> bool:
    """Повторяет правило зачёта слота: три признака, у первого достаточно двух."""
    if slot["frame_id"] is None:
        return False
    stripes = [slot["has_equipment"], slot["has_kit"], slot["has_motion"]]
    required = FIRST_SLOT_STRIPES if slot["is_first"] else FULL_STRIPES
    counted = sum(1 for value in stripes[:required] if value) == required
    return counted


def render_slot(slot: dict[str, object]) -> str:
    """Рисует один слот: три полоски и рамку зачёта."""
    starts_at = datetime.fromisoformat(str(slot["starts_at"]))
    block = SLOT_TEMPLATE.format(
        counted=" counted" if is_counted(slot) else "",
        equipment=" on" if slot["has_equipment"] else "",
        kit=" on" if slot["has_kit"] else "",
        motion=" on" if slot["has_motion"] else "",
        time=starts_at.strftime(TIME_FORMAT),
    )
    return block


def render_work(timeline: dict[str, object], work_name: str) -> str:
    """Рисует ленту одной смены."""
    slots = timeline[SLOTS_KEY]
    counted = sum(1 for slot in slots if is_counted(slot))  # type: ignore[union-attr]
    minutes = counted * int(timeline[SLOT_MINUTES_KEY])
    planned = len(slots) * int(timeline[SLOT_MINUTES_KEY])  # type: ignore[arg-type]
    total = f"Засчитано {minutes} мин из {planned}: слотов {counted} из {len(slots)}"  # type: ignore[arg-type]
    block = WORK_TEMPLATE.format(
        work_id=timeline[WORK_ID_KEY],
        work_name=work_name,
        plan_date=timeline[PLAN_DATE_KEY],
        slots="".join(render_slot(slot) for slot in slots),  # type: ignore[union-attr]
        total=total,
    )
    return block


def main() -> int:
    """Собирает страницу из кеша прогона смен."""
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    names = load_work_names()
    works = "".join(
        render_work(timeline, names.get(work_id, work_id))
        for work_id, timeline in sorted(cache.items())
    )
    slot_minutes = next(iter(cache.values()))[SLOT_MINUTES_KEY]
    page = PAGE_TEMPLATE.format(works=works, note=NOTE, slot_minutes=slot_minutes)
    OUTPUT_PATH.write_text(page, encoding="utf-8")
    logger.info("Страница собрана: %s, смен %d", OUTPUT_PATH, len(cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
