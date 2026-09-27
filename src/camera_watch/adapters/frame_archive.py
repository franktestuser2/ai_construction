"""Хранение снятого с камер.

Архив камеры — это снимки, сделанные по расписанию, отрезки записи к событиям и опись
того и другого. Снимок кладётся с датой съёмки в EXIF: основной сервис разносит кадры по
этапам плана именно по ней, и кадр без метаданных попал бы в разбор по порядку загрузки.

Непрерывной записи здесь нет и не заявляется: круглосуточный архив — работа медиасервера,
которого на этой машине нет. Хранится то, что сервису действительно нужно для разбора, —
кадры по расписанию и короткий отрезок вокруг события.
"""

import json
import logging
import os
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from camera_watch.entity import CapturedFrame, PersonRegion, SafetyFinding

logger = logging.getLogger(__name__)

PHOTOS_DIR_NAME = "photos"
CLIPS_DIR_NAME = "clips"
INDEX_FILE_NAME = "frames.json"
NAME_FORMAT = "%Y%m%d-%H%M%S"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"
EXIF_IFD = 0x8769
EXIF_DATETIME = 0x0132
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME_DIGITIZED = 0x9004
EXIF_DESCRIPTION = 0x010E
EXIF_SOFTWARE = 0x0131
SOFTWARE_TAG = "site-monitoring camera watch"
JPEG_SUFFIX = ".jpg"
CLIP_SUFFIX = ".mp4"
JPEG_QUALITY = 88
NOTHING = 0


