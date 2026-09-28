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
LEAD_KEY = "lead"
KIT_KIND = "комплект"
CREW_KIND = "люди"
FACADE_CHECK_KEY = "facade_check"
OBSERVATIONS_KEY = "observations"
BUILD_STAMP_FORMAT = "%d.%m.%Y %H:%M"
KIT_TEMPLATE = "1) Основная машина, которая делает работу: {machines}"
EXTRA_TEMPLATE = "2) Дополнительные машины, работающие при ней: {machines}"
NO_EXTRA_MACHINES = "не требуются"
EVIDENCE_TEMPLATE = "Признак работ на объекте: {evidence}"
CREW_TEMPLATE = "3) Люди на фронте работ: {crew}"
NO_LEAD_DESCRIPTION = "На кадре нет того, кто делает работу: ни главной машины, ни бригады"
NO_KIT_DESCRIPTION = "Комплект за смену не собран: дополнительной машины не нашлось"
NO_MOTION_DESCRIPTION = "Между этим и прошлым кадром работа не подтверждена"
FOREIGN_DESCRIPTION = "На кадре техника не по этапу: {machine}"
FRAME_NOTE_TEMPLATE = "Смена {work}, отрезок {time}"
# Короткие имена работ для подписей: полные названия справочника не читаются с ходу.
SHORT_TITLES = {
    "W01": "Погрузка мусора",
    "W02": "Буронабивные сваи",
    "W03": "Разработка грунта",
    "W04": "Фундаментная плита",
    "W05": "Монолит подземной части",
    "W06": "Монолит надземной части",
    "W07": "Фасадная система",
}
STAGE_CONFIRMED = "подтверждён"
STAGE_NOT_CONFIRMED = "не подтверждён"
FACADE_KIT_TEXT = (
    "Техника на этом этапе не проверяется: работает фасадный пайплайн — "
    "детектор зданий, разбор фасада на ячейки и проверка ограждений"
)
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


# Классы детектора, которых нет ни в одних правилах: в правила они не попали намеренно
# (Trailer, Motor grader и Roller обучены плохо), но на кадре встречаются и показываются
# как техника не по этапу. По-английски это читается как сбой, а не как находка.
EXTRA_MACHINE_NAMES = {
    "Bulldozer": "Бульдозер",
    "Cleaning equipment": "Уборочная машина",
    "Forklift Standart": "Вилочный погрузчик",
    "Gazelle": "Малотоннажный фургон",
    "Motor grader": "Автогрейдер",
    "Roller": "Каток",
    "Tanker": "Автоцистерна",
    "Trailer": "Прицеп или полуприцеп",
    "Truck": "Грузовик",
}


def _machine_names() -> dict[str, str]:
    """Сопоставляет класс детектора русскому названию машины из правил.

    Детектор отдаёт свои английские ярлыки — `Excavator`, `Dump truck`. Показывать их
    рядом с русскими позициями правил незачем: человек читает «список машин» и не должен
    догадываться, что `Excavator` и «Экскаватор» это одно и то же. Исходный ярлык
    остаётся рядом — по нему находку можно проверить.
    """
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    names: dict[str, str] = dict(EXTRA_MACHINE_NAMES)
    for work in rules["works"]:
        for position in work["positions"]:
            for alternative in position["alternatives"]:
                for found in alternative.get("detector_classes") or []:
                    names[found] = alternative["machine_type"]
    return names


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
            # Находку одной и той же позиции детектор подписывает своим классом,
            # а модель — названием машины из правил. Роль нужна и для той, и для другой.
            names = [alternative["machine_type"], *(alternative.get("detector_classes") or [])]
            for name in names:
                index[name] = role
    return index


def _position_text(position: dict[str, object]) -> str:
    """Позиция комплекта словами: чем она закрывается и ведущая ли она.

    Перечень альтернатив дописывается, только если он отличается от названия позиции:
    позиции названы по работе, а не по классу машины, и «машина для погрузки» сама по себе
    не говорит, что её закрывает экскаватор. А «самосвал (самосвал)» — пустое повторение.
    """
    names = [str(item["machine_type"]).lower() for item in position["alternatives"]]  # type: ignore[index]
    title = str(position["position"]).lower()
    # Пометка «ведущая» больше не нужна: ведущая машина стоит в своём пункте перечня.
    if names == [title]:
        return title
    return f"{title} — {' или '.join(names)}"


