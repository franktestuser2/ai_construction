"""Разметка роликов: рамки и подписи прямо на видео.

Смотреть разбор по отдельным кадрам неудобно и неубедительно: непонятно, держится ли
находка или мигает от кадра к кадру. Поэтому ролик пересобирается с нарисованными рамками
и отдаётся проигрывателем как обычное видео.

Разбор идёт не на каждом кадре: детектор людей занимает секунды, а между соседними кадрами
на стройке ничего не меняется. Находки держатся до следующего разбора — так рамки не мигают
и картинка остаётся честной.

Пишется WebM: H.264 в этой сборке OpenCV недоступен, а WebM браузеры играют без плагинов.
"""

import logging
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from camera_watch.entity import PRESENT, PersonRegion, SafetyFinding
from camera_watch.services.safety_assessment import SafetyAssessmentService

logger = logging.getLogger(__name__)

WEBM_CODEC = "VP80"
OUTPUT_WIDTH = 960
# Выходной ролик идёт с пониженной частотой: смотреть разметку хватает и двенадцати
# кадров в секунду, а вес падает вдвое — VP8 в этой сборке пишется без выбора битрейта.
OUTPUT_FPS = 12.0
# Разбор идёт по копии покрупнее выходной картинки: детектор сам сжимает вход, и на
# съёмке с дрона рабочие пропадали бы. Найденные рамки потом переносятся на выходной кадр.
DETECT_WIDTH = 2600
OK_COLOR = (122, 192, 33)
BAD_COLOR = (79, 77, 255)
BOX_THICKNESS = 3
# Подписи рисуются через PIL: шрифты OpenCV кириллицу не умеют и пишут вопросительные знаки.
LABEL_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
LABEL_SIZE = 20
LABEL_PAD = 6
HEAD_SHARE = 0.32
HELMET_KEY = "нет_каски"
VEST_KEY = "нет_жилета"
PANEL_COLOR = (32, 32, 32)
PANEL_TEXT = (235, 235, 235)
NOTHING = 0


@dataclass(frozen=True, slots=True)
class VideoSummary:
    """Итог разметки одного ролика."""

    source: str
    output: str
    seconds: float
    frames: int
    checked: int
    people: int
    violations: int


class VideoAnnotator:
    """Пересобирает ролик с нарисованными находками."""

    def __init__(self, assessment: SafetyAssessmentService) -> None:
        self._assessment = assessment

    def annotate(
        self, source: Path, target: Path, max_seconds: float, check_every: float
    ) -> VideoSummary:
        """Размечает ролик и возвращает итог разбора."""
        capture = cv2.VideoCapture(str(source))
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        size = _output_size(width, height)
        target.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*WEBM_CODEC), OUTPUT_FPS, size)
        summary = self._run(capture, writer, fps, size, source, target, max_seconds, check_every)
        capture.release()
        writer.release()
        logger.info(
            "Ролик %s размечен: кадров %d, разборов %d, людей %d, отметок %d",
            source.name,
            summary.frames,
            summary.checked,
            summary.people,
            summary.violations,
        )
        return summary

    def _detect(
        self, frame: np.ndarray, size: tuple[int, int]
    ) -> tuple[tuple[PersonRegion, ...], tuple[SafetyFinding, ...]]:
        """Разбирает кадр в рабочем разрешении и переносит рамки на выходное."""
        height, width = frame.shape[:2]
        work_width = min(DETECT_WIDTH, width)
        work = cv2.resize(frame, (work_width, int(height * work_width / width)), interpolation=cv2.INTER_AREA)
        regions, findings = self._assessment.assess([work])
        scale = size[0] / work_width
        moved_regions = tuple(_scale_region(region, scale) for region in regions)
        moved_findings = tuple(_scale_finding(finding, scale) for finding in findings)
        return moved_regions, moved_findings

    def _run(
        self,
        capture: cv2.VideoCapture,
        writer: cv2.VideoWriter,
        fps: float,
        size: tuple[int, int],
        source: Path,
        target: Path,
        max_seconds: float,
        check_every: float,
    ) -> VideoSummary:
        """Идёт по ролику, разбирая каждый n-й кадр и рисуя находки на всех."""
        step = max(int(fps * check_every), 1)
        keep_every = max(int(round(fps / OUTPUT_FPS)), 1)
        limit = int(fps * max_seconds)
        regions: tuple[PersonRegion, ...] = ()
        findings: tuple[SafetyFinding, ...] = ()
        counts = {"frames": NOTHING, "checked": NOTHING, "people": NOTHING, "violations": NOTHING}
        while counts["frames"] < limit:
            ok, frame = capture.read()
            if not ok:
                break
            if counts["frames"] % step == NOTHING:
                regions, findings = self._detect(frame, size)
                counts["checked"] += 1
                counts["people"] += len(regions)
                counts["violations"] += sum(1 for item in findings if item.verdict == PRESENT)
            if counts["frames"] % keep_every == NOTHING:
                picture = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                writer.write(_draw(picture, regions, findings))
            counts["frames"] += 1
        summary = VideoSummary(
            source=source.name,
            output=target.name,
            seconds=counts["frames"] / fps if fps else 0.0,
            frames=counts["frames"],
            checked=counts["checked"],
            people=counts["people"],
            violations=counts["violations"],
        )
        return summary


