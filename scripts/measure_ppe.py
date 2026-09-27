"""Замер обученных проверок СИЗ на отложенной выборке.

Пороги не выбираются на глаз: по отложенной выборке печатается, сколько нарушений
ловится и сколько отметок оказывается ложными при разных порогах. Числа из этой таблицы
и стоят в `config/safety_checks.json`.

Запуск: python scripts/measure_ppe.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2  # noqa: E402

from camera_watch.adapters.ppe_classifier import PpeClassifier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DATA_ROOT = Path("data/ppe_train")
WEIGHTS_ROOT = Path("models/ppe")
SPLIT = "test"
VIOLATION_CLASS = "0"
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def collect(kind: str) -> list[tuple[int, float]]:
    """Прогоняет отложенную выборку через классификатор."""
    classifier = PpeClassifier(WEIGHTS_ROOT / f"{kind}.pt")
    rows = []
    for label_dir in sorted((DATA_ROOT / kind / SPLIT).iterdir()):
        truth = 1 if label_dir.name == VIOLATION_CLASS else 0
        for path in sorted(label_dir.iterdir()):
            image = cv2.imread(str(path))
            if image is None:
                continue
            rows.append((truth, classifier.violation_probability(image)))
    return rows


def report(kind: str, rows: list[tuple[int, float]]) -> None:
    """Печатает рабочие точки проверки."""
    bad = [share for truth, share in rows if truth == 1]
    good = [share for truth, share in rows if truth == 0]
    pairs = sum(1 for a in bad for b in good if a > b)
    logger.info("\n%s: вырезок %d, из них с нарушением %d", kind, len(rows), len(bad))
    logger.info("AUC %.3f", pairs / (len(bad) * len(good)) if bad and good else 0.0)
    logger.info("%6s %9s %8s %9s %10s", "порог", "поймано", "ложных", "полнота", "точность")
    for threshold in THRESHOLDS:
        caught = sum(1 for share in bad if share >= threshold)
        false = sum(1 for share in good if share >= threshold)
        recall = caught / len(bad) if bad else 0.0
        precision = caught / (caught + false) if caught + false else 0.0
        logger.info("%6.2f %9d %8d %9.2f %10.2f", threshold, caught, false, recall, precision)


def main() -> int:
    """Считает и печатает рабочие точки обеих проверок."""
    for kind in ("head", "vest"):
        if not (WEIGHTS_ROOT / f"{kind}.pt").exists():
            logger.error("Нет весов: %s", WEIGHTS_ROOT / f"{kind}.pt")
            continue
        report(kind, collect(kind))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
