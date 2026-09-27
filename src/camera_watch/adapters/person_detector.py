"""Поиск людей в кадре обученным детектором.

Второй способ найти людей — рядом с вычитанием фона. Разделение не про вкус: на
рисованной сцене симулятора модель, обученная на фотографиях, не находит ничего, а на
настоящем кадре вычитание фона путает человека с куском движущейся техники. Поэтому
источник людей задаётся у камеры: синтетике — движение, настоящей камере — детектор.

Модель и порог роста взяты из разбора набора ОТиПБ (`docs/ppe_dataset.md`): человек ниже
80 пикселей не годится для суждения о каске — она занимает на нём считаные пиксели, и
отказ честнее выдумки.
"""

import logging
import threading
from typing import Any

import numpy as np

from camera_watch.entity import PersonRegion

logger = logging.getLogger(__name__)

PERSON_LABEL = 1
SCORE_THRESHOLD = 0.5
MIN_PERSON_HEIGHT = 80
COLOR_SCALE = 255.0
MAX_REGIONS = 12


class PersonDetector:
    """Находит людей в кадре детектором COCO из torchvision."""

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        min_height: int = MIN_PERSON_HEIGHT,
        max_regions: int = MAX_REGIONS,
    ) -> None:
        self._score_threshold = score_threshold
        self._min_height = min_height
        self._max_regions = max_regions
        self._lock = threading.Lock()
        self._model: Any = None

    def find(self, frames: list[np.ndarray]) -> tuple[PersonRegion, ...]:
        """Ищет людей на последнем кадре; предыстория детектору не нужна."""
        if not frames:
            return ()
        boxes = self._detect(frames[-1])
        regions = tuple(PersonRegion(*box) for box in boxes[: self._max_regions])
        return regions

    def _detect(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Прогоняет кадр через детектор и оставляет людей подходящего роста."""
        import torch

        tensor = self._to_tensor(frame)
        with self._lock:
            self._load()
            with torch.no_grad():
                output = self._model([tensor])[0]
        boxes = _filter_people(output, self._score_threshold, self._min_height)
        return boxes

    def _to_tensor(self, frame: np.ndarray) -> Any:
        """Кадр BGR к входу torchvision: RGB, доли единицы, каналы впереди."""
        import torch

        rgb = frame[:, :, ::-1].copy().astype(np.float32) / COLOR_SCALE
        tensor = torch.from_numpy(rgb).permute(2, 0, 1)
        return tensor

    def _load(self) -> None:
        """Поднимает детектор при первом обращении."""
        if self._model is not None:
            return
        from torchvision.models.detection import (
            FasterRCNN_ResNet50_FPN_V2_Weights,
            fasterrcnn_resnet50_fpn_v2,
        )

        weights = FasterRCNN_ResNet50_FPN_V2_Weights.COCO_V1
        self._model = fasterrcnn_resnet50_fpn_v2(weights=weights)
        self._model.eval()
        logger.info("Детектор людей поднят, веса %s", weights.name)


def _filter_people(output: Any, score_threshold: float, min_height: int) -> list[tuple[int, int, int, int]]:
    """Оставляет рамки людей, прошедшие порог уверенности и порог роста."""
    boxes: list[tuple[int, int, int, int]] = []
    for box, label, score in zip(output["boxes"], output["labels"], output["scores"]):
        if int(label) != PERSON_LABEL or float(score) < score_threshold:
            continue
        left, top, right, bottom = (int(round(float(value))) for value in box)
        if bottom - top < min_height:
            continue
        boxes.append((left, top, right, bottom))
    return boxes
