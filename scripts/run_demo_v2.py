"""Прогон демонстрационного фотонабора по новому календарному плану.

Каждый снимок разбирается детектором и VLM, затем по нему выносится вердикт
контрольной даты. Результат складывается в кеш, чтобы стенд открывался мгновенно.
"""

import json
import logging
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Settings  # noqa: E402
from site_monitoring.container import _build_recognition  # noqa: E402
from site_monitoring.adapters.equipment_rules_reader import EquipmentRulesReader  # noqa: E402
from site_monitoring.entity import DeviationKind, PlanEntry  # noqa: E402
from site_monitoring.mappers import (  # noqa: E402
    map_frames_payload_to_observations,
    map_rules_payload_to_work_rules,
)
from site_monitoring.services.rule_engine import RuleEngineService  # noqa: E402

logging.basicConfig(level=logging.WARNING)

PLAN_PATH = Path("config/calendar_plan_new.json")
RULES_PATH = Path("config/equipment_rules_v3.json")
PHOTOS_DIR = Path("data/photos_v2")
MANIFEST_PATH = PHOTOS_DIR / "manifest.json"
CACHE_PATH = Path("data/cache/demo_v2_observations.json")
CAPTURED_FORMAT = "%Y-%m-%d %H:%M"
STATUS_CONFIRMED = "подтверждён"
STATUS_PARTIAL = "подтверждён частично"
STATUS_REJECTED = "не подтверждён"


