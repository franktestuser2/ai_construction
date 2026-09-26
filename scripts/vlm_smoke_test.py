"""Проба подключения к мультимодальной модели того провайдера, что выбран в настройках.

Проверяет на реальном снимке три вещи: доступность API, умение модели видеть технику,
которой нет в словаре детектора, и соблюдение схемы ответа. Провайдер берётся из
`VLM_PROVIDER`, поэтому одним и тем же прогоном проверяются и DeepSeek, и запасная
модель Yandex Cloud AI Studio.
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Settings  # noqa: E402
from site_monitoring.adapters.vlm_client import VlmClient  # noqa: E402
from site_monitoring.container import build_vlm_transport  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")

DEFAULT_IMAGE_PATH = Path("data/photos_v2/W03/W03_2026-11-27_frame47.jpg")
WORK_NAME = "Разработка грунта в котловане с креплением стенок"
QUESTIONS = (
    ("Экскаватор", "есть ли на снимке экскаватор и работает ли он"),
    ("Самосвал", "есть ли на снимке самосвал и работает ли он"),
    ("Башенный кран", "есть ли на снимке башенный кран и работает ли он"),
    ("Бетононасос", "есть ли на снимке бетононасос и работает ли он"),
)
NO_TRANSPORT_MESSAGE = "Ключ выбранного провайдера не задан: проверять нечего"
EXIT_CODE_NO_ACCESS = 1


def main() -> int:
    """Запрашивает у модели разбор снимка и печатает ответ с замером времени."""
    settings = Settings()
    transport = build_vlm_transport(settings)
    if transport is None:
        logging.error(NO_TRANSPORT_MESSAGE)
        return EXIT_CODE_NO_ACCESS
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE_PATH
    client = VlmClient(transport)
    logging.info("Провайдер: %s, снимок: %s", settings.vlm_provider.value, image_path.name)
    started = time.monotonic()
    answer = client.assess_frame(image_path, WORK_NAME, QUESTIONS)
    elapsed = time.monotonic() - started
    logging.info("Ответ за %.1f с:\n%s", elapsed, json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
