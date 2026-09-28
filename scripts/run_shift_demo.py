"""Прогон смены по слотам: снимки серии → признаки → лента слотов.

Каждый снимок разбирается моделями, соседние пары сравниваются между собой.
В кеш кладутся **сырые наблюдения**, а не готовая лента: правила зачёта слота
меняются чаще, чем данные, и пересчёт по кешу не должен стоить обращений к моделям.

Флаг `--cached` пересобирает ленты из кеша, ничего не спрашивая у моделей.
"""

import json
import logging
import sys
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Settings  # noqa: E402
from site_monitoring.container import build_dependencies  # noqa: E402
from site_monitoring.entity import (  # noqa: E402
    EquipmentSource,
    EquipmentStatus,
    FacadeReadiness,
    FrameObservation,
    MotionObservation,
    ObservedEquipment,
    PlanEntry,
    ShiftFrames,
    ShiftTimeline,
)
from site_monitoring.adapters.scene_comparator import SceneComparator  # noqa: E402
from site_monitoring.services.shift_timeline import ShiftTimelineService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MANIFEST_PATH = Path("data/photos_slots/manifest.json")
# Смены идут по сжатому плану: один день на вид работ, работы друг за другом.
SHIFT_PLAN_PATH = Path("config/calendar_plan_shift.json")
OBSERVATIONS_CACHE = Path("data/cache/shift_observations.json")
TIMELINES_CACHE = Path("data/cache/shift_timelines.json")
CACHED_FLAG = "--cached"
WORK_ID_KEY = "work_id"
FILE_KEY = "file"
CAPTURED_AT_KEY = "captured_at"
STRIPE_MARKS = ("Т", "К", "Д")
COUNTED_MARK = "■"
MISSING_MARK = "·"
NO_FRAME_TITLE = "нет снимка"
OBSERVATIONS_KEY = "observations"
MOTIONS_KEY = "motions"
PLAN_DATE_KEY = "plan_date"
FRAME_IDS_KEY = "frame_ids"
FACADE_KEY = "facade"
SCENE_KEY = "scene_mismatch"
FRAMES_PAYLOAD_KEY = "frames"
IMAGE_PATH_KEY = "image_path"


def save_observations(cache: dict[str, object]) -> None:
    """Пишет сырые наблюдения в кеш, приводя даты к строкам."""
    OBSERVATIONS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cache, ensure_ascii=False, indent=2, default=str)
    OBSERVATIONS_CACHE.write_text(payload, encoding="utf-8")


def load_manifest() -> list[dict[str, str]]:
    """Читает опись серии снимков."""
    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return records


def build_payload(records: list[dict[str, str]], work_id: str) -> dict[str, object]:
    """Собирает вход смены: снимки одного вида работ по порядку времени."""
    selected = [record for record in records if record[WORK_ID_KEY] == work_id]
    frames = [
        {
            "frame_id": record[FILE_KEY],
            "image_path": f"data/photos_slots/{work_id}/{record[FILE_KEY]}",
        }
        for record in selected
    ]
    observation_date = selected[0][CAPTURED_AT_KEY].split(" ")[0]
    payload = {"observation_date": observation_date, "frames": frames}
    return payload


def print_timeline(timeline: ShiftTimeline) -> None:
    """Печатает ленту слотов: полоски и засчитанные отрезки."""
    print(f"\nСмена {timeline.plan_date}, работа {timeline.work_id}")
    for slot in timeline.slots:
        stripes = [slot.has_equipment, slot.has_kit, slot.has_motion]
        marks = " ".join(
            mark if present else MISSING_MARK for mark, present in zip(STRIPE_MARKS, stripes)
        )
        counted = COUNTED_MARK if slot.is_counted else " "
        title = slot.frame_id or NO_FRAME_TITLE
        print(f"  {slot.starts_at:%H:%M}  {marks}  {counted}  {title}")
    print(
        f"  засчитано {timeline.counted_minutes} мин из {timeline.planned_minutes}, "
        f"слотов {timeline.counted_slots} из {len(timeline.slots)}"
    )


def observe_work(dependencies, records: list[dict[str, str]], work_id: str) -> dict[str, object] | None:
    """Разбирает смену моделями и возвращает сырые наблюдения.

    Отказ модели на одном кадре не должен стоить всего прогона: смена пропускается,
    остальные считаются дальше, а в кеше остаётся то, что уже разобрано.
    """
    payload = build_payload(records, work_id)
    try:
        raw = dependencies.facade.observe_shift(payload)
    except (ValueError, httpx.HTTPError):
        logger.exception("Смена по работе %s не разобрана, пропускаю", work_id)
        return None
    if raw is None:
        logger.warning("Смена по работе %s не разобрана", work_id)
        return None
    stored = {
        PLAN_DATE_KEY: raw.plan_entry.plan_date.isoformat(),
        FRAME_IDS_KEY: list(raw.frame_ids),
        OBSERVATIONS_KEY: [asdict(item) for item in raw.observations],
        MOTIONS_KEY: [asdict(item) if item is not None else None for item in raw.motions],
        FACADE_KEY: [asdict(item) if item is not None else None for item in raw.facade],
        SCENE_KEY: list(raw.scene_mismatch),
    }
    return stored


def restore_observations(stored: dict[str, object]) -> tuple[FrameObservation, ...]:
    """Восстанавливает наблюдения по снимкам из кеша."""
    observed_on = date.fromisoformat(str(stored[PLAN_DATE_KEY]))
    observations = []
    for item in stored[OBSERVATIONS_KEY]:  # type: ignore[union-attr]
        equipment = tuple(_restore_equipment(entry) for entry in item["equipment"])
        observation = FrameObservation(
            frame_id=str(item["frame_id"]),
            observed_on=observed_on,
            equipment=equipment,
            limited_view=bool(item.get("limited_view", False)),
            limited_reason=str(item.get("limited_reason", "")),
        )
        observations.append(observation)
    return tuple(observations)


