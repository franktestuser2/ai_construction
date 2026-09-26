"""Собирает демонстрационный стенд: одну самодостаточную HTML-страницу.

Страница читает результаты прогона из кеша и показывает план, снимки с рамками
детектора, ответы VLM и вердикт по каждой контрольной дате.
"""

import base64
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

CACHE_PATH = Path("data/cache/demo_v2_observations.json")
PHOTOS_DIR = Path("data/photos_v2")
SHIFT_TIMELINES_PATH = Path("data/cache/shift_timelines.json")
SHIFT_OBSERVATIONS_PATH = Path("data/cache/shift_observations.json")
SLOT_PHOTOS_DIR = Path("data/photos_slots")
SLOT_MANIFEST_PATH = SLOT_PHOTOS_DIR / "manifest.json"
PLAN_PATH = Path("config/calendar_plan_new.json")
RULES_PATH = Path("config/equipment_rules_v3.json")
SLOT_PREVIEW_WIDTH = 1000
SLOT_PREVIEW_QUALITY = 74
FIRST_SLOT_STRIPES = 2
WORK_EVIDENCE_KIND = "признак_работ"
FACADE_CHECK_KEY = "facade_check"
FULL_STRIPES = 3
TEMPLATE_PATH = Path("templates/demo_stand.html")
OUTPUT_PATH = Path("docs/demo_stand.html")
DATA_PLACEHOLDER = "__DATA__"
PREVIEW_WIDTH = 1280
PREVIEW_QUALITY = 78
DATA_URI_TEMPLATE = "data:image/jpeg;base64,{encoded}"
BUILD_STAMP_FORMAT = "%d.%m.%Y %H:%M"

ABOUT_HTML = """
<h2>Что мы строим</h2>
<p>Демонстрационный проект <b>EDU-DEMO-001</b> — образовательная организация (школа) с одним
подземным этажом. Направление «Образование» по справочнику видов работ ЛТЦ: в набор попали
только те работы, которые в справочнике отмечены для этого направления.</p>
<p>Календарный план линейный: этапы не перекрываются, на каждую дату приходится ровно один
вид работ, поэтому любой снимок однозначно привязывается к пункту плана. Всего 7 пунктов
и 294 дня, с 5 октября 2026 по 25 июля 2027 года.</p>

<h3>Как строится вердикт</h3>
<p>Для каждого вида работ задан перечень требуемой техники с ролью и источником признака.
<b>Обязательная</b> машина — ведущая для этапа: без неё работа не ведётся.
<b>Вспомогательная</b> — нужная, но её отсутствие не рушит вердикт, а даёт отклонение низкой
критичности. Источник признака — либо <b>детектор</b> (рамка на снимке и скор), либо
<b>VLM</b> (ответ на прямой вопрос с обоснованием), если такого класса в детекторе нет.</p>
<p>По каждой контрольной дате: <b>подтверждён</b> — обязательный признак найден и работы идут;
<b>частично</b> — признак найден, но техника простаивает или не хватает количества;
<b>не подтверждён</b> — обязательного признака нет.
Пункт плана считается подтверждённым, если обязательный признак найден не менее чем на половине
его снимков и хотя бы на одном из них работы идут.</p>

<h3>Что важно знать о данных</h3>
<p>Снимки взяты из архива заказчика. Даты съёмки назначены внутри периода своего этапа:
исходные штампы на кадрах относятся к разным объектам и, как отмечено в материалах заказчика,
не являются датами демонстрационного проекта. Дата съёмки записана в EXIF каждого файла.</p>
<p>Порог уверенности детектора — 0.05. Модель отдаёт низкие абсолютные скоры: в эталонных
прогонах авторов весов верные находки подписаны 0.05–0.10, при пороге 0.3 не находится ничего.
Классы Roller и Trailer в правилах не используются: на обучении каток дал mAP 0.002,
а прицеп — 0.18.</p>
"""


def encode_photo(path: Path, width_limit: int = PREVIEW_WIDTH, quality: int = PREVIEW_QUALITY) -> str:
    """Готовит уменьшенную копию снимка и кодирует её для встраивания в страницу."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    if width > width_limit:
        image = image.resize((width_limit, round(height * width_limit / width)))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_uri = DATA_URI_TEMPLATE.format(encoded=encoded)
    return data_uri


def collect_images(payload: dict[str, object]) -> dict[str, str]:
    """Собирает встраиваемые копии всех снимков прогона."""
    images: dict[str, str] = {}
    for stage in payload["stages"]:  # type: ignore[index]
        for frame in stage["frames"]:
            path = PHOTOS_DIR / stage["work_id"] / frame["file"]
            images[frame["file"]] = encode_photo(path)
    return images


def is_slot_counted(slot: dict[str, object]) -> bool:
    """Повторяет правило зачёта: три полоски, у последнего слота достаточно двух."""
    if slot["frame_id"] is None:
        return False
    stripes = [slot["has_equipment"], slot["has_kit"], slot["has_motion"]]
    required = FIRST_SLOT_STRIPES if slot["is_first"] else FULL_STRIPES
    counted = sum(1 for value in stripes[:required] if value) == required
    return counted


def _work_names() -> dict[str, str]:
    """Читает названия видов работ из календарного плана."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    names = {str(stage["work_id"]): str(stage["full_name"]) for stage in plan["stages"]}
    return names


