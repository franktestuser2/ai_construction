"""Чтение картинки камеры.

Источник бывает двух видов, и они ведут себя по-разному.

**Живой поток** (`https://…m3u8`, `rtsp://…`) читается только с текущего места: перемотки
у него нет, «секунда ролика» смысла не имеет, а открытие соединения стоит секунду-две,
поэтому сведения о потоке запоминаются. OpenCV собран с FFmpeg, так что HLS и RTSP он
открывает сам — отдельный медиасервер для этого не нужен.

**Ролик на диске** крутится по кругу, и его положение считается от часов сервера: иначе
двое смотрящих видели бы разные секунды одной камеры, а снятый по расписанию кадр не
совпадал бы с тем, что в это время показывали.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from camera_watch.entity import STREAM_SCHEMES

logger = logging.getLogger(__name__)

JPEG_SUFFIX = ".jpg"
JPEG_QUALITY = 80
DEFAULT_FPS = 10.0
MIN_FPS = 1.0
MAX_FPS = 60.0
SEGMENT_CODEC = "mp4v"
# Живой поток отдаёт кадры сам в своём темпе, поэтому паузы между чтениями не нужны:
# лишние кадры просто не уходят зрителю.
LIVE_DELAY = 0.0
OPEN_TIMEOUT_MS = 15000
# Картинка для браузера: камера снимает в 1920x1080 и 25 кадрах, но показывать столько
# незачем — без этих двух ограничений один зритель съедал по сорок мегабайт в секунду.
STREAM_MAX_WIDTH = 900
STREAM_FPS = 5.0
STREAM_QUALITY = 70


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Что известно о картинке камеры."""

    fps: float
    frame_count: int
    width: int
    height: int
    live: bool = False

    @property
    def duration_seconds(self) -> float:
        """Длительность ролика; у живого потока её нет."""
        if self.live or not self.fps:
            return 0.0
        seconds = self.frame_count / self.fps
        return seconds


