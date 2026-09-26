"""Детектор строительной техники на снимке: дообученная модель RT-DETR.

Веса и порог уверенности приходят из контейнера; переменные окружения
адаптер не читает.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from ..entity import EquipmentSource, EquipmentStatus, ObservedEquipment

logger = logging.getLogger(__name__)

CPU_DEVICE = "cpu"
CUDA_DEVICE = "cuda"
SCORE_KEY = "scores"
LABEL_KEY = "labels"
BOX_KEY = "boxes"


@dataclass
class _ClassFindings:
    """Накопитель находок одного класса на снимке."""

    count: int
    confidence: float
    boxes: list[tuple[float, float, float, float]]


class EquipmentDetector:
    """Адаптер поиска техники на снимке дообученной моделью RT-DETR."""

    def __init__(self, weights_path: Path, confidence_threshold: float) -> None:
        self._weights_path = weights_path
        self._confidence_threshold = confidence_threshold
        self._processor: AutoImageProcessor | None = None
        self._model: AutoModelForObjectDetection | None = None
        self._device = CUDA_DEVICE if torch.cuda.is_available() else CPU_DEVICE
        # Кадры разбираются параллельно, а модель одна на всех: без замка
        # два потока начали бы поднимать её одновременно.
        self._load_lock = threading.Lock()

    def load(self) -> None:
        """Загружает веса и препроцессор в память."""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            self._processor = AutoImageProcessor.from_pretrained(self._weights_path)
            model = AutoModelForObjectDetection.from_pretrained(self._weights_path)
            model.to(self._device)
            model.eval()
            self._model = model
        logger.info("Детектор загружен из %s на устройство %s", self._weights_path.name, self._device)

    def detect(self, image_path: Path) -> tuple[ObservedEquipment, ...]:
        """Находит технику на снимке и группирует её по классам модели."""
        self.load()
        image = Image.open(image_path).convert("RGB")
        results = self._run_model(image)
        counts = self._count_by_class(results, image.size)
        equipment = tuple(
            ObservedEquipment(
                machine_type=machine_type,
                source=EquipmentSource.DETECTOR,
                status=EquipmentStatus.NOT_APPLICABLE,
                count=found.count,
                confidence=found.confidence,
                boxes=tuple(found.boxes),
            )
            for machine_type, found in sorted(counts.items())
        )
        logger.info("Снимок %s: классов техники %d", image_path.name, len(equipment))
        return equipment

    def _run_model(self, image: Image.Image) -> dict[str, torch.Tensor]:
        """Прогоняет снимок через модель и отбирает находки выше порога."""
        inputs = self._processor(images=image, return_tensors="pt").to(self._device)  # type: ignore[union-attr]
        with torch.no_grad():
            outputs = self._model(**inputs)  # type: ignore[misc]
        target_sizes = torch.tensor([image.size[::-1]], device=self._device)
        processed = self._processor.post_process_object_detection(  # type: ignore[union-attr]
            outputs,
            threshold=self._confidence_threshold,
            target_sizes=target_sizes,
        )
        results = processed[0]
        return results

    def _count_by_class(
        self,
        results: dict[str, torch.Tensor],
        image_size: tuple[int, int],
    ) -> dict[str, "_ClassFindings"]:
        """Считает находки по каждому классу и запоминает их рамки."""
        labels = self._model.config.id2label  # type: ignore[union-attr]
        counts: dict[str, _ClassFindings] = {}
        width, height = image_size
        for score, label, box in zip(results[SCORE_KEY], results[LABEL_KEY], results[BOX_KEY]):
            machine_type = labels[int(label)]
            confidence = float(score)
            relative = self._relative_box(box, width, height)
            current = counts.get(machine_type)
            if current is None:
                counts[machine_type] = _ClassFindings(1, confidence, [relative])
                continue
            current.count += 1
            current.confidence = max(current.confidence, confidence)
            current.boxes.append(relative)
        return counts

    def _relative_box(self, box: torch.Tensor, width: int, height: int) -> tuple[float, float, float, float]:
        """Переводит рамку в доли размера снимка, чтобы её можно было нарисовать поверх любой копии."""
        left, top, right, bottom = (float(value) for value in box)
        relative = (
            round(left / width, 4),
            round(top / height, 4),
            round(right / width, 4),
            round(bottom / height, 4),
        )
        return relative