def _position_index(work_id: str) -> dict[str, dict[str, str]]:
    """Собирает соответствие «что нашли → какую позицию правил это закрывает».

    Нужно показу: детектор находит на кадре и то, чего в правилах этапа нет вовсе,
    и без пометки такие находки выглядят как часть вердикта.
    """
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    work = next((item for item in rules["works"] if item["work_id"] == work_id), None)
    index: dict[str, dict[str, str]] = {}
    for position in work["positions"] if work else []:
        role = {"position": position["position"], "kind": position["kind"], "lead": position.get("lead", False)}
        for alternative in position["alternatives"]:
            names = alternative.get("detector_classes") or [alternative["machine_type"]]
            for name in names:
                index[name] = role
    return index


KIT_TEMPLATE = "Необходимые машины для производства работ: {machines}"
FACADE_KIT_TEXT = (
    "Техника на этом этапе не проверяется: работает фасадный пайплайн — "
    "детектор зданий, разбор фасада на ячейки и проверка ограждений"
)
LEAD_MARK = " (ведущая)"


def _kit_text(work_id: str) -> str:
    """Составляет строку о том, какие машины нужны для производства этих работ."""
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    work = next((item for item in rules["works"] if item["work_id"] == work_id), None)
    if work is None:
        return ""
    if work.get(FACADE_CHECK_KEY):
        return FACADE_KIT_TEXT
    machines = [
        f"{position['position']}{LEAD_MARK if position.get('lead') else ''}"
        for position in work["positions"]
        if position["kind"] != WORK_EVIDENCE_KIND
    ]
    text = KIT_TEMPLATE.format(machines=", ".join(machines).lower())
    return text


def _frame_details(observations: dict[str, object], work_id: str) -> dict[str, dict[str, object]]:
    """Собирает по каждому кадру смены находки техники и обоснование движения."""
    stored = observations.get(work_id)
    if stored is None:
        return {}
    facade = stored.get("facade") or []
    if facade:
        return _facade_details(stored, facade)  # type: ignore[arg-type]
    motions = stored["motions"]  # type: ignore[index]
    roles = _position_index(work_id)
    details: dict[str, dict[str, object]] = {}
    for index, item in enumerate(stored["observations"]):  # type: ignore[index]
        motion = motions[index] if index < len(motions) else None
        for unit in item["equipment"]:
            unit["role"] = roles.get(unit["machine_type"])
        details[item["frame_id"]] = {
            "equipment": item["equipment"],
            "motion": motion,
        }
    return details


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


def collect_shifts() -> tuple[list[dict[str, object]], dict[str, str]]:
    """Собирает ленты смен, снимки слотов и пояснения к ним."""
    if not SHIFT_TIMELINES_PATH.exists():
        return [], {}
    timelines = json.loads(SHIFT_TIMELINES_PATH.read_text(encoding="utf-8"))
    observations = json.loads(SHIFT_OBSERVATIONS_PATH.read_text(encoding="utf-8"))
    names = _work_names()
    shifts: list[dict[str, object]] = []
    images: dict[str, str] = {}
    for work_id, timeline in sorted(timelines.items()):
        details = _frame_details(observations, work_id)
        for slot in timeline["slots"]:
            slot["is_counted"] = is_slot_counted(slot)
            slot["details"] = details.get(slot["frame_id"])
            if slot["frame_id"] is not None:
                path = SLOT_PHOTOS_DIR / work_id / slot["frame_id"]
                images[slot["frame_id"]] = encode_photo(path, SLOT_PREVIEW_WIDTH, SLOT_PREVIEW_QUALITY)
        timeline["work_name"] = names.get(work_id, work_id)
        timeline["kit"] = _kit_text(work_id)
        shifts.append(timeline)
    return shifts, images


def main() -> None:
    """Записывает страницу стенда на диск."""
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    shifts, slot_images = collect_shifts()
    payload["shifts"] = shifts
    payload["images"] = collect_images(payload) | slot_images
    payload["about"] = ABOUT_HTML
    payload["built_at"] = datetime.now().strftime(BUILD_STAMP_FORMAT)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    serialized = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace(DATA_PLACEHOLDER, serialized)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(page, encoding="utf-8")
    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    print(f"Стенд собран: {OUTPUT_PATH} ({size_mb:.1f} МБ)")


if __name__ == "__main__":
    main()
