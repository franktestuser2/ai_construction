"""Прогон проверок СИЗ по фотографиям и роликам, лежащим в папке.

Зачем отдельно от камер: проверка каски и жилета работает на крупных планах, а камеры
объекта обзорные — человек занимает в них два десятка пикселей. Этот прогон показывает,
на каком материале проверка работает, и его же результат идёт на страницу сервиса.

Запуск: python scripts/check_ppe.py [--source data/ppe_demo] [--step 3]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camera_watch.adapters.camera_registry_reader import SafetyChecksReader  # noqa: E402
from camera_watch.adapters.clip_encoder import ClipEncoder  # noqa: E402
from camera_watch.adapters.person_detector import PersonDetector  # noqa: E402
from camera_watch.entity import DETECTOR_SOURCE  # noqa: E402
from camera_watch.services.safety_assessment import SafetyAssessmentService  # noqa: E402
from config import Settings  # noqa: E402
from ppe_report import PpeReportBuilder  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SOURCE = Path("data/ppe_demo")
DEFAULT_OUTPUT = Path("docs/ppe")
DEFAULT_STEP_SECONDS = 3.0


def build_service(settings: Settings) -> SafetyAssessmentService:
    """Собирает разбор СИЗ: люди детектором, признаки — сравнением фраз."""
    reader = SafetyChecksReader(settings.safety_checks_path)
    encoder = ClipEncoder(
        model_dir=settings.clip_models_path,
        phrase_cache_dir=settings.clip_phrase_cache_path,
        threads=settings.onnx_threads,
    )
    service = SafetyAssessmentService(
        encoder=encoder,
        region_finders={DETECTOR_SOURCE: PersonDetector()},
        checks=reader.read(),
        person_padding=reader.read_padding(),
    )
    return service


def main() -> int:
    """Разбирает материал и собирает по нему страницу."""
    parser = argparse.ArgumentParser(description="Проверка касок и жилетов")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--step", type=float, default=DEFAULT_STEP_SECONDS)
    args = parser.parse_args()

    settings = Settings()
    service = build_service(settings)
    if not service.is_ready():
        logger.error("Проверки не настроены или не найдены веса CLIP")
        return 1
    builder = PpeReportBuilder(
        assessment=service,
        source_dir=Path(args.source),
        output_dir=Path(args.output),
        video_step_seconds=args.step,
    )
    results = builder.build()
    people = sum(len(item.people) for item in results)
    marks = sum(len(item.violations) for item in results)
    logger.info("Кадров %d, людей %d, отметок %d", len(results), people, marks)
    for item in results:
        if item.violations:
            found = ", ".join(sorted({finding.title for finding in item.violations}))
            logger.info("  %s: %s", item.title, found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
