"""Тесты архива камер: запись снимка, опись находок и отметка об отправке."""

from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from camera_watch.adapters.frame_archive import FrameArchive, with_findings
from camera_watch.entity import PRESENT, CapturedFrame, PersonRegion, SafetyFinding
from site_monitoring.adapters.photo_timestamp_reader import read_capture_time

CAMERA_ID = "gate"
CAPTURED_AT = datetime(2026, 9, 27, 9, 20, 0)
NOTE = "Камера 1 — КПП"


def _frame() -> np.ndarray:
    """Кадр однородного цвета."""
    picture = np.full((60, 80, 3), 90, dtype=np.uint8)
    return picture


def _finding() -> SafetyFinding:
    """Находка-нарушение с рамкой."""
    finding = SafetyFinding(
        check_key="нет_каски",
        title="Рабочий без защитной каски",
        verdict=PRESENT,
        confidence=0.81,
        margin=0.021,
        best_positive="worker without a hard hat",
        best_negative="worker wearing a helmet",
        box=(10, 12, 40, 55),
        confident=True,
    )
    return finding


def test_снимок_пишется_с_датой_съёмки_в_метаданных(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)

    # Act
    name = archive.save_photo(CAMERA_ID, _frame(), CAPTURED_AT, NOTE)

    # Assert
    stamp, from_exif = read_capture_time(archive.photo_path(CAMERA_ID, name))
    assert from_exif is True
    assert stamp == CAPTURED_AT


def test_опись_возвращает_находки_и_рамки(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)
    name = archive.save_photo(CAMERA_ID, _frame(), CAPTURED_AT, NOTE)
    frame = CapturedFrame(CAMERA_ID, CAPTURED_AT, name, source_second=12.5)
    stored = with_findings(frame, (PersonRegion(10, 12, 40, 55),), (_finding(),), "gate-clip.mp4")

    # Act
    archive.append(stored)
    restored = archive.list_frames(CAMERA_ID)

    # Assert
    assert len(restored) == 1
    assert restored[0].violations[0].box == (10, 12, 40, 55)
    assert restored[0].violations[0].confident is True
    assert restored[0].clip_name == "gate-clip.mp4"


def test_отправленные_снимки_помечаются_временем(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)
    name = archive.save_photo(CAMERA_ID, _frame(), CAPTURED_AT, NOTE)
    archive.append(CapturedFrame(CAMERA_ID, CAPTURED_AT, name, source_second=1.0))
    sent_at = datetime(2026, 9, 27, 9, 25, 0)

    # Act
    touched = archive.mark_sent(CAMERA_ID, {name}, sent_at)

    # Assert
    assert touched == 1
    assert archive.list_frames(CAMERA_ID)[0].sent_at == sent_at


def test_имя_снимка_не_выводит_за_каталог_камеры(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)

    # Act
    path = archive.photo_path(CAMERA_ID, "../../секрет.jpg")

    # Assert
    assert path.parent == archive.photos_dir(CAMERA_ID)
    assert path.name == "секрет.jpg"


def test_снимок_читается_как_изображение(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)
    name = archive.save_photo(CAMERA_ID, _frame(), CAPTURED_AT, NOTE)

    # Act
    with Image.open(archive.photo_path(CAMERA_ID, name)) as picture:
        size = picture.size

    # Assert
    assert size == (80, 60)


def test_кадры_старше_срока_хранения_убираются(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)
    old_at = datetime(2026, 9, 26, 9, 0)
    fresh_at = datetime(2026, 9, 27, 9, 0)
    old_name = archive.save_photo(CAMERA_ID, _frame(), old_at, NOTE)
    fresh_name = archive.save_photo(CAMERA_ID, _frame(), fresh_at, NOTE)
    archive.append(CapturedFrame(CAMERA_ID, old_at, old_name, source_second=0.0))
    archive.append(CapturedFrame(CAMERA_ID, fresh_at, fresh_name, source_second=0.0))

    # Act
    removed = archive.prune(CAMERA_ID, datetime(2026, 9, 27, 0, 0))

    # Assert
    assert removed == 1
    assert [frame.file_name for frame in archive.list_frames(CAMERA_ID)] == [fresh_name]
    assert not archive.photo_path(CAMERA_ID, old_name).exists()
    assert archive.photo_path(CAMERA_ID, fresh_name).exists()


def test_вместе_с_кадром_уходит_его_отрезок_записи(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)
    old_at = datetime(2026, 9, 26, 9, 0)
    name = archive.save_photo(CAMERA_ID, _frame(), old_at, NOTE)
    clip = archive.clip_path(CAMERA_ID, "gate-clip.mp4")
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    frame = CapturedFrame(CAMERA_ID, old_at, name, source_second=0.0, clip_name=clip.name)
    archive.append(frame)

    # Act
    archive.prune(CAMERA_ID, datetime(2026, 9, 27, 0, 0))

    # Assert
    assert not clip.exists()


def test_свежие_кадры_уборка_не_трогает(tmp_path: Path) -> None:
    # Arrange
    archive = FrameArchive(tmp_path)
    name = archive.save_photo(CAMERA_ID, _frame(), CAPTURED_AT, NOTE)
    archive.append(CapturedFrame(CAMERA_ID, CAPTURED_AT, name, source_second=0.0))

    # Act
    removed = archive.prune(CAMERA_ID, CAPTURED_AT)

    # Assert
    assert removed == 0
    assert len(archive.list_frames(CAMERA_ID)) == 1