def _restore_equipment(entry: dict[str, object]) -> ObservedEquipment:
    """Восстанавливает одну находку техники из кеша.

    Значение приходит либо строкой из файла, либо самим членом перечисления —
    у смен, посчитанных в этом же прогоне. Оборачивать его в `str()` нельзя:
    у перечисления это даёт имя члена, а не значение.
    """
    item = ObservedEquipment(
        machine_type=str(entry["machine_type"]),
        source=EquipmentSource(entry["source"]),
        status=EquipmentStatus(entry["status"]),
        count=int(entry["count"]),  # type: ignore[arg-type]
    )
    return item


def restore_motions(stored: dict[str, object]) -> tuple[MotionObservation | None, ...]:
    """Восстанавливает сравнения пар кадров из кеша."""
    motions = []
    for entry in stored[MOTIONS_KEY]:  # type: ignore[union-attr]
        if entry is None:
            motions.append(None)
            continue
        motion = MotionObservation(
            moved=bool(entry["moved"]),
            operator_present=bool(entry["operator_present"]),
            working_body_changed=bool(entry["working_body_changed"]),
            justification=str(entry["justification"]),
        )
        motions.append(motion)
    return tuple(motions)


def _shift_settings() -> Settings:
    """Настройки прогона смен: календарный план сжат до дня на вид работ."""
    settings = Settings(calendar_plan_path=SHIFT_PLAN_PATH)
    return settings


def restore_facade(stored: dict[str, object]) -> tuple[FacadeReadiness | None, ...]:
    """Восстанавливает разбор фасада по кадрам из кеша."""
    readings = []
    for entry in stored.get(FACADE_KEY) or []:  # type: ignore[union-attr]
        readings.append(None if entry is None else FacadeReadiness(**entry))
    return tuple(readings)


def restore_frames(work_id: str, stored: dict[str, object], settings: Settings) -> ShiftFrames:
    """Собирает разобранные снимки смены из кеша."""
    frames = ShiftFrames(
        plan_entry=_plan_entry(work_id, stored, settings),
        frame_ids=tuple(str(item) for item in stored.get(FRAME_IDS_KEY) or []),
        observations=restore_observations(stored),
        motions=restore_motions(stored),
        facade=restore_facade(stored),
        scene_mismatch=tuple(bool(item) for item in stored.get(SCENE_KEY) or []),
    )
    return frames


def scene_mismatch(records: list[dict[str, str]], work_id: str, settings: Settings) -> tuple[bool, ...]:
    """Считает по снимкам смены, какие из них сняты не с той сцены.

    Проверка идёт по самим файлам и не требует моделей, поэтому её можно повторить
    и при пересборке по кешу: результат при тех же снимках всегда один и тот же.
    """
    payload = build_payload(records, work_id)
    frames = payload[FRAMES_PAYLOAD_KEY]
    paths = tuple(Path(str(item[IMAGE_PATH_KEY])) for item in frames)  # type: ignore[union-attr,index]
    comparator = SceneComparator(settings.scene_mismatch_threshold)
    mismatches = comparator.find_mismatches(paths)
    return mismatches


def build_timelines(
    cache: dict[str, dict[str, object]],
    dependencies,
    records: list[dict[str, str]],
) -> dict[str, object]:
    """Пересобирает ленты слотов по сырым наблюдениям из кеша."""
    settings = _shift_settings()
    service = ShiftTimelineService(
        slot_minutes=settings.slot_minutes,
        slots_per_shift=settings.slots_per_shift,
        shift_start_hour=settings.shift_start_hour,
    )
    timelines: dict[str, object] = {}
    for work_id, stored in sorted(cache.items()):
        rules = dependencies.rules_by_work[work_id]
        frames = restore_frames(work_id, stored, settings)
        frames = replace(frames, scene_mismatch=scene_mismatch(records, work_id, settings))
        timeline = service.build_timeline(rules, frames)
        print_timeline(timeline)
        timelines[work_id] = asdict(timeline)
    return timelines


def _plan_entry(work_id: str, stored: dict[str, object], settings: Settings) -> PlanEntry:
    """Собирает пункт плана для пересчёта ленты."""
    entry = PlanEntry(
        project_id=settings.project_id,
        work_id=work_id,
        plan_date=date.fromisoformat(str(stored[PLAN_DATE_KEY])),
    )
    return entry


def main() -> int:
    """Разбирает смены моделями либо пересобирает ленты по кешу."""
    arguments = [value for value in sys.argv[1:] if value != CACHED_FLAG]
    use_cache = CACHED_FLAG in sys.argv
    records = load_manifest()
    dependencies = build_dependencies(_shift_settings())
    cache = json.loads(OBSERVATIONS_CACHE.read_text(encoding="utf-8")) if OBSERVATIONS_CACHE.exists() else {}
    if not use_cache:
        work_ids = arguments or sorted({record[WORK_ID_KEY] for record in records})
        for work_id in work_ids:
            stored = observe_work(dependencies, records, work_id)
            if stored is None:
                continue
            cache[work_id] = stored
            # Кеш пишется после каждой смены: разбор одной смены это десятки запросов
            # к моделям, и падение на последней не должно стоить всего прогона.
            save_observations(cache)
    timelines = build_timelines(cache, dependencies, records)
    TIMELINES_CACHE.write_text(json.dumps(timelines, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("Ленты слотов сохранены в %s", TIMELINES_CACHE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
