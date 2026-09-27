"""Тесты приёмной: очередь снимков с камер и план, составляемый под них."""

import json
from datetime import date
from pathlib import Path

from camera_watch.adapters.camera_registry_reader import CameraRegistryReader, SafetyChecksReader
from camera_watch.entity import PERSON_SCOPE
from ingest_routes import _build_plan, _clear_queue, _collect_photos, _queue
from site_monitoring.adapters.uploaded_plan_reader import UploadedPlanReader

PHOTO_BYTES = b"\xff\xd8\xff\xe0 fake jpeg"
WORK_TITLE = "Погрузка строительного мусора"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _inbox(tmp_path: Path) -> Path:
    """Очередь с двумя снимками одной камеры и одним посторонним файлом."""
    directory = tmp_path / "gate"
    directory.mkdir(parents=True)
    (directory / "gate-1.jpg").write_bytes(PHOTO_BYTES)
    (directory / "gate-2.jpg").write_bytes(PHOTO_BYTES)
    (directory / "заметка.txt").write_text("не снимок", encoding="utf-8")
    return tmp_path


def test_очередь_считает_только_снимки(tmp_path: Path) -> None:
    # Arrange
    inbox = _inbox(tmp_path)

    # Act
    counts = _queue(inbox)

    # Assert
    assert counts == {"gate": 2}


def test_очередь_отдаёт_содержимое_снимков(tmp_path: Path) -> None:
    # Arrange
    inbox = _inbox(tmp_path)

    # Act
    photos = _collect_photos(inbox)

    # Assert
    assert [name for name, _ in photos] == ["gate-1.jpg", "gate-2.jpg"]
    assert photos[0][1] == PHOTO_BYTES


def test_разобранные_снимки_уходят_из_очереди(tmp_path: Path) -> None:
    # Arrange
    inbox = _inbox(tmp_path)

    # Act
    _clear_queue(inbox)

    # Assert
    assert _queue(inbox) == {}
    assert (inbox / "gate" / "заметка.txt").exists()


def test_план_под_снятое_составляется_на_один_день(tmp_path: Path) -> None:
    # Arrange
    day = date(2026, 9, 27)
    target = tmp_path / "План.csv"

    # Act
    target.write_bytes(_build_plan(WORK_TITLE, day))
    stages = UploadedPlanReader(target).read_stages()

    # Assert
    assert len(stages) == 1
    assert stages[0].full_name == WORK_TITLE
    assert stages[0].start == day
    assert stages[0].finish == day


def test_камеры_читаются_из_конфигурации() -> None:
    # Arrange
    reader = CameraRegistryReader(PROJECT_ROOT / "config" / "cameras.json")

    # Act
    cameras = reader.read()

    # Assert
    assert cameras
    assert all(camera.capture_period_minutes > 0 for camera in cameras)
    assert all(camera.title and camera.place for camera in cameras)


def test_источник_камеры_читается_и_файлом_и_потоком(tmp_path: Path) -> None:
    # Arrange
    payload = {
        "cameras": [
            {
                "id": "live",
                "title": "Живая",
                "place": "Площадка",
                "source": "https://example.test/hls/stream.m3u8",
                "capture_period_minutes": 20,
                "origin": "Публичная трансляция",
            },
            {
                "id": "file",
                "title": "Ролик",
                "place": "Площадка",
                "source": "data/cameras/scenes/gate.mp4",
                "capture_period_minutes": 20,
            },
        ]
    }
    target = tmp_path / "cameras.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # Act
    cameras = CameraRegistryReader(target).read()

    # Assert
    assert [camera.is_live for camera in cameras] == [True, False]
    assert cameras[0].origin == "Публичная трансляция"


def test_подключённые_камеры_это_живые_трансляции() -> None:
    # Arrange
    reader = CameraRegistryReader(PROJECT_ROOT / "config" / "cameras.json")

    # Act
    cameras = reader.read()

    # Assert
    assert cameras
    assert all(camera.is_live for camera in cameras)
    assert all(camera.origin for camera in cameras)


def test_проверки_охраны_труда_читаются_с_обоими_порогами() -> None:
    # Arrange
    reader = SafetyChecksReader(PROJECT_ROOT / "config" / "safety_checks.json")

    # Act
    checks = reader.read()

    # Assert
    assert checks
    assert all(check.strict_threshold > check.threshold for check in checks)
    assert all(check.scope == PERSON_SCOPE for check in checks)
    assert all(check.measured_on for check in checks)


def test_очередь_чистится_по_сроку_хранения(tmp_path: Path) -> None:
    # Arrange
    import os
    from datetime import datetime, timedelta

    from ingest_routes import prune_queue

    inbox = _inbox(tmp_path)
    stale = inbox / "gate" / "gate-1.jpg"
    old_stamp = (datetime.now() - timedelta(hours=30)).timestamp()
    os.utime(stale, (old_stamp, old_stamp))

    # Act
    removed = prune_queue(inbox, datetime.now() - timedelta(hours=24))

    # Assert
    assert removed == 1
    assert _queue(inbox) == {"gate": 1}
