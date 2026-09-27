"""Оркестрация контура наблюдения за камерами.

Один вход для всего, что умеет контур: показать картинку камеры, снять кадр по расписанию,
проверить его на нарушения охраны труда, положить в архив и передать основному сервису.
"""

import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from camera_watch.adapters.camera_registry_reader import CameraRegistryReader
from camera_watch.adapters.frame_archive import FrameArchive, with_findings
from camera_watch.adapters.main_service_client import MainServiceClient
from camera_watch.adapters.video_source import VideoSource
from camera_watch.entity import (
    Camera,
    CameraState,
    CapturedFrame,
    CaptureOutcome,
    PersonRegion,
    SafetyCheck,
    SafetyFinding,
)
from camera_watch.services.capture_planner import (
    capture_position,
    is_due,
    next_capture_at,
    position_seconds,
)
from camera_watch.services.safety_assessment import SafetyAssessmentService

logger = logging.getLogger(__name__)

# Вычитанию фона нужна история: по одному кадру движение не определить.
BACKGROUND_FRAMES = 12
BACKGROUND_STEP = 2
EVENT_CLIP_SECONDS = 6.0
NO_SOURCE_NOTE = "Файл камеры не найден"
NO_FRAME_NOTE = "Кадр не прочитан"
NO_SAFETY_NOTE = "Проверка охраны труда выключена для этой камеры"
NO_MODEL_NOTE = "Веса CLIP не найдены, проверка охраны труда пропущена"
NOTHING = 0


