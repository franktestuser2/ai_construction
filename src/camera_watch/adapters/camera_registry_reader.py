"""Чтение описания камер и проверок охраны труда из конфигурации."""

import json
import logging
from pathlib import Path

from camera_watch.entity import MOTION_SOURCE, Camera, SafetyCheck

logger = logging.getLogger(__name__)

CAMERAS_KEY = "cameras"
CHECKS_KEY = "checks"
PADDING_KEY = "person_padding"
DEFAULT_PADDING = 30
DEFAULT_PERIOD_MINUTES = 20


class CameraRegistryReader:
    """Достаёт список камер из файла конфигурации."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> tuple[Camera, ...]:
        """Камеры, описанные в конфигурации."""
        if not self._path.exists():
            logger.warning("Файл камер не найден: %s", self._path)
            return ()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        cameras = tuple(_build_camera(item) for item in payload.get(CAMERAS_KEY, []))
        return cameras


class SafetyChecksReader:
    """Достаёт проверки охраны труда из файла конфигурации."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> tuple[SafetyCheck, ...]:
        """Проверки, описанные в конфигурации."""
        payload = self._read_payload()
        checks = tuple(_build_check(item) for item in payload.get(CHECKS_KEY, []))
        return checks

    def read_padding(self) -> int:
        """Запас вокруг области человека, с которым мерили проверки."""
        payload = self._read_payload()
        padding = int(payload.get(PADDING_KEY, DEFAULT_PADDING))
        return padding

    def _read_payload(self) -> dict[str, object]:
        """Содержимое файла проверок."""
        if not self._path.exists():
            logger.warning("Файл проверок охраны труда не найден: %s", self._path)
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return payload


def _build_camera(item: dict[str, object]) -> Camera:
    """Собирает камеру из записи конфигурации."""
    camera = Camera(
        camera_id=str(item["id"]),
        title=str(item["title"]),
        place=str(item.get("place", "")),
        source=str(item["source"]),
        capture_period_minutes=int(item.get("capture_period_minutes", DEFAULT_PERIOD_MINUTES)),  # type: ignore[arg-type]
        safety_enabled=bool(item.get("safety_enabled", True)),
        people_source=str(item.get("people_source", MOTION_SOURCE)),
        origin=str(item.get("origin", "")),
        notes=str(item.get("notes", "")),
    )
    return camera


def _build_check(item: dict[str, object]) -> SafetyCheck:
    """Собирает проверку из записи конфигурации."""
    check = SafetyCheck(
        key=str(item["key"]),
        title=str(item["title"]),
        scope=str(item["scope"]),
        positive=tuple(str(phrase) for phrase in item["positive"]),  # type: ignore[union-attr]
        negative=tuple(str(phrase) for phrase in item["negative"]),  # type: ignore[union-attr]
        threshold=float(item["threshold"]),  # type: ignore[arg-type]
        strict_threshold=float(item["strict_threshold"]),  # type: ignore[arg-type]
        min_margin=float(item["min_margin"]),  # type: ignore[arg-type]
        measured_on=str(item.get("measured_on", "")),
    )
    return check
