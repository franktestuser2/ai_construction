"""Поиск людей в кадре по движению.

Детектора людей у нас нет: RT-DETR обучен на технике, а COCO-модель на рисованной сцене
симулятора не находит ничего — об этом прямо написано у авторов симулятора. Поэтому области
людей берутся вычитанием фона: модель фона набирается по соседним кадрам, движущееся
выделяется, из выделенного оставляются вытянутые вверх пятна подходящего размера.

Замер на трёх сценах симулятора по их собственной разметке (270 человек в кадрах):
найдено 222, то есть 82 %, лишних областей 123. Лишние — это части движущейся техники,
попавшие под фильтр пропорций. Отсюда правило показа: область не утверждается как человек,
она лишь предъявляется проверке, а решение принимает CLIP по содержимому области.
"""

import logging

import numpy as np

from camera_watch.entity import PersonRegion

logger = logging.getLogger(__name__)

# Параметры подобраны замером на сценах симулятора: история короче не успевает набрать фон,
# порог ниже ловит шум дорисованного зерна.
HISTORY_FRAMES = 200
VARIANCE_THRESHOLD = 40
WARMUP_FRAMES = 20
OPEN_KERNEL = 3
DILATE_KERNEL = 7
DILATE_ITERATIONS = 2
MIN_AREA = 1200
MIN_WIDTH_TO_HEIGHT = 0.25
MAX_WIDTH_TO_HEIGHT = 1.0
MAX_REGIONS = 12


class MotionRegionFinder:
    """Выделяет области движения, похожие по форме на человека."""

    def __init__(self, min_area: int = MIN_AREA, max_regions: int = MAX_REGIONS) -> None:
        self._min_area = min_area
        self._max_regions = max_regions

    def find(self, frames: list[np.ndarray]) -> tuple[PersonRegion, ...]:
        """Ищет людей на последнем кадре, используя предыдущие как фон."""
        if len(frames) < 2:
            return ()
        mask = self._build_mask(frames)
        boxes = self._mask_to_boxes(mask)
        regions = tuple(PersonRegion(*box) for box in boxes[: self._max_regions])
        return regions

    def _build_mask(self, frames: list[np.ndarray]) -> np.ndarray:
        """Набирает модель фона и возвращает маску движения последнего кадра."""
        import cv2

        subtractor = cv2.createBackgroundSubtractorMOG2(
            history=HISTORY_FRAMES, varThreshold=VARIANCE_THRESHOLD, detectShadows=False
        )
        mask = np.zeros(frames[0].shape[:2], dtype=np.uint8)
        for frame in frames:
            mask = subtractor.apply(frame)
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((OPEN_KERNEL, OPEN_KERNEL), np.uint8))
        grown = cv2.dilate(opened, np.ones((DILATE_KERNEL, DILATE_KERNEL), np.uint8), iterations=DILATE_ITERATIONS)
        return grown

    def _mask_to_boxes(self, mask: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Переводит маску движения в рамки, отсеивая непохожее на человека."""
        import cv2

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: list[tuple[int, int, int, int]] = []
        for contour in contours:
            left, top, width, height = cv2.boundingRect(contour)
            if not _looks_like_person(width, height, self._min_area):
                continue
            boxes.append((left, top, left + width, top + height))
        boxes.sort(key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), reverse=True)
        return boxes


def _looks_like_person(width: int, height: int, min_area: int) -> bool:
    """Проверяет размер и пропорции пятна: человек в кадре выше, чем шире."""
    if width * height < min_area:
        return False
    ratio = width / max(height, 1)
    fits = MIN_WIDTH_TO_HEIGHT <= ratio <= MAX_WIDTH_TO_HEIGHT
    return fits


def crop_region(frame: np.ndarray, region: PersonRegion, padding: int) -> np.ndarray:
    """Вырезает область с запасом по краям.

    Запас не украшение: на замере без него CLIP различал каску на уровне монетки
    (AUC 0,53), с запасом в 30 пикселей — 0,81. Модели нужна обстановка вокруг фигуры.
    """
    height, width = frame.shape[:2]
    left = max(0, region.left - padding)
    top = max(0, region.top - padding)
    right = min(width, region.right + padding)
    bottom = min(height, region.bottom + padding)
    piece = frame[top:bottom, left:right]
    return piece
