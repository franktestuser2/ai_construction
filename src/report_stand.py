"""Сборка страницы со сменами по слотам.

Страница одна, а данных для неё два источника: демонстрационный набор и прогон
пользователя. Поэтому пути к лентам, наблюдениям и снимкам задаются снаружи,
а не прибиты к модулю: демонстрация собирается из кеша проекта, прогон — из
своего каталога. Пока данных нет, страница открывается пустой.

Снимки выносятся из страницы наружу отдельными файлами: встроенные в текст,
они раздували её до четырнадцати мегабайт.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from config import Settings
from site_monitoring.adapters.shift_timeline_reader import ShiftTimelineReader
from site_monitoring.services.plan_fact_report import build_report
from page_shell import render_stand_nav

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path("templates/demo_stand.html")
RULES_PATH = Path("config/equipment_rules_v3.json")
DATA_PLACEHOLDER = "__DATA__"
NAV_PLACEHOLDER = "__NAV__"
PHOTOS_SUBDIR = "photos"
INDEX_NAME = "index.html"
PREVIEW_WIDTH = 1000
PREVIEW_QUALITY = 74
FIRST_SLOT_STRIPES = 2
FULL_STRIPES = 3
WORK_EVIDENCE_KIND = "признак_работ"
FACADE_CHECK_KEY = "facade_check"
BUILD_STAMP_FORMAT = "%d.%m.%Y %H:%M"
KIT_TEMPLATE = "Необходимые машины для производства работ: {machines}"
FACADE_KIT_TEXT = (
    "Техника на этом этапе не проверяется: работает фасадный пайплайн — "
    "детектор зданий, разбор фасада на ячейки и проверка ограждений"
)
LEAD_MARK = " (ведущая)"
PERCENT = 100
NOTHING = 0


@dataclass(frozen=True)
class StandSources:
    """Откуда брать данные страницы и куда её класть."""

    timelines_path: Path
    observations_path: Path
    photos_dir: Path
    titles: dict[str, str]
    output_dir: Path
    photo_url_prefix: str
    photos_by_work: bool = True
    summary_path: Path | None = None
    about_html: str = ""
    # Вкладка просмотра снимков живёт на своём наборе кадров: у прогона её нет.
    frames_payload: dict[str, object] | None = None
    frames_photos_dir: Path | None = None


def is_slot_counted(slot: dict[str, object]) -> bool:
    """Повторяет правило зачёта: три полоски, у первого отрезка достаточно двух.

    Отрезок, по которому фронт работ не виден, не засчитывается ни при каких
    полосках: такой участок вне контроля ИИ и требует ручной проверки.
    """
    if slot["frame_id"] is None or slot.get("limited_view"):
        return False
    stripes = [slot["has_equipment"], slot["has_kit"], slot["has_motion"]]
    required = FIRST_SLOT_STRIPES if slot["is_first"] else FULL_STRIPES
    counted = sum(1 for value in stripes[:required] if value) == required
    return counted


def _rules_work(work_id: str) -> dict[str, object] | None:
    """Находит правила вида работ."""
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    work = next((item for item in rules["works"] if item["work_id"] == work_id), None)
    return work


def _position_index(work_id: str) -> dict[str, dict[str, object]]:
    """Собирает соответствие «что нашли → какую позицию правил это закрывает».

    Нужно показу: детектор находит на кадре и то, чего в правилах этапа нет вовсе,
    и без пометки такие находки выглядят как часть вердикта.
    """
    work = _rules_work(work_id)
    index: dict[str, dict[str, object]] = {}
    for position in work["positions"] if work else []:  # type: ignore[index]
        role = {
            "position": position["position"],
            "kind": position["kind"],
            "lead": position.get("lead", False),
        }
        for alternative in position["alternatives"]:
            names = alternative.get("detector_classes") or [alternative["machine_type"]]
            for name in names:
                index[name] = role
    return index


def _kit_text(work_id: str) -> str:
    """Составляет строку о том, какие машины нужны для производства этих работ."""
    work = _rules_work(work_id)
    if work is None:
        return ""
    if work.get(FACADE_CHECK_KEY):
        return FACADE_KIT_TEXT
    machines = [
        f"{position['position']}{LEAD_MARK if position.get('lead') else ''}"
        for position in work["positions"]  # type: ignore[index]
        if position["kind"] != WORK_EVIDENCE_KIND
    ]
    text = KIT_TEMPLATE.format(machines=", ".join(machines).lower())
    return text


class StandBuilder:
    """Собирает страницу смен по слотам из заданных источников."""

    def __init__(self, sources: StandSources) -> None:
        self._sources = sources

    def build(self) -> Path:
        """Пишет страницу и снимки к ней, возвращает путь страницы."""
        payload: dict[str, object] = dict(self._sources.frames_payload or {"stages": []})
        shifts, images = self._collect_shifts()
        payload["shifts"] = shifts
        payload["dashboard"] = self._build_dashboard()
        payload["images"] = images | self._collect_frame_photos(payload)
        payload["about"] = self._sources.about_html
        payload["built_at"] = datetime.now().strftime(BUILD_STAMP_FORMAT)
        page = self._render(payload)
        self._sources.output_dir.mkdir(parents=True, exist_ok=True)
        target = self._sources.output_dir / INDEX_NAME
        target.write_text(page, encoding="utf-8")
        logger.info("Страница смен собрана: %s, смен %d", target, len(shifts))
        return target

    def _render(self, payload: dict[str, object]) -> str:
        """Подставляет данные в шаблон страницы."""
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
        serialized = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
        page = template.replace(DATA_PLACEHOLDER, serialized)
        # Навигация общая со страницами сервиса: у стенда свой набор корешков
        # уводил половину страниц из виду при первом же переходе.
        page = page.replace(NAV_PLACEHOLDER, render_stand_nav())
        return page

    def _save_photo(self, path: Path, name: str) -> str:
        """Кладёт уменьшенную копию снимка рядом со страницей и возвращает её адрес."""
        target_dir = self._sources.output_dir / PHOTOS_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)
        image = Image.open(path).convert("RGB")
        width, height = image.size
        if width > PREVIEW_WIDTH:
            image = image.resize((PREVIEW_WIDTH, round(height * PREVIEW_WIDTH / width)))
        image.save(target_dir / name, format="JPEG", quality=PREVIEW_QUALITY)
        return f"{self._sources.photo_url_prefix}{name}"

    def _photo_path(self, work_id: str, name: str) -> Path:
        """Путь исходного снимка: у демонстрации они разложены по видам работ."""
        if self._sources.photos_by_work:
            return self._sources.photos_dir / work_id / name
        return self._sources.photos_dir / name

    def _collect_shifts(self) -> tuple[list[dict[str, object]], dict[str, str]]:
        """Собирает ленты смен, снимки отрезков и пояснения к ним."""
        if not self._sources.timelines_path.exists():
            return [], {}
        timelines = json.loads(self._sources.timelines_path.read_text(encoding="utf-8"))
        observations = self._read_observations()
        shifts: list[dict[str, object]] = []
        images: dict[str, str] = {}
        for work_id, timeline in sorted(timelines.items()):
            details = self._frame_details(observations, work_id)
            for slot in timeline["slots"]:
                slot["is_counted"] = is_slot_counted(slot)
                slot["details"] = details.get(slot["frame_id"])
                if slot["frame_id"] is not None:
                    path = self._photo_path(work_id, slot["frame_id"])
                    images[slot["frame_id"]] = self._save_photo(path, slot["frame_id"])
            timeline["work_name"] = self._sources.titles.get(work_id, work_id)
            timeline["kit"] = _kit_text(work_id)
            shifts.append(timeline)
        return shifts, images

    def _collect_frame_photos(self, payload: dict[str, object]) -> dict[str, str]:
        """Кладёт снимки вкладки просмотра, если её набор задан."""
        directory = self._sources.frames_photos_dir
        if directory is None:
            return {}
        images: dict[str, str] = {}
        for stage in payload.get("stages") or []:  # type: ignore[union-attr]
            for frame in stage["frames"]:
                images[frame["file"]] = self._save_photo(directory / stage["work_id"] / frame["file"], frame["file"])
        return images

    def _read_observations(self) -> dict[str, object]:
        """Читает сырые наблюдения прогона, если они сохранены."""
        if not self._sources.observations_path.exists():
            return {}
        payload = json.loads(self._sources.observations_path.read_text(encoding="utf-8"))
        return payload

    def _frame_details(self, observations: dict[str, object], work_id: str) -> dict[str, dict[str, object]]:
        """Собирает по каждому кадру смены находки техники и обоснование движения."""
        stored = observations.get(work_id)
        if stored is None:
            return {}
        facade = stored.get("facade") or []  # type: ignore[union-attr]
        if facade:
            return _facade_details(stored, facade)  # type: ignore[arg-type]
        motions = stored["motions"]  # type: ignore[index]
        roles = _position_index(work_id)
        details: dict[str, dict[str, object]] = {}
        for index, item in enumerate(stored["observations"]):  # type: ignore[index]
            motion = motions[index] if index < len(motions) else None
            for unit in item["equipment"]:
                unit["role"] = roles.get(unit["machine_type"])
            details[item["frame_id"]] = {"equipment": item["equipment"], "motion": motion}
        return details

    def _foreign_count(self, timelines: dict[str, object], work_id: str) -> int:
        """Считает отрезки, где на кадре нашлась техника не по этапу."""
        slots = timelines.get(work_id, {}).get("slots", [])  # type: ignore[union-attr]
        found = sum(1 for slot in slots if slot.get("foreign_equipment"))
        return found

    def _build_dashboard(self) -> dict[str, object]:
        """Считает сводку план-факта для верхней вкладки страницы."""
        settings = Settings()
        timelines = ShiftTimelineReader(self._sources.timelines_path).read_timelines()
        titles = {key: value.split(" → ")[-1] for key, value in self._sources.titles.items()}
        report = build_report(timelines, titles, settings.slots_per_shift)
        raw = json.loads(self._sources.timelines_path.read_text(encoding="utf-8")) if timelines else {}
        conclusion = self._read_conclusion()
        payload = {
            "status": report.status.value,
            "completion": round(report.completion * PERCENT),
            "counted": report.counted_slots,
            "measured": report.measured_slots,
            "planned": report.planned_slots,
            "limited": report.limited_slots,
            "foreign": sum(self._foreign_count(raw, stage.work_id) for stage in report.stages),
            "lag_days": report.lag_days,
            "slot_minutes": settings.slot_minutes,
            "slots_per_shift": settings.slots_per_shift,
            "conclusion": conclusion,
            "stages": [_describe_stage(stage, self._foreign_count(raw, stage.work_id)) for stage in report.stages],
        }
        return payload

    def _read_conclusion(self) -> dict[str, str]:
        """Читает заключение модели, если оно сформировано."""
        path = self._sources.summary_path
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload


def _facade_details(stored: dict[str, object], facade: list) -> dict[str, dict[str, object]]:
    """Собирает разбор фасада по кадрам смены.

    Рамки приходят уже в долях кадра, пересчитывать их не нужно.
    """
    frame_ids = stored.get("frame_ids") or []
    details: dict[str, dict[str, object]] = {}
    for index, frame_id in enumerate(frame_ids):  # type: ignore[union-attr]
        reading = facade[index] if index < len(facade) else None
        details[str(frame_id)] = {"facade": reading}
    return details


def _describe_stage(stage: object, foreign: int) -> dict[str, object]:
    """Готовит строку этапа для сводки на странице."""
    described = {
        "work_id": stage.work_id,  # type: ignore[attr-defined]
        "title": stage.title,  # type: ignore[attr-defined]
        "plan_date": stage.plan_date,  # type: ignore[attr-defined]
        "planned": stage.planned_slots,  # type: ignore[attr-defined]
        "measured": stage.measured_slots,  # type: ignore[attr-defined]
        "counted": stage.counted_slots,  # type: ignore[attr-defined]
        "limited": stage.limited_slots,  # type: ignore[attr-defined]
        "foreign": foreign,
        "completion": round(stage.completion * PERCENT),  # type: ignore[attr-defined]
        "status": stage.status.value,  # type: ignore[attr-defined]
    }
    return described