class VideoSource:
    """Даёт кадры камеры: живым потоком или роликом с диска."""

    def __init__(self, source: str) -> None:
        self._source = str(source)
        self._live = self._source.startswith(STREAM_SCHEMES)
        self._info: SourceInfo | None = None

    @property
    def is_live(self) -> bool:
        """Живой поток или файл."""
        return self._live

    def exists(self) -> bool:
        """Доступен ли источник. У потока это проверяется только попыткой открыть."""
        if self._live:
            return True
        found = Path(self._source).exists()
        return found

    def describe(self) -> SourceInfo:
        """Частота кадров, их число и размер картинки.

        У живого потока сведения запоминаются: открытие соединения стоит секунду-две,
        а меняться там нечему.
        """
        if self._info is not None:
            return self._info
        capture = self._open()
        info = _read_info(capture, self._live)
        capture.release()
        if self._live:
            self._info = info
        return info

    def read_at(self, second: float) -> np.ndarray | None:
        """Кадр камеры. У живого потока берётся текущий, секунда не используется."""
        capture = self._open()
        if not self._live:
            self._seek(capture, second)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            logger.warning("Камера %s не отдала кадр", self._short_name())
            return None
        return frame

    def read_sequence(self, start_second: float, count: int, step_frames: int) -> list[np.ndarray]:
        """Подряд идущие кадры.

        Нужны вычитанию фона: по одному кадру движение не определить. У живого потока
        это кадры, пришедшие сейчас, у ролика — начиная с заданной секунды.
        """
        capture = self._open()
        frames = (
            _read_live_sequence(capture, count, step_frames)
            if self._live
            else self._read_file_sequence(capture, start_second, count, step_frames)
        )
        capture.release()
        return frames

    def encode_jpeg(self, frame: np.ndarray, max_width: int = 0) -> bytes:
        """Кадр в JPEG для показа в браузере, при надобности уменьшенный."""
        import cv2

        picture = _fit_width(frame, max_width) if max_width else frame
        quality = STREAM_QUALITY if max_width else JPEG_QUALITY
        ok, buffer = cv2.imencode(JPEG_SUFFIX, picture, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return b""
        return buffer.tobytes()

    def stream_jpeg(self, start_second: float, seconds: float) -> Iterator[bytes]:
        """Отдаёт кадры JPEG подряд — это и есть «онлайн».

        Поток ограничен по времени намеренно: вкладку браузера оставляют открытой на
        часы, а каждый открытый поток держит на сервере свой декодер. По исчерпании
        лимита картинка замирает, и страница открывает поток заново.
        """
        capture = self._open()
        info = self.describe()
        if not self._live:
            self._seek(capture, start_second)
        delay = LIVE_DELAY if self._live else 1.0 / info.fps
        # Темп отдачи считается по часам, а не по числу прочитанных кадров: живой поток
        # отдаёт накопленный буфер быстрее реального времени, и счётчик кадров дал бы
        # вместо пяти кадров в секунду двести.
        step = 1.0 / STREAM_FPS
        deadline = time.monotonic() + seconds
        next_frame = 0.0
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            ok, frame = capture.read()
            if not ok:
                if self._live:
                    break
                self._seek(capture, 0.0)
                continue
            if now >= next_frame:
                next_frame = now + step
                yield self.encode_jpeg(frame, STREAM_MAX_WIDTH)
            if delay:
                time.sleep(delay)
        capture.release()

    def save_segment(self, start_second: float, seconds: float, target: Path) -> Path | None:
        """Пишет кусок записи в файл — доказательство к событию."""
        import cv2

        info = self.describe()
        frames = self.read_sequence(start_second, int(seconds * info.fps), step_frames=1)
        if not frames:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        codec = cv2.VideoWriter_fourcc(*SEGMENT_CODEC)
        height, width = frames[0].shape[:2]
        writer = cv2.VideoWriter(str(target), codec, info.fps, (width, height))
        for frame in frames:
            writer.write(frame)
        writer.release()
        logger.info("Записан отрезок %s (%d кадров)", target.name, len(frames))
        return target

    def _open(self):  # type: ignore[no-untyped-def]
        """Открывает источник."""
        import cv2

        capture = cv2.VideoCapture(self._source)
        if self._live:
            capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS)
        return capture

    def _seek(self, capture, second: float) -> None:  # type: ignore[no-untyped-def]
        """Ставит ролик на нужную секунду."""
        import cv2

        info = self.describe()
        index = int(second * info.fps) % max(info.frame_count, 1)
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)

    def _read_file_sequence(
        self, capture, start_second: float, count: int, step_frames: int
    ) -> list[np.ndarray]:  # type: ignore[no-untyped-def]
        """Кадры ролика с перемоткой по кругу."""
        import cv2

        info = self.describe()
        total = max(info.frame_count, 1)
        frames: list[np.ndarray] = []
        for number in range(count):
            index = (int(start_second * info.fps) + number * step_frames) % total
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if ok:
                frames.append(frame)
        return frames

    def _short_name(self) -> str:
        """Короткое имя источника для журнала."""
        name = self._source if self._live else Path(self._source).name
        return name


def _read_live_sequence(capture, count: int, step_frames: int) -> list[np.ndarray]:  # type: ignore[no-untyped-def]
    """Кадры живого потока подряд: перемотки у него нет, читаем что приходит."""
    frames: list[np.ndarray] = []
    for number in range(count * step_frames):
        ok, frame = capture.read()
        if not ok:
            break
        if number % step_frames == 0:
            frames.append(frame)
    return frames


def _fit_width(frame: np.ndarray, max_width: int) -> np.ndarray:
    """Уменьшает кадр под ширину показа, не трогая пропорции."""
    import cv2

    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / width
    smaller = cv2.resize(frame, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)
    return smaller


def _read_info(capture, live: bool) -> SourceInfo:  # type: ignore[no-untyped-def]
    """Снимает свойства источника с открытого соединения."""
    import cv2

    fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
    info = SourceInfo(
        fps=min(max(fps, MIN_FPS), MAX_FPS),
        frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        live=live,
    )
    return info
