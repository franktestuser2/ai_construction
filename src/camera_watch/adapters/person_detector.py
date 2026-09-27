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
# Стоящий человек ростом 145 пикселей занимает в ширину полсотни, а не двадцать.
# Без этого правила детектор отдавал за человека узкую вертикальную полосу у края
# кадра — и отдавал её на каждом снимке подряд, набивая ленту одной и той же ошибкой.
MIN_WIDTH_TO_HEIGHT = 0.25
COLOR_SCALE = 255.0
MAX_REGIONS = 12
# Разбор по частям включается не по размеру кадра, а по тому, что на нём нашлось: если
# самый крупный человек мельче этого роста, кадр прогоняется ещё раз по частям. Причина
# в самой модели — она сжимает вход до 800 пикселей по короткой стороне, и на съёмке
# с дрона рабочий ростом в полтораста пикселей превращается в полсотни. На крупных планах
# части не нужны и вредны: они плодят находки на обрывках фигур.
TILE_TRIGGER_WIDTH = 1500
SMALL_PERSON_HEIGHT = 220
TILE_SIDE = 1100
TILE_OVERLAP = 0.2
SAME_BOX_IOU = 0.45


class PersonDetector:
    """Находит людей в кадре детектором COCO из torchvision."""

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        min_height: int = MIN_PERSON_HEIGHT,
        max_regions: int = MAX_REGIONS,
        min_ratio: float = MIN_WIDTH_TO_HEIGHT,
    ) -> None:
        self._score_threshold = score_threshold
        self._min_height = min_height
        self._max_regions = max_regions
        self._min_ratio = min_ratio
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
        boxes = self._detect_piece(frame)
        if frame.shape[1] <= TILE_TRIGGER_WIDTH:
            return boxes
        tallest = max((bottom - top for _, top, _, bottom in boxes), default=0)
        if tallest >= SMALL_PERSON_HEIGHT:
            return boxes
        found = self._detect_by_tiles(frame)
        return found

    def _detect_piece(self, piece: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Находит людей на одном изображении."""
        import torch

        tensor = self._to_tensor(piece)
        with self._lock:
            self._load()
            with torch.no_grad():
                output = self._model([tensor])[0]
        boxes = _filter_people(output, self._score_threshold, self._min_height, self._min_ratio)
        return boxes

    def _detect_by_tiles(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Разбирает крупный кадр по перекрывающимся частям и сводит найденное."""
        height, width = frame.shape[:2]
        step = int(TILE_SIDE * (1 - TILE_OVERLAP))
        found: list[tuple[int, int, int, int]] = []
        for top in range(0, height, step):
            for left in range(0, width, step):
                piece = frame[top : top + TILE_SIDE, left : left + TILE_SIDE]
                if piece.shape[0] < TILE_SIDE // 2 or piece.shape[1] < TILE_SIDE // 2:
                    continue
                found.extend(
                    (box[0] + left, box[1] + top, box[2] + left, box[3] + top)
                    for box in self._detect_piece(piece)
                )
        merged = _drop_duplicates(found)
        logger.info("Кадр %dx%d разобран по частям: людей %d", width, height, len(merged))
        return merged

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


def _filter_people(
    output: Any, score_threshold: float, min_height: int, min_ratio: float
) -> list[tuple[int, int, int, int]]:
    """Оставляет рамки людей, прошедшие пороги уверенности, роста и пропорций."""
    boxes: list[tuple[int, int, int, int]] = []
    for box, label, score in zip(output["boxes"], output["labels"], output["scores"]):
        if int(label) != PERSON_LABEL or float(score) < score_threshold:
            continue
        left, top, right, bottom = (int(round(float(value))) for value in box)
        if not _looks_like_person(right - left, bottom - top, min_height, min_ratio):
            continue
        boxes.append((left, top, right, bottom))
    return boxes


def _drop_duplicates(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Убирает повторы: на перекрытии частей один человек находится дважды."""
    ordered = sorted(boxes, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), reverse=True)
    kept: list[tuple[int, int, int, int]] = []
    for box in ordered:
        if all(_overlap(box, other) < SAME_BOX_IOU for other in kept):
            kept.append(box)
    return kept


def _overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    """Доля пересечения двух рамок."""
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    inner = max(0, right - left) * max(0, bottom - top)
    if inner == 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    share = inner / (first_area + second_area - inner)
    return share


def _looks_like_person(width: int, height: int, min_height: int, min_ratio: float) -> bool:
    """Проверяет рост и пропорции рамки: слишком узкая полоса человеком не бывает."""
    if height < min_height:
        return False
    fits = width / max(height, 1) >= min_ratio
    return fits
