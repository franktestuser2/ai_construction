"""Готовит набор для загрузки в сервис: календарный план и снимки с датами.

Набор нужен, чтобы сервис можно было проверить по-настоящему: пользователь
загружает план таблицей и все снимки разом, а сервис сам разносит их по этапам
по времени съёмки из метаданных. Поэтому у каждого снимка время в EXIF стоит
внутри периода своего этапа.

Собирается из готовой серии смен: план берётся сжатый, по дню на вид работ.
"""

import json
import logging
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_calendar_plan import build_package_parts, build_sheet  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PLAN_PATH = Path("config/calendar_plan_shift.json")
PHOTOS_PATH = Path("data/photos_slots")
OUTPUT_DIR = Path("data/sample")
PLAN_FILE = OUTPUT_DIR / "Календарный_план.xlsx"
PHOTOS_DIR = OUTPUT_DIR / "photos"
PHOTOS_ARCHIVE = OUTPUT_DIR / "Снимки_с_камер.zip"
STAGES_KEY = "stages"
DATE_FORMAT = "%d.%m.%Y"
ISO_FORMAT = "%Y-%m-%d"


def format_date(value: str) -> str:
    """Переводит дату плана в российскую запись."""
    parsed = datetime.strptime(value, ISO_FORMAT)
    return parsed.strftime(DATE_FORMAT)


def write_plan(stages: list[dict[str, object]]) -> None:
    """Пишет календарный план книгой Excel."""
    rows = [
        (str(stage["full_name"]), format_date(str(stage["start"])), format_date(str(stage["finish"])))
        for stage in stages
    ]
    parts = build_package_parts(build_sheet(rows))
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(PLAN_FILE, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    logger.info("План записан: %s, этапов %d", PLAN_FILE, len(rows))


def collect_photos() -> int:
    """Складывает снимки всех этапов в одну папку и архив, сохраняя метаданные."""
    if PHOTOS_DIR.exists():
        shutil.rmtree(PHOTOS_DIR)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    sources = sorted(PHOTOS_PATH.glob("*/*.jpg"))
    for source in sources:
        shutil.copy2(source, PHOTOS_DIR / source.name)
    with zipfile.ZipFile(PHOTOS_ARCHIVE, "w", zipfile.ZIP_DEFLATED) as archive:
        for photo in sorted(PHOTOS_DIR.iterdir()):
            archive.write(photo, photo.name)
    logger.info("Снимки собраны: %s, файлов %d", PHOTOS_DIR, len(sources))
    return len(sources)


def main() -> int:
    """Собирает набор для загрузки в сервис."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    stages = plan[STAGES_KEY]
    write_plan(stages)  # type: ignore[arg-type]
    count = collect_photos()
    logger.info("Набор готов: план на %d этапов и %d снимков", len(stages), count)  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