class CameraWatchFacade:
    """Всё, что делает контур наблюдения."""

    def __init__(
        self,
        registry: CameraRegistryReader,
        archive: FrameArchive,
        assessment: SafetyAssessmentService,
        client: MainServiceClient,
    ) -> None:
        self._registry = registry
        self._archive = archive
        self._assessment = assessment
        self._client = client
        self._cameras: tuple[Camera, ...] = ()
        self._sources: dict[str, VideoSource] = {}

    def cameras(self) -> tuple[Camera, ...]:
        """Камеры площадки."""
        if not self._cameras:
            self._cameras = self._registry.read()
            self._sources = {item.camera_id: VideoSource(item.source) for item in self._cameras}
        return self._cameras

    def camera(self, camera_id: str) -> Camera | None:
        """Одна камера по идентификатору."""
        found = next((item for item in self.cameras() if item.camera_id == camera_id), None)
        return found

    def source(self, camera_id: str) -> VideoSource | None:
        """Источник картинки камеры."""
        self.cameras()
        found = self._sources.get(camera_id)
        return found

    def states(self, moment: datetime) -> tuple[CameraState, ...]:
        """Состояние всех камер: когда снимали, что нашли, что не отправлено."""
        states = tuple(self._build_state(camera) for camera in self.cameras())
        return states

    def live_jpeg(self, camera_id: str, moment: datetime) -> bytes:
        """Картинка камеры на текущий момент."""
        source = self.source(camera_id)
        if source is None or not source.exists():
            return b""
        second = self.live_position(camera_id, moment)
        frame = source.read_at(second)
        if frame is None:
            return b""
        return source.encode_jpeg(frame)

    def live_position(self, camera_id: str, moment: datetime) -> float:
        """Секунда ролика, которую камера показывает сейчас."""
        source = self.source(camera_id)
        if source is None or not source.exists():
            return 0.0
        info = source.describe()
        second = position_seconds(moment, info.duration_seconds)
        return second

    def capture_position(self, camera: Camera, moment: datetime) -> float:
        """Секунда ролика, которую возьмёт съёмка по расписанию."""
        source = self.source(camera.camera_id)
        if source is None or not source.exists():
            return 0.0
        info = source.describe()
        second = capture_position(moment, info.duration_seconds, camera.capture_period_minutes)
        return second

    def capture(self, camera_id: str, moment: datetime) -> CaptureOutcome | None:
        """Снимает кадр камеры, проверяет его и кладёт в архив."""
        camera = self.camera(camera_id)
        source = self.source(camera_id)
        if camera is None or source is None or not source.exists():
            logger.warning("Камера %s недоступна для съёмки", camera_id)
            return None
        # Берём последовательность кадров: последний идёт в архив, предыдущие — на фон.
        second = self.capture_position(camera, moment)
        frames = self._read_history(source, second)
        if not frames:
            return None
        # Разбираем кадр проверками охраны труда.
        regions, findings, notes = self._run_safety(camera, frames)
        # Нарушение сопровождаем отрезком записи: по одному кадру спор не разрешить.
        violated = any(item.is_violation for item in findings)
        clip = self._store_clip(camera, source, second, moment) if violated else None
        # Кладём снимок, а следом опись с находками.
        outcome = self._store(camera, frames[-1], moment, second, notes)
        stored = with_findings(outcome.frame, regions, findings, clip.name if clip else "")
        self._archive.append(stored)
        outcome.frame = stored
        outcome.clip_path = clip
        return outcome

    def capture_due(self, moment: datetime) -> list[CaptureOutcome]:
        """Снимает те камеры, у которых подошёл срок съёмки."""
        outcomes: list[CaptureOutcome] = []
        for camera in self.cameras():
            frames = self._archive.list_frames(camera.camera_id)
            last = frames[0].captured_at if frames else None
            if not is_due(last, moment, camera.capture_period_minutes):
                continue
            outcome = self.capture(camera.camera_id, moment)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def next_capture(self, camera: Camera, moment: datetime) -> datetime:
        """Когда камера снимет следующий кадр."""
        frames = self._archive.list_frames(camera.camera_id)
        last = frames[0].captured_at if frames else None
        planned = next_capture_at(last, moment, camera.capture_period_minutes)
        return planned

    def frames(self, camera_id: str) -> tuple[CapturedFrame, ...]:
        """Архив снимков камеры."""
        stored = self._archive.list_frames(camera_id)
        return stored

    def photo_path(self, camera_id: str, name: str) -> Path:
        """Путь снимка из архива камеры."""
        path = self._archive.photo_path(camera_id, name)
        return path

    def clip_path(self, camera_id: str, name: str) -> Path:
        """Путь отрезка записи камеры."""
        path = self._archive.clip_path(camera_id, name)
        return path

    def safety_checks(self) -> tuple[SafetyCheck, ...]:
        """Проверки охраны труда, которыми разбираются кадры."""
        checks = self._assessment.checks
        return checks

    def safety_events(self, limit: int) -> list[tuple[Camera, CapturedFrame, SafetyFinding]]:
        """Отметки охраны труда по всем камерам, свежие впереди."""
        events: list[tuple[Camera, CapturedFrame, SafetyFinding]] = []
        for camera in self.cameras():
            for frame in self._archive.list_frames(camera.camera_id):
                events.extend((camera, frame, finding) for finding in frame.violations)
        events.sort(key=lambda item: item[1].captured_at, reverse=True)
        return events[:limit]

    def send_to_main_service(self, camera_id: str) -> tuple[int, str]:
        """Передаёт основному сервису снимки, которые ещё не уходили."""
        pending = [frame for frame in self.frames(camera_id) if frame.sent_at is None]
        if not pending:
            return NOTHING, "Новых снимков нет"
        files = [
            (frame.file_name, self._archive.read_photo_bytes(camera_id, frame.file_name))
            for frame in pending
        ]
        sent, note = self._client.send_frames(camera_id, files)
        if sent:
            names = {frame.file_name for frame in pending}
            self._archive.mark_sent(camera_id, names, datetime.now())
        return sent, note

    def _read_history(self, source: VideoSource, second: float) -> list[np.ndarray]:
        """Кадр съёмки вместе с предысторией для вычитания фона."""
        info = source.describe()
        start = second - BACKGROUND_FRAMES * BACKGROUND_STEP / max(info.fps, 1.0)
        frames = source.read_sequence(max(start, 0.0), BACKGROUND_FRAMES, BACKGROUND_STEP)
        return frames

    def _run_safety(
        self, camera: Camera, frames: list[np.ndarray]
    ) -> tuple[tuple[PersonRegion, ...], tuple[SafetyFinding, ...], list[str]]:
        """Прогоняет кадр через проверки, если они включены и есть чем проверять."""
        if not camera.safety_enabled:
            return (), (), [NO_SAFETY_NOTE]
        if not self._assessment.is_ready():
            return (), (), [NO_MODEL_NOTE]
        regions, findings = self._assessment.assess(frames, camera.people_source)
        return regions, findings, []

    def _store(
        self, camera: Camera, frame: np.ndarray, moment: datetime, second: float, notes: list[str]
    ) -> CaptureOutcome:
        """Пишет снимок на диск и готовит запись о нём."""
        note = f"{camera.title} · {camera.place}"
        name = self._archive.save_photo(camera.camera_id, frame, moment, note)
        captured = CapturedFrame(
            camera_id=camera.camera_id,
            captured_at=moment,
            file_name=name,
            source_second=second,
        )
        outcome = CaptureOutcome(
            frame=captured, photo_path=self._archive.photo_path(camera.camera_id, name), notes=notes
        )
        return outcome

    def _store_clip(
        self, camera: Camera, source: VideoSource, second: float, moment: datetime
    ) -> Path | None:
        """Пишет короткий отрезок записи вокруг события."""
        name = f"{camera.camera_id}-{moment.strftime('%Y%m%d-%H%M%S')}.mp4"
        target = self._archive.clip_path(camera.camera_id, name)
        saved = source.save_segment(max(second - EVENT_CLIP_SECONDS / 2, 0.0), EVENT_CLIP_SECONDS, target)
        return saved

    def _build_state(self, camera: Camera) -> CameraState:
        """Собирает состояние одной камеры по её архиву."""
        frames = self._archive.list_frames(camera.camera_id)
        violations = [frame for frame in frames if frame.violations]
        state = CameraState(
            camera=camera,
            frames_stored=len(frames),
            last_captured_at=frames[0].captured_at if frames else None,
            last_violation_at=violations[0].captured_at if violations else None,
            violations_total=sum(len(frame.violations) for frame in frames),
            unsent_frames=sum(1 for frame in frames if frame.sent_at is None),
        )
        return state
