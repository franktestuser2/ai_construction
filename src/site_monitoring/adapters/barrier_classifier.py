"""Классификатор ограждений в проёме: есть нарушение ОТиПБ или нет.

ResNet-18 с одним выходом, обучен авторами фасадных моделей. Решение снимается
сигмоидой: значение выше порога означает нарушение. Проверяются только пустые
проёмы — в заложенный или остеклённый проём упасть нельзя.
"""

import logging
from pathlib import Path

import torch
from PIL import Image
from torchvision import models, transforms

logger = logging.getLogger(__name__)

FEATURE_COUNT = 512
OUTPUT_COUNT = 1
INPUT_SIDE = 224
NORMALIZE_MEAN = [0.485, 0.456, 0.406]
NORMALIZE_STD = [0.229, 0.224, 0.225]
MIN_CROP_SIDE = 2


class BarrierClassifier:
    """Адаптер проверки ограждений в пустых проёмах фасада."""

    def __init__(self, weights_path: Path, violation_threshold: float) -> None:
        self._weights_path = weights_path
        self._violation_threshold = violation_threshold
        self._model: torch.nn.Module | None = None
        self._transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Resize(size=(INPUT_SIDE, INPUT_SIDE)),
                transforms.Normalize(NORMALIZE_MEAN, NORMALIZE_STD),
            ]
        )

    def load(self) -> None:
        """Поднимает модель в память один раз на весь прогон."""
        if self._model is not None:
            return
        model = models.resnet18(weights=None)
        model.fc = torch.nn.Linear(FEATURE_COUNT, OUTPUT_COUNT, bias=True)
        state = torch.load(self._weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        self._model = model
        logger.info("Классификатор ограждений загружен: %s", self._weights_path.name)

    def classify(
        self,
        image_path: Path,
        boxes: tuple[tuple[float, float, float, float], ...],
    ) -> tuple[bool, ...]:
        """Возвращает по каждому проёму признак нарушения в установке ограждения.

        Рамки приходят в долях кадра, как и везде в фасадной ветке.
        """
        self.load()
        image = Image.open(image_path).convert("RGB")
        verdicts = [self._classify_box(image, box) for box in boxes]
        violations = tuple(verdict for verdict in verdicts if verdict is not None)
        logger.info(
            "Ограждения проверены на %d проёмах, нарушений %d",
            len(violations),
            sum(violations),
        )
        return violations

    def _classify_box(
        self,
        image: Image.Image,
        box: tuple[float, float, float, float],
    ) -> bool | None:
        """Проверяет один проём; слишком мелкие вырезы пропускает."""
        width, height = image.size
        left, top, right, bottom = (int(value * side) for value, side in zip(box, (width, height, width, height)))
        if right - left < MIN_CROP_SIDE or bottom - top < MIN_CROP_SIDE:
            return None
        piece = image.crop((left, top, right, bottom))
        tensor = self._transform(piece).unsqueeze(0)
        with torch.no_grad():
            logit = self._model(tensor)
        probability = float(torch.sigmoid(logit))
        violation = probability > self._violation_threshold
        return violation
