"""Готовит демонстрационный фотонабор: раскладывает снимки по этапам плана и
проставляет каждому дату съёмки в метаданных EXIF.

Источник — архив «Строительная_техника.zip» из материалов заказчика.
"""

import csv
import json
import os
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

PLAN_PATH = Path("config/calendar_plan_new.json")
ARCHIVE_PATH = Path("materials/Строительная_техника.zip")
ARCHIVE_PREFIX = "Строительная_техника"
OUTPUT_DIR = Path("data/photos_v2")
MANIFEST_JSON = OUTPUT_DIR / "manifest.json"
MANIFEST_CSV = OUTPUT_DIR / "manifest.csv"
JPEG_QUALITY = 92
EXIF_DATETIME = 0x0132
EXIF_DESCRIPTION = 0x010E
EXIF_SOFTWARE = 0x0131
EXIF_XP_COMMENT = 0x9C9C
EXIF_XP_SUBJECT = 0x9C9F
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME_DIGITIZED = 0x9004
EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"
INPUT_TIME_FORMAT = "%Y-%m-%d %H:%M"
SOFTWARE_TAG = "site-monitoring demo set"
CSV_COLUMNS = ("file", "work_id", "work_name", "captured_at", "source_frame", "note")


def encode_windows_text(value: str) -> bytes:
    """Кодирует текст в формат windows-тегов EXIF (UTF-16LE с нулём в конце)."""
    encoded = value.encode("utf-16-le") + b"\x00\x00"
    return encoded


def build_exif(captured_at: datetime, work_name: str, note: str) -> Image.Exif:
    """Готовит набор EXIF-тегов со временем съёмки и описанием кадра."""
    stamp = captured_at.strftime(EXIF_TIME_FORMAT)
    exif = Image.Exif()
    exif[EXIF_DATETIME] = stamp
    exif[EXIF_DESCRIPTION] = work_name.encode("utf-8").decode("latin-1", "ignore")
    exif[EXIF_SOFTWARE] = SOFTWARE_TAG
    exif[EXIF_XP_SUBJECT] = encode_windows_text(work_name)
    exif[EXIF_XP_COMMENT] = encode_windows_text(note)
    sub_ifd = exif.get_ifd(EXIF_IFD)
    sub_ifd[EXIF_DATETIME_ORIGINAL] = stamp
    sub_ifd[EXIF_DATETIME_DIGITIZED] = stamp
    return exif


def save_frame(raw: bytes, target: Path, captured_at: datetime, work_name: str, note: str) -> None:
    """Сохраняет кадр в JPEG с датой съёмки в EXIF и в отметке времени файла."""
    image = Image.open(BytesIO(raw)).convert("RGB")
    exif = build_exif(captured_at, work_name, note)
    image.save(target, quality=JPEG_QUALITY, exif=exif)
    stamp = captured_at.timestamp()
    os.utime(target, (stamp, stamp))


def build_records(plan: dict[str, object]) -> list[dict[str, str]]:
    """Разворачивает этапы плана в плоский список кадров с их атрибутами."""
    records: list[dict[str, str]] = []
    for stage in plan["stages"]:  # type: ignore[index]
        for photo in stage["photos"]:
            frame = photo["frame"]
            captured_at = photo["captured_at"]
            day = captured_at.split(" ")[0]
            record = {
                "file": f"{stage['work_id']}_{day}_frame{frame}.jpg",
                "work_id": stage["work_id"],
                "work_name": stage["full_name"],
                "short_name": stage["short_name"],
                "captured_at": captured_at,
                "source_frame": f"Screenshot_{frame}.png",
                "note": photo["note"],
            }
            records.append(record)
    return records


def write_manifest(records: list[dict[str, str]]) -> None:
    """Пишет опись фотонабора в JSON и CSV рядом со снимками."""
    MANIFEST_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with MANIFEST_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    """Собирает фотонабор демонстрации по календарному плану."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    records = build_records(plan)
    archive = zipfile.ZipFile(ARCHIVE_PATH)
    for record in records:
        folder = OUTPUT_DIR / record["work_id"]
        folder.mkdir(parents=True, exist_ok=True)
        raw = archive.read(f"{ARCHIVE_PREFIX}/{record['source_frame']}")
        captured_at = datetime.strptime(record["captured_at"], INPUT_TIME_FORMAT)
        save_frame(raw, folder / record["file"], captured_at, record["short_name"], record["note"])
    write_manifest(records)
    print(f"Подготовлено снимков: {len(records)}; опись: {MANIFEST_CSV}")


if __name__ == "__main__":
    main()
