"""Замер проверок охраны труда на разметке сцен симулятора.

Зачем отдельный скрипт: пороги в `config/safety_checks.json` должны быть измерены, а не
выбраны на глаз, и замер должен воспроизводиться. Сцены и разметка к ним сделаны
генератором из репозитория `video-monitoring`, в разметке для каждого человека указано,
есть ли на нём каска и жилет.

Важно, что считается именно то правило, по которому сервис принимает решение: сначала
порог отрыва (иначе «не ясно»), и только потом порог уверенности. Меряя одну уверенность
в отрыве от этого правила, легко получить числа, которых в работе не бывает.

Запуск: python scripts/measure_safety_checks.py
"""

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camera_watch.adapters.camera_registry_reader import SafetyChecksReader  # noqa: E402
from camera_watch.adapters.clip_encoder import ClipEncoder  # noqa: E402
from camera_watch.entity import PRESENT, UNCLEAR, SafetyCheck  # noqa: E402
from camera_watch.services.safety_assessment import score_check  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

SCENES_DIR = Path("data/cameras/scenes")
TRUTH_FILE = SCENES_DIR / "ground_truth.json"
CHECKS_PATH = Path("config/safety_checks.json")
CLIP_DIR = Path("materials/external/video-monitoring-master/data/models/clip")
PHRASE_CACHE = Path("data/cache/clip_phrases")
SCENES = ("gate", "yard", "tower")
PERSON_CLASS = "person"
HELMET_KEY = "hasHelmet"
PADDING = 30
ONNX_THREADS = 2
THRESHOLDS = (0.55, 0.65, 0.75, 0.85, 0.95)
MARGINS = (0.002, 0.005, 0.010)


@dataclass(frozen=True, slots=True)
class Sample:
    """Одна область человека: что о ней говорит разметка и что ответила модель."""

    violation: bool
    confidence: float
    margin: float


def collect_samples(encoder: ClipEncoder, check: SafetyCheck) -> list[Sample]:
    """Прогоняет все размеченные области людей через проверку."""
    truth = json.loads(TRUTH_FILE.read_text(encoding="utf-8"))
    vectors = encoder.embed_phrases([*check.positive, *check.negative])
    samples: list[Sample] = []
    for scene in SCENES:
        samples.extend(_scene_samples(scene, truth, encoder, check, vectors))
    return samples


def _scene_samples(
    scene: str,
    truth: dict[str, object],
    encoder: ClipEncoder,
    check: SafetyCheck,
    vectors: dict[str, np.ndarray],
) -> list[Sample]:
    """Области людей одной сцены."""
    fps = float(truth["fps"])  # type: ignore[arg-type]
    capture = cv2.VideoCapture(str(SCENES_DIR / f"{scene}.mp4"))
    samples: list[Sample] = []
    for record in truth["scenes"][scene]["samples"]:  # type: ignore[index]
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(record["t"] * fps))
        ok, frame = capture.read()
        if not ok:
            break
        samples.extend(_frame_samples(frame, record, encoder, check, vectors))
    capture.release()
    return samples


def _frame_samples(
    frame: np.ndarray,
    record: dict[str, object],
    encoder: ClipEncoder,
    check: SafetyCheck,
    vectors: dict[str, np.ndarray],
) -> list[Sample]:
    """Области людей одного кадра."""
    samples: list[Sample] = []
    for item in record["objects"]:  # type: ignore[index]
        if item["class"] != PERSON_CLASS:
            continue
        crop = _crop(frame, item["bbox"])
        if crop.size == 0:
            continue
        finding = score_check(check, encoder.embed_image(crop), vectors, None)
        samples.append(Sample(not item[HELMET_KEY], finding.confidence, finding.margin))
    return samples


def _crop(frame: np.ndarray, box: list[int]) -> np.ndarray:
    """Вырезает область с запасом, как это делает сервис."""
    height, width = frame.shape[:2]
    left, top, right, bottom = box
    piece = frame[
        max(0, top - PADDING) : min(height, bottom + PADDING),
        max(0, left - PADDING) : min(width, right + PADDING),
    ]
    return piece


def report(samples: list[Sample]) -> None:
    """Печатает рабочие точки: сколько поймано, сколько ложных, сколько «не ясно»."""
    positives = sum(1 for item in samples if item.violation)
    print(f"областей людей: {len(samples)}, из них без каски по разметке: {positives}")
    print(f"{'отрыв':>7} {'порог':>6} {'поймано':>8} {'ложных':>7} {'не ясно':>8} {'полнота':>8} {'точность':>9}")
    for min_margin in MARGINS:
        for threshold in THRESHOLDS:
            _report_point(samples, threshold, min_margin, positives)


def _report_point(samples: list[Sample], threshold: float, min_margin: float, positives: int) -> None:
    """Одна строка отчёта по паре порогов."""
    verdicts = [(item.violation, _verdict(item, threshold, min_margin)) for item in samples]
    caught = sum(1 for violation, verdict in verdicts if violation and verdict == PRESENT)
    false = sum(1 for violation, verdict in verdicts if not violation and verdict == PRESENT)
    unclear = sum(1 for _, verdict in verdicts if verdict == UNCLEAR)
    recall = caught / positives if positives else 0.0
    precision = caught / (caught + false) if caught + false else 0.0
    print(
        f"{min_margin:>7.3f} {threshold:>6.2f} {caught:>8} {false:>7} {unclear:>8}"
        f" {recall:>8.2f} {precision:>9.2f}"
    )


def _verdict(sample: Sample, threshold: float, min_margin: float) -> str:
    """Правило вердикта сервиса, применённое к замеру."""
    if abs(sample.margin) < min_margin:
        return UNCLEAR
    return PRESENT if sample.confidence >= threshold else "нет"


def main() -> int:
    """Считает и печатает рабочие точки проверки каски."""
    checks = SafetyChecksReader(CHECKS_PATH).read()
    if not checks:
        logger.error("В конфигурации нет ни одной проверки")
        return 1
    encoder = ClipEncoder(CLIP_DIR, PHRASE_CACHE, ONNX_THREADS)
    if not encoder.is_available():
        logger.error("Веса CLIP не найдены: %s", CLIP_DIR)
        return 1
    for check in checks:
        print(f"\nпроверка: {check.title}")
        report(collect_samples(encoder, check))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
