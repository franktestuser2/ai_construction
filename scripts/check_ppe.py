"""Прогон проверок СИЗ по фотографиям и роликам, лежащим в папке.

Зачем отдельно от камер: проверка каски и жилета работает на крупных планах, а камеры
объекта обзорные — человек занимает в них два десятка пикселей. Этот прогон показывает,
на каком материале проверка работает, и его же результат идёт на страницу сервиса.

Материал для показа отобран вручную и перечислен в `config/ppe_demo.json`: оставлены
только те снимки, где отметки проверены глазами.

Запуск: python scripts/check_ppe.py [--source data/ppe_demo] [--selection config/ppe_demo.json]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camera_watch.adapters.camera_registry_reader import SafetyChecksReader  # noqa: E402
from camera_watch.adapters.clip_encoder import ClipEncoder  # noqa: E402
from camera_watch.adapters.person_detector import PersonDetector  # noqa: E402
from camera_watch.entity import DETECTOR_SOURCE  # noqa: E402
from camera_watch.container import build_classifiers  # noqa: E402
from camera_watch.services.safety_assessment import SafetyAssessmentService  # noqa: E402
from config import Settings  # noqa: E402
from ppe_report import PpeReportBuilder  # noqa: E402
from ppe_video import VideoAnnotator  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SOURCE = Path("data/ppe_demo")
DEFAULT_OUTPUT = Path("docs/ppe")
DEFAULT_SELECTION = Path("config/ppe_demo.json")


def build_service(settings: Settings) -> SafetyAssessmentService:
    """Собирает разбор СИЗ: люди детектором, признаки — сравнением фраз."""
    reader = SafetyChecksReader(settings.safety_checks_path)
    encoder = ClipEncoder(
        model_dir=settings.clip_models_path,
        phrase_cache_dir=settings.clip_phrase_cache_path,
        threads=settings.onnx_threads,
    )
    checks = reader.read()
    service = SafetyAssessmentService(
        encoder=encoder,
        region_finders={DETECTOR_SOURCE: PersonDetector()},
        checks=checks,
        person_padding=reader.read_padding(),
        classifiers=build_classifiers(checks),
    )
    return service


def main() -> int:
    """Разбирает материал и собирает по нему страницу."""
    parser = argparse.ArgumentParser(description="Проверка касок и жилетов")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--selection", default=str(DEFAULT_SELECTION))
    parser.add_argument("--reuse", action="store_true", help="не переразмечать готовые ролики")
    args = parser.parse_args()

    settings = Settings()
    service = build_service(settings)
    if not service.is_ready():
        logger.error("Проверки не настроены или не найдены веса CLIP")
        return 1
    selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    builder = PpeReportBuilder(
        assessment=service,
        annotator=VideoAnnotator(service),
        source_dir=Path(args.source),
        output_dir=Path(args.output),
        reuse_marked=args.reuse,
    )
    photos, videos = builder.build(selection)
    logger.info("Роликов %d, фотографий %d", len(videos), len(photos))
    for summary, _ in videos:
        logger.info("  %s: людей %d, отметок %d", summary.source, summary.people, summary.violations)
    for item in photos:
        logger.info("  %s: людей %d, отметок %d", item.source, len(item.people), len(item.violations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