class FrameArchive:
    """Складывает и достаёт снимки камер и отрезки записи."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def photos_dir(self, camera_id: str) -> Path:
        """Каталог снимков камеры."""
        path = self._root / camera_id / PHOTOS_DIR_NAME
        return path

    def clips_dir(self, camera_id: str) -> Path:
        """Каталог отрезков записи камеры."""
        path = self._root / camera_id / CLIPS_DIR_NAME
        return path

    def photo_path(self, camera_id: str, name: str) -> Path:
        """Путь одного снимка; имя берётся только как имя файла."""
        path = self.photos_dir(camera_id) / Path(name).name
        return path

    def clip_path(self, camera_id: str, name: str) -> Path:
        """Путь одного отрезка записи."""
        path = self.clips_dir(camera_id) / Path(name).name
        return path

    def save_photo(self, camera_id: str, image: np.ndarray, captured_at: datetime, note: str) -> str:
        """Пишет кадр в архив с датой съёмки в метаданных и возвращает имя файла."""
        directory = self.photos_dir(camera_id)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{camera_id}-{captured_at.strftime(NAME_FORMAT)}{JPEG_SUFFIX}"
        target = directory / name
        picture = Image.fromarray(image[:, :, ::-1])
        picture.save(target, quality=JPEG_QUALITY, exif=_build_exif(captured_at, note))
        # Отметка файла ставится вслед за EXIF: по ней снимок читается, если метаданных нет.
        stamp = captured_at.timestamp()
        os.utime(target, (stamp, stamp))
        return name

    def read_photo_bytes(self, camera_id: str, name: str) -> bytes:
        """Содержимое снимка для отправки в основной сервис."""
        content = self.photo_path(camera_id, name).read_bytes()
        return content

    def append(self, frame: CapturedFrame) -> None:
        """Дописывает снимок в опись камеры."""
        records = self._read_index(frame.camera_id)
        records.append(_frame_to_record(frame))
        self._write_index(frame.camera_id, records)

    def list_frames(self, camera_id: str) -> tuple[CapturedFrame, ...]:
        """Все снимки камеры от новых к старым."""
        records = self._read_index(camera_id)
        frames = [_record_to_frame(item) for item in records]
        frames.sort(key=lambda item: item.captured_at, reverse=True)
        return tuple(frames)

    def mark_sent(self, camera_id: str, names: set[str], sent_at: datetime) -> int:
        """Отмечает снимки как переданные основному сервису."""
        records = self._read_index(camera_id)
        touched = NOTHING
        for record in records:
            if record["file_name"] in names:
                record["sent_at"] = sent_at.strftime(TIME_FORMAT)
                touched += 1
        self._write_index(camera_id, records)
        return touched

    def prune(self, camera_id: str, keep_after: datetime) -> int:
        """Убирает кадры старше заданного времени и возвращает, сколько их было.

        Снимок с камеры нужен ровно до тех пор, пока его не разобрали и не сверили
        с планом; дальше это просто занятое место. Вместе со снимком уходит и отрезок
        записи, снятый к нему: доказательство без кадра бессмысленно.
        """
        records = self._read_index(camera_id)
        kept: list[dict[str, object]] = []
        removed = NOTHING
        for record in records:
            stamp = datetime.strptime(str(record["captured_at"]), TIME_FORMAT)
            if stamp >= keep_after:
                kept.append(record)
                continue
            self._remove_files(camera_id, record)
            removed += 1
        if removed:
            self._write_index(camera_id, kept)
            logger.info("Камера %s: убрано кадров старше срока хранения: %d", camera_id, removed)
        return removed

    def _remove_files(self, camera_id: str, record: dict[str, object]) -> None:
        """Удаляет файлы одного кадра: сам снимок и отрезок записи к нему."""
        self.photo_path(camera_id, str(record["file_name"])).unlink(missing_ok=True)
        clip_name = str(record.get("clip_name") or "")
        if clip_name:
            self.clip_path(camera_id, clip_name).unlink(missing_ok=True)

    def used_bytes(self, camera_id: str) -> int:
        """Сколько места занимает архив камеры."""
        directory = self._root / camera_id
        if not directory.exists():
            return NOTHING
        total = sum(item.stat().st_size for item in directory.rglob("*") if item.is_file())
        return total

    def clear(self, camera_id: str) -> None:
        """Убирает архив камеры целиком."""
        shutil.rmtree(self._root / camera_id, ignore_errors=True)

    def _index_path(self, camera_id: str) -> Path:
        """Путь описи камеры."""
        path = self._root / camera_id / INDEX_FILE_NAME
        return path

    def _read_index(self, camera_id: str) -> list[dict[str, object]]:
        """Читает опись камеры."""
        path = self._index_path(camera_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            logger.warning("Опись камеры %s повреждена, начинаю заново", camera_id)
            return []
        return list(payload)

    def _write_index(self, camera_id: str, records: list[dict[str, object]]) -> None:
        """Пишет опись камеры."""
        path = self._index_path(camera_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")


def _build_exif(captured_at: datetime, note: str) -> Image.Exif:
    """Собирает метаданные снимка со временем съёмки."""
    stamp = captured_at.strftime(EXIF_TIME_FORMAT)
    exif = Image.Exif()
    exif[EXIF_DATETIME] = stamp
    exif[EXIF_SOFTWARE] = SOFTWARE_TAG
    exif[EXIF_DESCRIPTION] = note.encode("utf-8").decode("latin-1", "ignore")
    sub_ifd = exif.get_ifd(EXIF_IFD)
    sub_ifd[EXIF_DATETIME_ORIGINAL] = stamp
    sub_ifd[EXIF_DATETIME_DIGITIZED] = stamp
    return exif


def _frame_to_record(frame: CapturedFrame) -> dict[str, object]:
    """Переводит снимок в запись описи."""
    record = {
        "camera_id": frame.camera_id,
        "captured_at": frame.captured_at.strftime(TIME_FORMAT),
        "file_name": frame.file_name,
        "source_second": round(frame.source_second, 2),
        "clip_name": frame.clip_name,
        "sent_at": frame.sent_at.strftime(TIME_FORMAT) if frame.sent_at else "",
        "people": [list(region.box) for region in frame.people],
        "findings": [_finding_to_record(item) for item in frame.findings],
    }
    return record


def _finding_to_record(finding: SafetyFinding) -> dict[str, object]:
    """Переводит находку в запись описи."""
    record = {
        "check_key": finding.check_key,
        "title": finding.title,
        "verdict": finding.verdict,
        "confidence": finding.confidence,
        "margin": finding.margin,
        "best_positive": finding.best_positive,
        "best_negative": finding.best_negative,
        "box": list(finding.box) if finding.box else None,
        "confident": finding.confident,
    }
    return record


def _record_to_frame(record: dict[str, object]) -> CapturedFrame:
    """Собирает снимок из записи описи."""
    people = tuple(PersonRegion(*box) for box in record.get("people", []))  # type: ignore[misc]
    findings = tuple(_record_to_finding(item) for item in record.get("findings", []))  # type: ignore[union-attr]
    sent_raw = str(record.get("sent_at") or "")
    frame = CapturedFrame(
        camera_id=str(record["camera_id"]),
        captured_at=datetime.strptime(str(record["captured_at"]), TIME_FORMAT),
        file_name=str(record["file_name"]),
        source_second=float(record.get("source_second", 0.0)),  # type: ignore[arg-type]
        people=people,
        findings=findings,
        clip_name=str(record.get("clip_name") or ""),
        sent_at=datetime.strptime(sent_raw, TIME_FORMAT) if sent_raw else None,
    )
    return frame


def _record_to_finding(record: dict[str, object]) -> SafetyFinding:
    """Собирает находку из записи описи."""
    box = record.get("box")
    finding = SafetyFinding(
        check_key=str(record["check_key"]),
        title=str(record["title"]),
        verdict=str(record["verdict"]),
        confidence=float(record["confidence"]),  # type: ignore[arg-type]
        margin=float(record["margin"]),  # type: ignore[arg-type]
        best_positive=str(record.get("best_positive", "")),
        best_negative=str(record.get("best_negative", "")),
        box=tuple(box) if box else None,  # type: ignore[arg-type]
        confident=bool(record.get("confident", False)),
    )
    return finding


def with_findings(
    frame: CapturedFrame,
    people: tuple[PersonRegion, ...],
    findings: tuple[SafetyFinding, ...],
    clip_name: str = "",
) -> CapturedFrame:
    """Возвращает копию снимка с добавленными находками и записью-доказательством."""
    updated = replace(frame, people=people, findings=findings, clip_name=clip_name)
    return updated
