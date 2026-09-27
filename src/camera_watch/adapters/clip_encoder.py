"""CLIP: кадр и фраза в одном векторном пространстве.

Модель и подход взяты из репозитория `video-monitoring` (`backend/app/cv/clip_encoder.py`),
веса лежат там же — `data/models/clip`, квантованные vision и text ViT-B/32. Смысл в том,
что спросить «есть ли в кадре рабочий без каски» можно фразой, не собирая датасет и никого
не дообучая: детектор умеет ровно те классы, что были в обучении, а CLIP сравнивает смыслы.

Главное, что нужно знать про эти числа: **абсолютная близость не значит ничего**. Все
близости лежат в узкой полосе около 0,2-0,3, и порог на сырое значение был бы настройкой,
которая выглядит осмысленной и не работает. Решение принимается сравнением фразы «за» с
фразой «против» — этим занимается сервис `safety_assessment`, сюда он приходит за векторами.

Модели поднимаются лениво и остаются в памяти процесса: вместе они весят 154 МБ и грузятся
около секунды. Вектор фразы считается один раз и кладётся на диск, вектор кадра — каждый раз.
"""

import hashlib
import json
import logging
import math
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

VISION_FILE_NAME = "vision_model_quantized.onnx"
TEXT_FILE_NAME = "text_model_quantized.onnx"
TOKENIZER_FILE_NAME = "tokenizer.json"
# Длина контекста CLIP задана архитектурой, хвост добивается последним токеном.
CONTEXT_LENGTH = 77
EMBEDDING_SIZE = 512
END_OF_TEXT_TOKEN = 49407
INPUT_SIZE = 224
# Нормировка входа из preprocessor_config.json модели: с другими числами вектор кадра
# уезжает, и близости перестают что-либо значить.
IMAGE_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
IMAGE_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
COLOR_SCALE = 255.0
MIN_NORM = 1e-9
CACHE_NAME_LENGTH = 32
PIXEL_INPUT = "pixel_values"
TOKEN_INPUT = "input_ids"
CPU_PROVIDER = "CPUExecutionProvider"