def _evidence_seen(observations: dict[str, object], work_id: str) -> bool:
    """Подтверждён ли признак работ хотя бы на одном снимке смены."""
    work = _rules_work(work_id)
    stored = observations.get(work_id)
    if work is None or stored is None:
        return False
    wanted = {
        alternative["machine_type"]
        for position in work["positions"]  # type: ignore[index]
        if position["kind"] == WORK_EVIDENCE_KIND
        for alternative in position["alternatives"]
    }
    if not wanted:
        return False
    frames = stored.get(OBSERVATIONS_KEY) or []  # type: ignore[union-attr]
    found = any(
        unit["machine_type"] in wanted and unit["count"] > NOTHING
        for frame in frames
        for unit in frame["equipment"]
    )
    return found


def _crew_text(work_id: str) -> str:
    """Составляет строку о людях на фронте работ.

    Отдельный пункт, потому что бригада — не машина и не состояние объекта: на
    арматурных и опалубочных работах работу делают руками, и техника при этом простаивает.
    """
    work = _rules_work(work_id)
    if work is None:
        return ""
    crew = [
        str(position["position"]).lower()
        for position in work["positions"]  # type: ignore[index]
        if position["kind"] == CREW_KIND
    ]
    if not crew:
        return ""
    text = CREW_TEMPLATE.format(crew=", ".join(crew))
    return text


def _evidence_text(work_id: str) -> str:
    """Составляет строку о признаке работ: что должно быть видно на самом объекте.

    Это не машина, а состояние объекта — опалубка и арматура плиты, каркас этажа,
    облицовка фасада. Машины показывают, чем работу делают, признак — что она сделана.
    """
    work = _rules_work(work_id)
    if work is None:
        return ""
    evidence = [
        str(position["position"]).lower()
        for position in work["positions"]  # type: ignore[index]
        if position["kind"] == WORK_EVIDENCE_KIND
    ]
    if not evidence:
        return ""
    text = EVIDENCE_TEMPLATE.format(evidence=", ".join(evidence))
    return text


def _extra_text(work_id: str) -> str:
    """Составляет строку о машинах, которые на этапе могут быть, а могут не быть.

    Пункт стоит у каждого этапа с техникой, даже когда сопутствующих машин нет:
    пустое место на его месте читается как недосмотр, а не как «их и не требуется».
    """
    if _is_facade(work_id):
        return ""
    machines = _machines_text(work_id, lead=False) or NO_EXTRA_MACHINES
    text = EXTRA_TEMPLATE.format(machines=machines)
    return text


def _is_facade(work_id: str) -> bool:
    """Проверяет, что работу подтверждает фасадный пайплайн, а не техника."""
    work = _rules_work(work_id)
    if work is None:
        return False
    facade = bool(work.get(FACADE_CHECK_KEY))
    return facade


def _machines_text(work_id: str, lead: bool) -> str:
    """Перечисляет машины этапа: ведущие отдельно, все прочие отдельно.

    Перечисляется только комплект: главная машина делает саму работу — грузит, бурит,
    подаёт бетон, — а остальные машины комплекта работают при ней. Допустимая техника
    вроде прицепа или бульдозера в перечень не идёт: она на площадке бывает, но работу
    не делает и комплект не закрывает.

    Рядом с позицией перечисляется, чем её можно закрыть: позиции названы по работе,
    а не по классу машины, и без перечня «машина для погрузки» не говорит о том, что
    её закрывает экскаватор.
    """
    work = _rules_work(work_id)
    if work is None or work.get(FACADE_CHECK_KEY):
        return ""
    machines = [
        _position_text(position)
        for position in work["positions"]  # type: ignore[index]
        if position["kind"] == KIT_KIND and bool(position.get(LEAD_KEY)) is lead
    ]
    text = ", ".join(machines).lower()
    return text


def _kit_text(work_id: str) -> str:
    """Составляет строку о машинах, без которых работа не идёт."""
    work = _rules_work(work_id)
    if work is None:
        return ""
    if work.get(FACADE_CHECK_KEY):
        return FACADE_KIT_TEXT
    machines = _machines_text(work_id, lead=True)
    if not machines:
        return ""
    text = KIT_TEMPLATE.format(machines=machines)
    return text


def _slot_assessment(slot: dict[str, object], shift: dict[str, object]) -> dict[str, object]:
    """Собирает вердикт по кадру для вкладки просмотра: засчитан ли отрезок и почему."""
    deviations: list[dict[str, str]] = []
    if slot.get("limited_view"):
        reason = slot.get("limited_reason") or "фронт работ не виден"
        deviations.append({"description": f"Отрезок вне контроля ИИ: {reason}"})
    if not slot.get("has_equipment"):
        deviations.append({"description": NO_LEAD_DESCRIPTION})
    elif not slot.get("has_kit"):
        deviations.append({"description": NO_KIT_DESCRIPTION})
    if slot.get("has_equipment") and not slot.get("has_motion") and not slot.get("is_first"):
        deviations.append({"description": NO_MOTION_DESCRIPTION})
    for machine in slot.get("foreign_equipment") or []:
        deviations.append({"description": FOREIGN_DESCRIPTION.format(machine=machine)})
    confirmed = [
        unit["machine_type"]
        for unit in (slot.get("details") or {}).get("equipment", [])  # type: ignore[union-attr]
        if unit.get("count", NOTHING) > NOTHING and unit.get("role")
    ]
    assessment = {
        "is_compliant": bool(slot.get("is_counted")),
        "deviations": deviations,
        "confirmed_equipment": confirmed,
    }
    return assessment


