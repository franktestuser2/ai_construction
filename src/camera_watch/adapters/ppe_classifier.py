"""Обученные классификаторы средств защиты: каска на голове и жилет на фигуре.

Пришли на смену сравнению текстовых фраз. Сравнение фраз удобно тем, что не требует
разметки, но на каске оно давало полноту 0,82 при точности 0,69 — каждая третья отметка
ложная. Разметка у открытых наборов есть, задача простая, и небольшая обученная сеть
решает её заметно лучше: на отложенной выборке 0,97 против 0,69.

Вырезки те же, что и в работе сервиса: голова с плечами из рамки человека и фигура
целиком. Обучение шло на них же — иначе обученное на чужих рамках не перенеслось бы.
"""

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

VIOLATION_INDEX = 0
DEFAULT_SIZE = 96
COLOR_SCALE = 255.0
STATE_KEY = "state"
SIZE_KEY = "size"


class PpeClassifier:
    """Говорит, есть ли на вырезке нарушение: голова без каски или фигура без жилета."""

    def __init__(self, weights_path: Path) -> None:
        self._weights_path = weights_path
        self._lock = threading.Lock()
        self._model: Any = None
        self._size = DEFAULT_SIZE

    def is_available(self) -> bool:
        """Есть ли веса на диске."""
        found = self._weights_path.exists()
        return found

    def violation_probability(self, crop: np.ndarray) -> float:
        """Вероятность того, что на вырезке нарушение."""
        import torch

        tensor = self._to_tensor(crop)
        with self._lock:
            self._load()
            with torch.no_grad():
                output = self._model(tensor)
                shares = torch.softmax(output, dim=1)[0]
        share = float(shares[VIOLATION_INDEX])
        return share

    def _to_tensor(self, crop: np.ndarray) -> Any:
        """Вырезка BGR к входу сети: размер сети, RGB, доли единицы."""
        import cv2
        import torch

        resized = cv2.resize(crop, (self._size, self._size), interpolation=cv2.INTER_AREA)
        rgb = resized[:, :, ::-1].copy().astype(np.float32) / COLOR_SCALE
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
        return tensor

    def _load(self) -> None:
        """Поднимает сеть при первом обращении."""
        if self._model is not None:
            return
        import torch
        from torchvision.models import resnet18

        payload = torch.load(self._weights_path, map_location="cpu", weights_only=False)
        model = resnet18()
        model.fc = torch.nn.Linear(model.fc.in_features, len(payload.get("classes", (0, 1))))
        model.load_state_dict(payload[STATE_KEY])
        model.eval()
        self._model = model
        self._size = int(payload.get(SIZE_KEY, DEFAULT_SIZE))
        logger.info("Классификатор СИЗ поднят: %s, вход %d", self._weights_path.name, self._size)
