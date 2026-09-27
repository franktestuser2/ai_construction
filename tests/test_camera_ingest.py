"""Тесты приёмной: очередь снимков с камер и план, составляемый под них."""

import json
from datetime import date
from pathlib import Path

from camera_watch.adapters.camera_registry_reader import CameraRegistryReader, SafetyChecksReader
from camera_watch.entity import PERSON_SCOPE
from ingest_routes import _clear_queue, _collect_photos, _queue, read_plan, stage_for

PHOTO_BYTES = b"\xff\xd8\xff\xe0 fake jpeg"
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


def test_этап_на_сегодня_берётся_из_плана_объекта() -> None:
    # Arrange
    stages = read_plan(PROJECT_ROOT / "config" / "План_объекта.csv")

    # Act
    stage = stage_for(stages, date.today())

    # Assert
    assert stages
    assert stage is not None
    assert stage.start <= date.today() <= stage.finish


def test_на_день_вне_плана_этапа_нет() -> None:
    # Arrange
    stages = read_plan(PROJECT_ROOT / "config" / "План_объекта.csv")

    # Act
    stage = stage_for(stages, date(2020, 1, 1))

    # Assert
    assert stage is None


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


def test_узкая_полоса_человеком_не_считается() -> None:
    # Arrange: рост 145 при ширине 23 — так стоящий человек не выглядит
    from camera_watch.adapters.person_detector import _looks_like_person

    # Act
    sliver = _looks_like_person(width=23, height=145, min_height=80, min_ratio=0.25)
    person = _looks_like_person(width=52, height=145, min_height=80, min_ratio=0.25)
    short = _looks_like_person(width=30, height=60, min_height=80, min_ratio=0.25)

    # Assert
    assert sliver is False
    assert person is True
    assert short is False
