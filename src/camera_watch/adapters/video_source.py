"""Чтение картинки камеры.

Источник камеры — видеофайл, который крутится по кругу: ролики симулятора площадки лежат
в проекте, и по ним показывается «онлайн». Настоящий RTSP читался бы этим же классом —
OpenCV открывает поток тем же вызовом, — но на этой машине нет ffmpeg, поэтому проверено
только на файлах, и обещать работу с регистратором мы не можем.

Положение в ролике считается от часов сервера, а не от момента открытия страницы: иначе
двое смотрящих видели бы разные секунды одной камеры, а снятый по расписанию кадр не
совпадал бы с тем, что в это время показывали.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

JPEG_SUFFIX = ".jpg"
JPEG_QUALITY = 80
DEFAULT_FPS = 10.0
MIN_FPS = 1.0
MAX_FPS = 60.0
SEGMENT_CODEC = "mp4v"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Что известно о ролике камеры."""

    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        """Длительность ролика."""
        seconds = self.frame_count / self.fps if self.fps else 0.0
        return seconds


class VideoSource:
    """Даёт кадры ролика камеры: по позиции, подряд и куском записи."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def exists(self) -> bool:
        """Есть ли файл источника на диске."""
        found = self._path.exists()
        return found

    def describe(self) -> SourceInfo:
        """Частота кадров, их число и размер картинки."""
        import cv2

        capture = cv2.VideoCapture(str(self._path))
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
        info = SourceInfo(
            fps=min(max(fps, MIN_FPS), MAX_FPS),
            frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        capture.release()
        return info

    def read_at(self, second: float) -> np.ndarray | None:
        """Кадр ролика на заданной секунде."""
        import cv2

        info = self.describe()
        capture = cv2.VideoCapture(str(self._path))
        index = int(second * info.fps) % max(info.frame_count, 1)
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            logger.warning("Кадр %d не прочитан из %s", index, self._path.name)
            return None
        return frame

    def read_sequence(self, start_second: float, count: int, step_frames: int) -> list[np.ndarray]:
        """Подряд идущие кадры, начиная с заданной секунды.

        Нужны вычитанию фона: по одному кадру движение не определить, модель фона
        набирается на нескольких соседних.
        """
        import cv2

        info = self.describe()
        capture = cv2.VideoCapture(str(self._path))
        total = max(info.frame_count, 1)
        frames: list[np.ndarray] = []
        for number in range(count):
            index = (int(start_second * info.fps) + number * step_frames) % total
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if ok:
                frames.append(frame)
        capture.release()
        return frames

    def encode_jpeg(self, frame: np.ndarray) -> bytes:
        """Кадр в JPEG для показа в браузере."""
        import cv2

        ok, buffer = cv2.imencode(JPEG_SUFFIX, frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            return b""
        return buffer.tobytes()

    def stream_jpeg(self, start_second: float, seconds: float) -> Iterator[bytes]:
        """Отдаёт кадры JPEG подряд в темпе ролика — это и есть «онлайн».

        Поток ограничен по времени намеренно: вкладку браузера оставляют открытой на
        часы, а каждый открытый поток держит на сервере свой декодер. По исчерпании
        лимита картинка замирает, и страница открывает поток заново.
        """
        import cv2

        info = self.describe()
        capture = cv2.VideoCapture(str(self._path))
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(start_second * info.fps))
        delay = 1.0 / info.fps
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ok, frame = capture.read()
            if not ok:
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            yield self.encode_jpeg(frame)
            time.sleep(delay)
        capture.release()

    def save_segment(self, start_second: float, seconds: float, target: Path) -> Path | None:
        """Пишет кусок ролика в файл — запись-доказательство к событию."""
        import cv2

        info = self.describe()
        frames = self.read_sequence(start_second, int(seconds * info.fps), step_frames=1)
        if not frames:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        codec = cv2.VideoWriter_fourcc(*SEGMENT_CODEC)
        writer = cv2.VideoWriter(str(target), codec, info.fps, (info.width, info.height))
        for frame in frames:
            writer.write(frame)
        writer.release()
        logger.info("Записан отрезок %s (%d кадров)", target.name, len(frames))
        return target