def _short_title(work_id: str, full_name: str) -> str:
    """Короткое имя вида работ для подписей.

    Полные названия справочника ЛЦТ идут со всеми уточнениями в скобках и занимают
    в подписи три строки. В таблицах и легендах нужно имя, которое читается с одного
    взгляда, а полное остаётся в разборе кадра.
    """
    short = SHORT_TITLES.get(work_id)
    if short is not None:
        return short
    tail = str(full_name).split(" → ")[-1]
    cut = tail.split("(")[0].split(",")[0].strip()
    return cut or tail


def _stages_from_shifts(shifts: list[dict[str, object]]) -> list[dict[str, object]]:
    """Раскладывает кадры смен по видам работ для вкладки просмотра."""
    stages = []
    for shift in shifts:
        frames = []
        for slot in shift["slots"]:  # type: ignore[index]
            if slot.get("frame_id") is None:
                continue
            details = slot.get("details") or {}
            frames.append({
                "file": slot["frame_id"],
                "captured_at": str(slot["starts_at"]),
                "note": FRAME_NOTE_TEMPLATE.format(
                    work=shift["work_id"], time=str(slot["starts_at"])[11:16]
                ),
                "equipment": details.get("equipment", []),  # type: ignore[union-attr]
                "assessment": _slot_assessment(slot, shift),
                "missing_mandatory": not slot.get("has_equipment"),
            })
        counted = sum(1 for slot in shift["slots"] if slot.get("is_counted"))  # type: ignore[union-attr]
        stages.append({
            "work_id": shift["work_id"],
            "full_name": shift["work_name"],
            "short_name": _short_title(str(shift["work_id"]), str(shift["work_name"])),
            "start": shift["plan_date"],
            "finish": shift["plan_date"],
            "status": STAGE_CONFIRMED if counted > NOTHING else STAGE_NOT_CONFIRMED,
            "frames": frames,
        })
    return stages


class StandBuilder:
    """Собирает страницу смен по слотам из заданных источников."""

    def __init__(self, sources: StandSources) -> None:
        self._sources = sources

    def build(self) -> Path:
        """Пишет страницу и снимки к ней, возвращает путь страницы."""
        payload: dict[str, object] = dict(self._sources.frames_payload or {"stages": []})
        shifts, images = self._collect_shifts()
        payload["shifts"] = shifts
        # Просмотр снимков идёт по тем же кадрам, что разложены по отрезкам смен:
        # два разных набора на одной странице сбивали с толку — было непонятно,
        # какие снимки в итоге дали проценты выполнения.
        payload["stages"] = _stages_from_shifts(shifts)
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
            names = _machine_names()
            for slot in timeline["slots"]:
                slot["is_counted"] = is_slot_counted(slot)
                slot["foreign_equipment"] = [
                    names.get(found, found) for found in slot.get("foreign_equipment") or []
                ]
                slot["details"] = details.get(slot["frame_id"])
                if slot["frame_id"] is not None:
                    path = self._photo_path(work_id, slot["frame_id"])
                    images[slot["frame_id"]] = self._save_photo(path, slot["frame_id"])
            timeline["work_name"] = self._sources.titles.get(work_id, work_id)
            timeline["short_name"] = _short_title(work_id, timeline["work_name"])
            timeline["kit"] = _kit_text(work_id)
            timeline["extra_kit"] = _extra_text(work_id)
            timeline["crew"] = _crew_text(work_id)
            timeline["evidence"] = _evidence_text(work_id)
            timeline["evidence_seen"] = _evidence_seen(observations, work_id)
            timeline["lead_seen"] = any(slot["has_equipment"] for slot in timeline["slots"])
            # На фасадном этапе полоски означают другое, и подписи страница берёт по этому флагу.
            timeline["facade"] = _is_facade(work_id)
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
        names = _machine_names()
        details: dict[str, dict[str, object]] = {}
        for index, item in enumerate(stored["observations"]):  # type: ignore[index]
            motion = motions[index] if index < len(motions) else None
            for unit in item["equipment"]:
                found = unit["machine_type"]
                unit["role"] = roles.get(found)
                unit["detector_class"] = found if found in names else ""
                unit["machine_type"] = names.get(found, found)
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
