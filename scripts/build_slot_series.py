"""Раскладывает снимки каждого вида работ в серию 20-минутных слотов одного дня.

Новая модель демонстрации: каждому виду работ отводится один день, следующий вид
начинается на сутки позже — обычная лестница календарного плана. Внутри дня идёт
короткая смена, снимок приходит раз в двадцать минут.

В серию берётся одна сцена — опорный кадр и дорисованные из него варианты, потому что
движение техники можно проследить только с одной точки съёмки. Время назначается
с шагом в двадцать минут и пишется в EXIF.

Рядом пишется сжатый календарный план `calendar_plan_shift.json`: семь пунктов по одному
дню подряд. Полный план проекта на 294 дня и исходные наборы снимков не трогаются.
"""

import csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prepare_demo_photos import build_exif  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PLAN_PATH = Path("config/calendar_plan_new.json")
ORIGINAL_DIR = Path("data/photos_v2")

GENERATED_DIR = Path("data/photos_generated")
VARIANT_SEPARATOR = "-"
OUTPUT_DIR = Path("data/photos_slots")
MANIFEST_JSON = OUTPUT_DIR / "manifest.json"
MANIFEST_CSV = OUTPUT_DIR / "manifest.csv"
SHIFT_PLAN_PATH = Path("config/calendar_plan_shift.json")
SHIFT_START_HOUR = 9
SLOT_MINUTES = 20
JPEG_QUALITY = 92
FILE_TIME_FORMAT = "%Y-%m-%d_%H-%M"
RECORD_TIME_FORMAT = "%Y-%m-%d %H:%M"
CSV_COLUMNS = ("file", "work_id", "work_name", "captured_at", "slot", "source")
STAGES_KEY = "stages"
WORK_ID_KEY = "work_id"
FULL_NAME_KEY = "full_name"
PHOTOS_KEY = "photos"
CAPTURED_AT_KEY = "captured_at"
DAY_FORMAT = "%Y-%m-%d"


def load_plan() -> dict[str, object]:
    """Читает календарный план проекта."""
    payload = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    return payload


def collect_frames(work_id: str) -> list[Path]:
    """Собирает серию одного вида работ: опорный кадр и дорисованные из него варианты.

    Смена — это одна точка съёмки, поэтому в серию идут только кадры одной сцены.
    Прочие исходные снимки этапа сняты на других площадках и в серию не годятся:
    сравнивать по ним движение техники нечего.

    Фасадный этап идёт по той же логике — одна сцена, — но область здания на его кадрах
    берётся не из детекции, а из разметки камеры: на дорисованных кадрах детектор зданий
    выбирает соседний готовый дом вместо строящегося.
    """
    variants = sorted((GENERATED_DIR / work_id).glob("*-[0-9][0-9].jpg"))
    if not variants:
        return []
    anchor_stem = variants[0].stem.rsplit(VARIANT_SEPARATOR, 1)[0]
    anchor = ORIGINAL_DIR / work_id / f"{anchor_stem}.jpg"
    frames = [anchor] + variants if anchor.exists() else list(variants)
    return frames


def shift_date(plan: dict[str, object], order: int) -> str:
    """День смены: работы идут подряд, каждая следующая на сутки позже."""
    opening = datetime.strptime(str(plan["start"]), DAY_FORMAT)
    day = opening + timedelta(days=order)
    return day.strftime(DAY_FORMAT)


def build_series(stage: dict[str, object], day: str) -> list[dict[str, str]]:
    """Назначает кадрам этапа время внутри смены с шагом в двадцать минут."""
    work_id = str(stage[WORK_ID_KEY])
    work_name = str(stage[FULL_NAME_KEY])
    start = datetime.strptime(f"{day} {SHIFT_START_HOUR:02d}:00", RECORD_TIME_FORMAT)
    records = []
    for slot, source in enumerate(collect_frames(work_id)):
        captured_at = start + timedelta(minutes=SLOT_MINUTES * slot)
        record = {
            "file": f"{work_id}_{captured_at.strftime(FILE_TIME_FORMAT)}.jpg",
            "work_id": work_id,
            "work_name": work_name,
            "captured_at": captured_at.strftime(RECORD_TIME_FORMAT),
            "slot": str(slot),
            "source": source.as_posix(),
        }
        records.append(record)
    return records


def save_frame(record: dict[str, str]) -> None:
    """Пересохраняет кадр в серию со временем съёмки в EXIF и в отметке файла."""
    captured_at = datetime.strptime(record["captured_at"], RECORD_TIME_FORMAT)
    target = OUTPUT_DIR / record["work_id"] / record["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(record["source"]).convert("RGB")
    note = f"Слот {record['slot']}, снимок серии смены"
    exif = build_exif(captured_at, record["work_name"], note)
    image.save(target, quality=JPEG_QUALITY, exif=exif)
    stamp = captured_at.timestamp()
    os.utime(target, (stamp, stamp))


def write_manifest(records: list[dict[str, str]]) -> None:
    """Пишет опись серии в JSON и CSV рядом со снимками."""
    MANIFEST_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with MANIFEST_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def write_shift_plan(plan: dict[str, object], days: dict[str, str]) -> None:
    """Пишет сжатый план: каждому виду работ по одному дню подряд."""
    stages = []
    for stage in plan[STAGES_KEY]:  # type: ignore[union-attr]
        day = days[str(stage[WORK_ID_KEY])]
        compressed = dict(stage)
        compressed["start"] = day
        compressed["finish"] = day
        compressed[PHOTOS_KEY] = []
        stages.append(compressed)
    shift_plan = dict(plan)
    shift_plan[STAGES_KEY] = stages
    shift_plan["start"] = stages[0]["start"]
    shift_plan["finish"] = stages[-1]["finish"]
    shift_plan["duration_days"] = len(stages)
    SHIFT_PLAN_PATH.write_text(json.dumps(shift_plan, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    """Собирает серии слотов и сжатый план, где работы идут день за днём."""
    plan = load_plan()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    days: dict[str, str] = {}
    for order, stage in enumerate(plan[STAGES_KEY]):  # type: ignore[union-attr, arg-type]
        day = shift_date(plan, order)
        days[str(stage[WORK_ID_KEY])] = day
        series = build_series(stage, day)  # type: ignore[arg-type]
        for record in series:
            save_frame(record)
        records.extend(series)
        logger.info("%s: слотов %d, смена %s", stage[WORK_ID_KEY], len(series), day)
    write_manifest(records)
    write_shift_plan(plan, days)
    logger.info("Серия собрана: кадров %d, план смен в %s", len(records), SHIFT_PLAN_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