def _scale_region(region: PersonRegion, scale: float) -> PersonRegion:
    """Переносит рамку человека в другое разрешение."""
    moved = PersonRegion(
        left=int(region.left * scale),
        top=int(region.top * scale),
        right=int(region.right * scale),
        bottom=int(region.bottom * scale),
    )
    return moved


def _scale_finding(finding: SafetyFinding, scale: float) -> SafetyFinding:
    """Переносит рамку находки в другое разрешение."""
    if finding.box is None:
        return finding
    left, top, right, bottom = finding.box
    box = (int(left * scale), int(top * scale), int(right * scale), int(bottom * scale))
    moved = replace(finding, box=box)
    return moved


def _output_size(width: int, height: int) -> tuple[int, int]:
    """Размер выходного ролика: по ширине, кратно двум."""
    if width <= OUTPUT_WIDTH:
        return (width - width % 2, height - height % 2)
    scale = OUTPUT_WIDTH / width
    new_height = int(height * scale)
    return (OUTPUT_WIDTH - OUTPUT_WIDTH % 2, new_height - new_height % 2)


def _draw(
    frame: np.ndarray, regions: tuple[PersonRegion, ...], findings: tuple[SafetyFinding, ...]
) -> np.ndarray:
    """Рисует на кадре рамки людей, подписи нарушений и сводку проверенного.

    Сводка нужна не для красоты: без неё кадр, на котором все в касках, выглядит так,
    будто каску никто и не проверял.
    """
    picture = frame.copy()
    for region in regions:
        cv2.rectangle(picture, (region.left, region.top), (region.right, region.bottom), OK_COLOR, 1)
    labels: list[tuple[str, int, int]] = []
    for finding in findings:
        if finding.box is None or finding.verdict != PRESENT:
            continue
        labels.append(_draw_violation(picture, finding))
    marked = _draw_labels(picture, labels)
    summed = _draw_summary(marked, regions, findings)
    return summed


def _draw_summary(
    picture: np.ndarray, regions: tuple[PersonRegion, ...], findings: tuple[SafetyFinding, ...]
) -> np.ndarray:
    """Пишет в углу, что проверено и сколько нарушений нашлось."""
    lines = [f"людей найдено: {len(regions)}"]
    for key, title in ((HELMET_KEY, "каска"), (VEST_KEY, "жилет")):
        checked = [item for item in findings if item.check_key == key]
        if not checked:
            lines.append(f"{title}: не проверялась — мелко в кадре")
            continue
        bad = sum(1 for item in checked if item.verdict == PRESENT)
        lines.append(f"{title}: проверено {len(checked)}, нарушений {bad}")
    return _draw_panel(picture, lines)


def _draw_violation(picture: np.ndarray, finding: SafetyFinding) -> tuple[str, int, int]:
    """Обводит находку и возвращает подпись к ней."""
    left, top, right, bottom = finding.box  # type: ignore[misc]
    if finding.check_key == HELMET_KEY:
        bottom = top + int((bottom - top) * HEAD_SHARE)
    cv2.rectangle(picture, (left, top), (right, bottom), BAD_COLOR, BOX_THICKNESS)
    label = "без каски" if finding.check_key == HELMET_KEY else "без жилета"
    return (label, left, top)


def _draw_labels(picture: np.ndarray, labels: list[tuple[str, int, int]]) -> np.ndarray:
    """Пишет подписи над рамками на подложке, чтобы их было видно на любом фоне."""
    if not labels:
        return picture
    from PIL import Image, ImageDraw, ImageFont

    image = Image.fromarray(picture[:, :, ::-1])
    canvas = ImageDraw.Draw(image)
    font = _label_font(ImageFont)
    for text, left, top in labels:
        box = canvas.textbbox((0, 0), text, font=font)
        width, height = box[2] - box[0], box[3] - box[1]
        bottom = max(top, height + 2 * LABEL_PAD)
        canvas.rectangle(
            (left, bottom - height - 2 * LABEL_PAD, left + width + 2 * LABEL_PAD, bottom),
            fill=BAD_COLOR[::-1],
        )
        canvas.text((left + LABEL_PAD, bottom - height - LABEL_PAD), text, font=font, fill=(255, 255, 255))
    return np.asarray(image)[:, :, ::-1].copy()


def _draw_panel(picture: np.ndarray, lines: list[str]) -> np.ndarray:
    """Рисует в левом верхнем углу тёмную подложку со строками сводки."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.fromarray(picture[:, :, ::-1])
    canvas = ImageDraw.Draw(image, "RGBA")
    font = _label_font(ImageFont)
    widths = [canvas.textbbox((0, 0), line, font=font)[2] for line in lines]
    height = (LABEL_SIZE + 8) * len(lines) + LABEL_PAD
    canvas.rectangle((8, 8, 18 + max(widths), 8 + height), fill=(*PANEL_COLOR, 205))
    for number, line in enumerate(lines):
        canvas.text((14, 12 + number * (LABEL_SIZE + 8)), line, font=font, fill=PANEL_TEXT)
    return np.asarray(image)[:, :, ::-1].copy()


def _label_font(module):  # type: ignore[no-untyped-def]
    """Шрифт подписей; если его нет в системе, берётся встроенный."""
    if LABEL_FONT_PATH.exists():
        return module.truetype(str(LABEL_FONT_PATH), LABEL_SIZE)
    return module.load_default()
