"""Собирает страницу смен по слотам для демонстрационного набора.

Сама сборка живёт в сервисе: ту же страницу он строит и по данным пользователя
после прогона. Здесь только источники демонстрации.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from report_stand import StandBuilder, StandSources  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

FRAMES_CACHE_PATH = Path("data/cache/demo_v2_observations.json")
FRAMES_PHOTOS_DIR = Path("data/photos_v2")
TIMELINES_PATH = Path("data/cache/shift_timelines.json")
OBSERVATIONS_PATH = Path("data/cache/shift_observations.json")
SUMMARY_PATH = Path("data/cache/plan_fact_summary.json")
SLOT_PHOTOS_DIR = Path("data/photos_slots")
PLAN_PATH = Path("config/calendar_plan_new.json")
OUTPUT_DIR = Path("docs/stand")
PHOTO_URL_PREFIX = "/demo/photos/"

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


def work_names() -> dict[str, str]:
    """Читает названия видов работ из календарного плана."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    names = {str(stage["work_id"]): str(stage["full_name"]) for stage in plan["stages"]}
    return names


def main() -> int:
    """Собирает демонстрационную страницу смен."""
    frames = json.loads(FRAMES_CACHE_PATH.read_text(encoding="utf-8"))
    sources = StandSources(
        timelines_path=TIMELINES_PATH,
        observations_path=OBSERVATIONS_PATH,
        photos_dir=SLOT_PHOTOS_DIR,
        titles=work_names(),
        output_dir=OUTPUT_DIR,
        photo_url_prefix=PHOTO_URL_PREFIX,
        photos_by_work=True,
        summary_path=SUMMARY_PATH,
        about_html=ABOUT_HTML,
        frames_payload=frames,
        frames_photos_dir=FRAMES_PHOTOS_DIR,
    )
    target = StandBuilder(sources).build()
    size_mb = target.stat().st_size / 1024 / 1024
    logger.info("Стенд собран: %s (%.1f МБ)", target, size_mb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