def load_json(path: Path) -> dict | list:
    """Читает файл конфигурации в структуру Python."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload


def serialize_equipment(equipment) -> list[dict[str, object]]:
    """Переводит найденную технику в сериализуемый вид."""
    items = []
    for unit in equipment:
        payload = asdict(unit)
        payload["source"] = unit.source.value
        payload["status"] = unit.status.value
        payload["boxes"] = [list(box) for box in unit.boxes]
        payload["rejected_boxes"] = [list(box) for box in unit.rejected_boxes]
        items.append(payload)
    return items


def serialize_assessment(assessment) -> dict[str, object]:
    """Переводит вердикт контрольной даты в сериализуемый вид."""
    deviations = [
        {"kind": item.kind.value, "machine_type": item.machine_type, "description": item.description}
        for item in assessment.deviations
    ]
    payload = {
        "is_compliant": assessment.is_compliant,
        "deviations": deviations,
        "confirmed_equipment": list(assessment.confirmed_equipment),
    }
    return payload


def has_missing_mandatory(assessment) -> bool:
    """Проверяет, что на кадре не нашлась обязательная техника этапа."""
    kinds = {item.kind for item in assessment.deviations}
    missing = DeviationKind.MISSING_EQUIPMENT in kinds or DeviationKind.NO_DATA in kinds
    return missing


def stage_status(frames: list[dict[str, object]]) -> str:
    """Сводит вердикты кадров этапа в статус пункта календарного плана."""
    total = len(frames)
    found = [frame for frame in frames if not frame["missing_mandatory"]]
    working = [frame for frame in frames if frame["assessment"]["is_compliant"]]
    if working and len(found) * 2 >= total:
        return STATUS_CONFIRMED
    if found:
        return STATUS_PARTIAL
    return STATUS_REJECTED


def process_stage(
    stage: dict[str, object],
    records: dict[str, dict[str, str]],
    recognition,
    rule_engine,
    rules,
    project_id: str,
) -> dict[str, object]:
    """Разбирает все снимки одного пункта плана и выносит по ним вердикты."""
    frames: list[dict[str, object]] = []
    for photo in stage["photos"]:
        record = records[f"Screenshot_{photo['frame']}.png"]
        path = PHOTOS_DIR / record["work_id"] / record["file"]
        captured = datetime.strptime(record["captured_at"], CAPTURED_FORMAT)
        observation = recognition.recognize_frame(
            frame_id=record["file"],
            image_path=path,
            observed_on=captured.date(),
            work_name=stage["short_name"],
            rules=rules,
        )
        plan_entry = PlanEntry(project_id=project_id, work_id=stage["work_id"], plan_date=captured.date())
        assessment = rule_engine.assess_day(plan_entry, rules, (observation,))
        frame = {
            "file": record["file"],
            "captured_at": record["captured_at"],
            "note": record["note"],
            "source_frame": record["source_frame"],
            "limited_view": observation.limited_view,
            "equipment": serialize_equipment(observation.equipment),
            "assessment": serialize_assessment(assessment),
            "missing_mandatory": has_missing_mandatory(assessment),
        }
        frames.append(frame)
        print(f"{record['file']}: соответствие={assessment.is_compliant}", flush=True)
    result = dict(stage)
    result["frames"] = frames
    result["status"] = stage_status(frames)
    result.pop("photos", None)
    return result


CACHED_FLAG = "--cached"


def reassess_stage(stage: dict[str, object], rule_engine, rules, project_id: str) -> dict[str, object]:
    """Пересчитывает вердикты этапа по уже сохранённым наблюдениям, без обращения к моделям."""
    frames = []
    for frame in stage["frames"]:  # type: ignore[index]
        payload = [{"frame_id": frame["file"], "observed_on": frame["captured_at"].split(" ")[0],
                    "limited_view": frame["limited_view"], "equipment": frame["equipment"]}]
        observations = map_frames_payload_to_observations(payload)
        observed_on = date.fromisoformat(frame["captured_at"].split(" ")[0])
        plan_entry = PlanEntry(project_id=project_id, work_id=stage["work_id"], plan_date=observed_on)
        assessment = rule_engine.assess_day(plan_entry, rules, observations)
        updated = dict(frame)
        updated["assessment"] = serialize_assessment(assessment)
        updated["missing_mandatory"] = has_missing_mandatory(assessment)
        frames.append(updated)
    result = dict(stage)
    result["frames"] = frames
    result["status"] = stage_status(frames)
    return result


def merge_stages(fresh: list[dict[str, object]], selected: set[str]) -> list[dict[str, object]]:
    """Подставляет заново разобранные этапы в уже готовый кеш."""
    if not selected or not CACHE_PATH.exists():
        return fresh
    cached = load_json(CACHE_PATH)
    merged = []
    fresh_by_id = {stage["work_id"]: stage for stage in fresh}
    for stage in cached["stages"]:  # type: ignore[index]
        merged.append(fresh_by_id.get(stage["work_id"], stage))
    return merged


def main() -> None:
    """Прогоняет демонстрационный набор и сохраняет кеш наблюдений."""
    arguments = sys.argv[1:]
    cached_only = CACHED_FLAG in arguments
    selected = {item for item in arguments if item != CACHED_FLAG}
    settings = Settings()
    plan = load_json(PLAN_PATH)
    rules_by_work = map_rules_payload_to_work_rules(EquipmentRulesReader(RULES_PATH).read_rules())
    rule_engine = RuleEngineService()
    if cached_only:
        cached = load_json(CACHE_PATH)
        cached["stages"] = [  # type: ignore[index]
            reassess_stage(stage, rule_engine, rules_by_work[stage["work_id"]], cached["project_id"])
            for stage in cached["stages"]  # type: ignore[index]
        ]
        CACHE_PATH.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Вердикты пересчитаны из кеша: {CACHE_PATH}")
        return
    recognition = _build_recognition(settings)
    if recognition is None:
        raise RuntimeError("Не заданы доступы к VLM: прогон невозможен")
    manifest: list[dict[str, str]] = load_json(MANIFEST_PATH)  # type: ignore[assignment]
    records = {item["source_frame"]: item for item in manifest}
    fresh = [
        process_stage(
            stage,
            records,
            recognition,
            rule_engine,
            rules_by_work[stage["work_id"]],
            plan["project_id"],
        )
        for stage in plan["stages"]
        if not selected or stage["work_id"] in selected
    ]
    stages = merge_stages(fresh, selected)
    payload = {key: value for key, value in plan.items() if key != "stages"}
    payload["stages"] = stages
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Кеш записан: {CACHE_PATH}")


if __name__ == "__main__":
    main()