class ClipEncoder:
    """Переводит кадры и фразы в векторы одного пространства."""

    def __init__(self, model_dir: Path, phrase_cache_dir: Path, threads: int) -> None:
        self._model_dir = model_dir
        self._phrase_cache_dir = phrase_cache_dir
        self._threads = threads
        self._lock = threading.Lock()
        self._vision: Any = None
        self._text: Any = None
        self._tokenizer: Any = None

    def is_available(self) -> bool:
        """Скачаны ли веса. Их отсутствие — штатное состояние, а не сбой."""
        vision = self._model_dir / VISION_FILE_NAME
        text = self._model_dir / TEXT_FILE_NAME
        ready = vision.exists() and text.exists()
        return ready

    def embed_image(self, image: np.ndarray) -> np.ndarray:
        """Вектор кадра BGR, приведённый к единичной длине."""
        prepared = self._prepare_image(image)
        with self._lock:
            self._load()
            raw = self._vision.run(None, {PIXEL_INPUT: prepared})[0]
        vector = _to_unit_vector(raw)
        return vector

    def embed_phrases(self, phrases: Sequence[str]) -> dict[str, np.ndarray]:
        """Векторы фраз: посчитанные раньше берутся с диска, новые считаются и туда же кладутся."""
        found: dict[str, np.ndarray] = {}
        missing: list[str] = []
        for phrase in phrases:
            cached = self._read_cached_phrase(phrase)
            if cached is None:
                missing.append(phrase)
                continue
            found[phrase] = cached
        if missing:
            found.update(self._encode_missing(missing))
        return found

    def _encode_missing(self, phrases: list[str]) -> dict[str, np.ndarray]:
        """Считает векторы фраз, которых нет в кеше, и сохраняет их."""
        computed: dict[str, np.ndarray] = {}
        with self._lock:
            self._load()
            for phrase in phrases:
                vector = self._encode_phrase(phrase)
                computed[phrase] = vector
                self._write_cached_phrase(phrase, vector)
        return computed

    def _encode_phrase(self, phrase: str) -> np.ndarray:
        """Вектор одной фразы."""
        ids = self._tokenizer.encode(phrase).ids[:CONTEXT_LENGTH]
        filler = ids[-1] if ids else END_OF_TEXT_TOKEN
        padded = ids + [filler] * (CONTEXT_LENGTH - len(ids))
        tokens = np.array([padded], dtype=np.int64)
        raw = self._text.run(None, {TOKEN_INPUT: tokens})[0]
        vector = _to_unit_vector(raw)
        return vector

    def _prepare_image(self, image: np.ndarray) -> np.ndarray:
        """Кадр BGR к входу CLIP: короткая сторона в 224, центральный кроп, нормировка.

        Центральный кроп означает, что края кадра модель не увидит, поэтому оценка кадра
        целиком — это оценка его середины. Для обзорной камеры важное в углу площадки в неё
        не попадёт: туда нужно подавать вырезанную область, а не весь кадр.
        """
        import cv2

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        scale = INPUT_SIZE / min(height, width)
        target = (max(INPUT_SIZE, round(width * scale)), max(INPUT_SIZE, round(height * scale)))
        resized = cv2.resize(rgb, target, interpolation=cv2.INTER_CUBIC)
        cropped = _center_crop(resized).astype(np.float32) / COLOR_SCALE
        normalized = (cropped - IMAGE_MEAN) / IMAGE_STD
        batch = normalized.transpose(2, 0, 1)[None]
        return batch

    def _load(self) -> None:
        """Поднимает модели и токенизатор при первом обращении."""
        if self._vision is not None:
            return
        import onnxruntime
        from tokenizers import Tokenizer

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = self._threads
        self._vision = onnxruntime.InferenceSession(
            str(self._model_dir / VISION_FILE_NAME), sess_options=options, providers=[CPU_PROVIDER]
        )
        self._text = onnxruntime.InferenceSession(
            str(self._model_dir / TEXT_FILE_NAME), sess_options=options, providers=[CPU_PROVIDER]
        )
        self._tokenizer = Tokenizer.from_file(str(self._model_dir / TOKENIZER_FILE_NAME))
        logger.info("CLIP поднят из %s", self._model_dir)

    def _cache_path(self, phrase: str) -> Path:
        """Путь файла с вектором фразы."""
        digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()[:CACHE_NAME_LENGTH]
        path = self._phrase_cache_dir / f"{digest}.json"
        return path

    def _read_cached_phrase(self, phrase: str) -> np.ndarray | None:
        """Читает вектор фразы с диска, если он там есть и цел."""
        path = self._cache_path(phrase)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Битый файл кеша — не повод падать: посчитаем заново и перезапишем.
            logger.warning("Кеш вектора фразы повреждён, считаю заново: %s", path.name)
            return None
        vector = np.asarray(payload, dtype=np.float32)
        return vector

    def _write_cached_phrase(self, phrase: str, vector: np.ndarray) -> None:
        """Кладёт вектор фразы на диск."""
        self._phrase_cache_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(vector.tolist())
        self._cache_path(phrase).write_text(payload, encoding="utf-8")


def _center_crop(image: np.ndarray) -> np.ndarray:
    """Вырезает середину кадра под вход модели."""
    height, width = image.shape[:2]
    top = (height - INPUT_SIZE) // 2
    left = (width - INPUT_SIZE) // 2
    piece = image[top : top + INPUT_SIZE, left : left + INPUT_SIZE]
    return piece


def _to_unit_vector(raw: np.ndarray) -> np.ndarray:
    """Приводит выход модели к вектору единичной длины."""
    flat = np.asarray(raw, dtype=np.float32).reshape(-1)[:EMBEDDING_SIZE]
    norm = float(np.linalg.norm(flat))
    if not math.isfinite(norm) or norm < MIN_NORM:
        return np.zeros(EMBEDDING_SIZE, dtype=np.float32)
    unit = (flat / norm).astype(np.float32)
    return unit
