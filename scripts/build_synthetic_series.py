"""Сборка синтетических серий снимков для проверки правил активности и комплекта.

Из одного реального кадра каждого вида работ делается смена из 24 слотов по
20 минут: техника переставляется, пропадает и простаивает по заданному сценарию.
Кадр собирается из чистого фона и вырезанной машины, поэтому следы вставок
не накапливаются.

Результат лежит отдельно от оригиналов, в data/synthetic, и сопровождается
манифестом с ожидаемым числом рабочих часов.
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Settings  # noqa: E402
from site_monitoring.adapters.equipment_detector import EquipmentDetector  # noqa: E402
from site_monitoring.adapters.frame_synthesizer import FrameSynthesizer  # noqa: E402
from site_monitoring.entity import SyntheticShift, SyntheticSlot  # noqa: E402
from site_monitoring.services.shift_scenario import (  # noqa: E402
    SCENARIO_FULL,
    SCENARIO_HALF,
    SCENARIO_KIT,
    SCENARIO_LEFT,
    SCENARIO_LUNCH,
    SCENARIO_WIND,
    SLOT_MINUTES,
    ShiftScenarioService,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PLAN_PATH = Path("config/calendar_plan_new.json")
PHOTOS_DIR = Path("data/photos_v2")
OUTPUT_DIR = Path("data/synthetic")
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
RANDOM_SEED = 20260922
SHAKE_PIXELS = 4
MARGIN_PIXELS = 12
MOVE_SPAN = (0.25, 0.55)
WALK_BAND = (1.2, 0.25)
JPEG_QUALITY = 92
SHIFT_START = "08:00"
CLOCK_FORMAT = "%Y-%m-%d %H:%M"
DAY_FORMAT = "%Y-%m-%d"
DAY_STEP_DAYS = 2
FIRST_DAY_OFFSET = 3
EXIF_DATETIME = 0x0132
EXIF_DESCRIPTION = 0x010E
EXIF_SOFTWARE = 0x0131
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"
SOFTWARE_TAG = "site-monitoring synthetic series"

SCENARIOS_WITH_KIT = (SCENARIO_FULL, SCENARIO_LUNCH, SCENARIO_HALF, SCENARIO_LEFT, SCENARIO_KIT, SCENARIO_WIND)
SCENARIOS_SOLO = (SCENARIO_FULL, SCENARIO_LUNCH, SCENARIO_HALF, SCENARIO_LEFT, SCENARIO_WIND)

SOURCES = (
    ("W01", "W01_2026-10-06_frame23.jpg", "Excavator", None),
    ("W02", "W02_2026-11-02_frame8.jpg", "Excavator", None),
    ("W03", "W03_2027-01-06_frame86.jpg", "Excavator", "Dump truck"),
    ("W04", "W04_2027-01-15_frame55.jpg", "Excavator", None),
    ("W05", "W05_2027-03-30_frame57.jpg", "Forklift Giraffe", "Excavator"),
    ("W06", "W06_2027-05-06_frame67.jpg", "Crane manipulator", None),
    ("W07", "W07_2027-07-15_frame1.jpg", "Excavator", None),
)


def read_plan() -> dict[str, dict[str, str]]:
    """Читает календарный план: названия этапов и даты их начала."""
    payload = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    stages = {item["work_id"]: {"name": item["short_name"], "start": item["start"]} for item in payload["stages"]}
    return stages


def build_exif(captured_at: datetime, title: str) -> Image.Exif:
    """Готовит EXIF со временем съёмки синтетического кадра."""
    stamp = captured_at.strftime(EXIF_TIME_FORMAT)
    exif = Image.Exif()
    exif[EXIF_DATETIME] = stamp
    exif[EXIF_DESCRIPTION] = title.encode("utf-8").decode("latin-1", "ignore")
    exif[EXIF_SOFTWARE] = SOFTWARE_TAG
    sub_ifd = exif.get_ifd(EXIF_IFD)
    sub_ifd[EXIF_DATETIME_ORIGINAL] = stamp
    return exif


def widest_box(detections: tuple, machine_type: str) -> tuple[float, float, float, float] | None:
    """Выбирает самую крупную рамку нужного класса: мелкие находки ненадёжны."""
    boxes: list[tuple[float, float, float, float]] = []
    for item in detections:
        if item.machine_type == machine_type:
            boxes.extend(item.boxes)
    if not boxes:
        return None
    widest = max(boxes, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))
    return widest


class DayPlates:
    """Заготовки одного дня: чистый фон с комплектом и без него плюс вырезанная машина."""

    def __init__(
        self,
        synthesizer: FrameSynthesizer,
        source: Image.Image,
        lead: tuple[float, float, float, float],
        kit: tuple[float, float, float, float] | None,
    ) -> None:
        self.origin = synthesizer.absolute_box(source, lead)
        self.kit_box = synthesizer.absolute_box(source, kit) if kit is not None else None
        self.machine = synthesizer.crop_machine(source, self.origin)
        self.with_kit = synthesizer.remove_machine(source, self.origin)
        without = self.with_kit if self.kit_box is None else synthesizer.remove_machine(self.with_kit, self.kit_box)
        self.without_kit = without


def render_slot(
    synthesizer: FrameSynthesizer,
    plates: DayPlates,
    slot: SyntheticSlot,
    lead_box: tuple[int, int, int, int],
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Рисует кадр слота и возвращает его вместе с новым положением ведущей машины."""
    next_box = lead_box
    if slot.machine_moves:
        offset = synthesizer.working_offset(lead_box, MOVE_SPAN)
        next_box = synthesizer.walk_box(lead_box, plates.origin, offset, WALK_BAND, plates.kit_box)
    base = plates.with_kit if slot.kit_present else plates.without_kit
    frame = base
    if slot.lead_present:
        frame = synthesizer.paste_machine(base, plates.machine, (next_box[0], next_box[1]))
    shaken = synthesizer.shake_and_crop(frame, slot.camera_shake)
    jittered = synthesizer.jitter_light(shaken)
    return jittered, next_box


def slot_record(slot: SyntheticSlot, name: str, captured_at: datetime) -> dict[str, object]:
    """Формирует строку манифеста по одному слоту."""
    record = {
        "index": slot.index,
        "file": name,
        "captured_at": captured_at.strftime(CLOCK_FORMAT),
        "outcome": slot.outcome.value,
        "lead_present": slot.lead_present,
        "kit_present": slot.kit_present,
        "machine_moves": slot.machine_moves,
    }
    return record


def build_day(
    synthesizer: FrameSynthesizer,
    shift: SyntheticShift,
    day: str,
    work_id: str,
    source: Image.Image,
    plates: DayPlates,
) -> dict[str, object]:
    """Собирает один синтетический день и возвращает его запись для манифеста."""
    target_dir = OUTPUT_DIR / work_id / shift.scenario
    target_dir.mkdir(parents=True, exist_ok=True)
    start = datetime.strptime(f"{day} {SHIFT_START}", CLOCK_FORMAT)
    lead_box = plates.origin
    records: list[dict[str, object]] = []
    for slot in shift.slots:
        frame, lead_box = render_slot(synthesizer, plates, slot, lead_box)
        captured_at = start + timedelta(minutes=SLOT_MINUTES * slot.index)
        name = f"SYN_{work_id}_{shift.scenario}_{day}_{slot.clock.replace(':', '')}.jpg"
        exif = build_exif(captured_at, shift.title)
        frame.save(target_dir / name, quality=JPEG_QUALITY, exif=exif)
        records.append(slot_record(slot, name, captured_at))
    day_record = {
        "work_id": work_id,
        "scenario": shift.scenario,
        "title": shift.title,
        "date": day,
        "expected_hours": shift.expected_hours,
        "slots": records,
    }
    return day_record


def build_work(
    work_id: str,
    frame_file: str,
    lead_type: str,
    kit_type: str | None,
    detector: EquipmentDetector,
    scenarios: ShiftScenarioService,
    stage: dict[str, str],
) -> dict[str, object]:
    """Собирает все сценарии одного вида работ из его реального кадра."""
    source_path = PHOTOS_DIR / work_id / frame_file
    detections = detector.detect(source_path)
    lead = widest_box(detections, lead_type)
    if lead is None:
        raise ValueError(f"На кадре {frame_file} не найдена ведущая машина {lead_type}")
    kit = widest_box(detections, kit_type) if kit_type else None
    source = Image.open(source_path).convert("RGB")
    synthesizer = FrameSynthesizer(RANDOM_SEED, SHAKE_PIXELS, MARGIN_PIXELS)
    plates = DayPlates(synthesizer, source, lead, kit)
    names = SCENARIOS_WITH_KIT if kit is not None else SCENARIOS_SOLO
    start = datetime.strptime(stage["start"], DAY_FORMAT)
    days = []
    for number, scenario in enumerate(names):
        shift = scenarios.build(scenario)
        day = (start + timedelta(days=FIRST_DAY_OFFSET + number * DAY_STEP_DAYS)).strftime(DAY_FORMAT)
        days.append(build_day(synthesizer, shift, day, work_id, source, plates))
    logger.info("%s %s: сценариев %d, ведущая машина %s", work_id, stage["name"], len(days), lead_type)
    work_record = {
        "work_id": work_id,
        "work_name": stage["name"],
        "source_frame": frame_file,
        "lead_machine": lead_type,
        "kit_machine": kit_type if kit is not None else None,
        "days": days,
    }
    return work_record


def main() -> None:
    """Собирает синтетические серии по всем видам работ и пишет общий манифест."""
    stages = read_plan()
    settings = Settings()
    detector = EquipmentDetector(settings.detector_weights_path, settings.detector_confidence_threshold)
    scenarios = ShiftScenarioService()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    works = []
    for work_id, frame_file, lead_type, kit_type in SOURCES:
        record = build_work(work_id, frame_file, lead_type, kit_type, detector, scenarios, stages[work_id])
        works.append(record)
    manifest = {"works": works}
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("Готово: видов работ %d, манифест %s", len(works), MANIFEST_PATH)


if __name__ == "__main__":
    main()
