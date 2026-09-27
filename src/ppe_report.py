"""Сборка страницы проверки СИЗ по фотографиям и видео.

Проверка средств защиты — отдельное измерение рядом с календарным планом: каска и жилет
не зависят от того, какой сегодня этап. Она работает на крупных планах, и страница эта
существует ровно затем, чтобы показать, где работает, а где нет.

Вход — и снимки, и ролики: из ролика кадры берутся с заданным шагом и дальше разбираются
так же, как фотографии. Ничего специфичного для видео в разборе нет, разница только
в том, откуда взялся кадр.
"""

import logging
from dataclasses import dataclass
from html import escape
from pathlib import Path

import cv2
import numpy as np

from camera_watch.entity import HEAD_SCOPE, PRESENT, UNCLEAR, PersonRegion, SafetyFinding
from camera_watch.services.safety_assessment import SafetyAssessmentService
from page_shell import STYLE, render_header

logger = logging.getLogger(__name__)

PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")
VIDEO_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv")
# Крупные кадры не сжимаются: детектор разберёт их по частям, и мелкие фигуры уцелеют.
MAX_SIDE = 2600
PREVIEW_WIDTH = 640
PREVIEW_QUALITY = 74
FRAMES_DIR_NAME = "frames"
# Страница отдаётся сервисом по своему адресу, поэтому ссылки на кадры абсолютные:
# относительные уходили бы на уровень выше и давали пустые рамки без картинок.
FRAMES_URL = "/safety/ppe/frames"
PAGE_NAME = "index.html"
SAFETY_URL = "/safety"
NOTHING = 0


@dataclass(frozen=True, slots=True)
class FrameResult:
    """Разбор одного кадра: откуда он и что на нём нашлось."""

    source: str
    title: str
    preview: str
    people: tuple[PersonRegion, ...]
    findings: tuple[SafetyFinding, ...]
    width: int
    height: int

    @property
    def violations(self) -> tuple[SafetyFinding, ...]:
        """Находки, признанные нарушениями."""
        found = tuple(item for item in self.findings if item.verdict == PRESENT)
        return found

    @property
    def unclear(self) -> int:
        """Сколько проверок не дали ответа."""
        count = sum(1 for item in self.findings if item.verdict == UNCLEAR)
        return count


class PpeReportBuilder:
    """Разбирает папку с фотографиями и роликами и собирает по ним страницу."""

    def __init__(
        self,
        assessment: SafetyAssessmentService,
        source_dir: Path,
        output_dir: Path,
        video_step_seconds: float,
    ) -> None:
        self._assessment = assessment
        self._source_dir = source_dir
        self._output_dir = output_dir
        self._video_step = video_step_seconds

    def build(self) -> tuple[FrameResult, ...]:
        """Разбирает весь материал и пишет страницу."""
        frames_dir = self._output_dir / FRAMES_DIR_NAME
        frames_dir.mkdir(parents=True, exist_ok=True)
        results: list[FrameResult] = []
        for path in sorted(self._source_dir.iterdir()):
            suffix = path.suffix.lower()
            if suffix in PHOTO_SUFFIXES:
                results.append(self._assess_photo(path, frames_dir))
            elif suffix in VIDEO_SUFFIXES:
                results.extend(self._assess_video(path, frames_dir))
        page = render_ppe_page(tuple(results), self._video_step)
        (self._output_dir / PAGE_NAME).write_text(page, encoding="utf-8")
        logger.info("Страница проверки СИЗ собрана: кадров %d", len(results))
        return tuple(results)

    def _assess_photo(self, path: Path, frames_dir: Path) -> FrameResult:
        """Разбирает одну фотографию."""
        image = _fit(cv2.imread(str(path)))
        result = self._assess_image(image, path.name, path.stem, path.name, frames_dir)
        return result

    def _assess_video(self, path: Path, frames_dir: Path) -> list[FrameResult]:
        """Разбирает ролик, беря кадры с заданным шагом."""
        results = []
        for number, (second, image) in enumerate(self._sample(path), start=1):
            name = f"{path.stem}-{number:02d}"
            title = f"{path.name} · {second:.0f} с"
            results.append(self._assess_image(_fit(image), path.name, name, title, frames_dir))
        return results

    def _sample(self, path: Path) -> list[tuple[float, np.ndarray]]:
        """Берёт из ролика кадры с шагом в заданное число секунд."""
        capture = cv2.VideoCapture(str(path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 1.0
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(int(fps * self._video_step), 1)
        sampled = []
        for index in range(0, total, step):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if ok:
                sampled.append((index / fps, frame))
        capture.release()
        return sampled

    def _assess_image(
        self, image: np.ndarray, source: str, name: str, title: str, frames_dir: Path
    ) -> FrameResult:
        """Прогоняет кадр через проверки и сохраняет уменьшенную копию."""
        regions, findings = self._assessment.assess([image])
        preview = _save_preview(image, frames_dir, name)
        height, width = image.shape[:2]
        result = FrameResult(
            source=source,
            title=title,
            preview=preview,
            people=regions,
            findings=findings,
            width=width,
            height=height,
        )
        return result


def _fit(image: np.ndarray) -> np.ndarray:
    """Уменьшает кадр до рабочего размера: детектор всё равно сожмёт его сам."""
    height, width = image.shape[:2]
    scale = MAX_SIDE / max(height, width)
    if scale >= 1:
        return image
    smaller = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return smaller


def _save_preview(image: np.ndarray, frames_dir: Path, name: str) -> str:
    """Кладёт уменьшенную копию кадра рядом со страницей."""
    height, width = image.shape[:2]
    scale = PREVIEW_WIDTH / width
    preview = cv2.resize(image, (PREVIEW_WIDTH, int(height * scale)), interpolation=cv2.INTER_AREA)
    file_name = f"{name}.jpg"
    cv2.imwrite(str(frames_dir / file_name), preview, [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_QUALITY])
    return file_name


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Проверка СИЗ</title><style>{style}{page_style}</style></head>
<body>{header}<div class="wrap">
<h1>Каски и жилеты на фото и видео<span class="svc extra">дополнительный сервис</span></h1>
<p class="sub">{lead}</p>
{summary}
{cards}
</div></body></html>"""

PAGE_STYLE = """
.ppe{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card .pic{position:relative;display:block;line-height:0}
.card .pic img{width:100%;display:block}
.card b.box{position:absolute;border:2px solid #21c07a;border-radius:3px}
.card b.box.bad{border-color:#ff4d4f}
.card .body{padding:11px 13px}
.card h3{margin:0 0 6px;font-size:13px;color:var(--muted);font-weight:600;word-break:break-all}
.card ul{margin:6px 0 0;padding-left:18px;font-size:13px}
.card li.bad{color:var(--bad)}
.card .none{font-size:13px;color:var(--ok)}
"""


def render_ppe_page(results: tuple[FrameResult, ...], video_step: float) -> str:
    """Собирает страницу разбора СИЗ."""
    cards = "".join(_card(item) for item in results)
    page = PAGE_TEMPLATE.format(
        style=STYLE,
        page_style=PAGE_STYLE,
        header=render_header(SAFETY_URL),
        lead="Тот же разбор, что на камерах, но по присланным фотографиям и роликам. "
        f"Из ролика кадры берутся раз в {video_step:.0f} с и разбираются как обычные снимки: "
        "ничего особенного для видео в проверке нет.",
        summary=_summary(results),
        cards=f'<div class="ppe">{cards}</div>',
    )
    return page


def _summary(results: tuple[FrameResult, ...]) -> str:
    """Свод по всему разобранному материалу."""
    people = sum(len(item.people) for item in results)
    marks = sum(len(item.violations) for item in results)
    unclear = sum(item.unclear for item in results)
    sources = len({item.source for item in results})
    panel = f"""<div class="panel"><h2>Что разобрано</h2>
<div class="kpis">
  <div class="kpi"><b>{sources}</b><span>файлов</span></div>
  <div class="kpi"><b>{len(results)}</b><span>кадров</span></div>
  <div class="kpi"><b>{people}</b><span>людей найдено</span></div>
  <div class="kpi"><b>{marks}</b><span>отметок</span></div>
  <div class="kpi"><b>{unclear}</b><span>без ответа</span></div>
</div>
<p class="note">Каска проверяется по голове с плечами, жилет — по фигуре целиком: это
разные вырезки, и мерялись они порознь. Человек ниже 80 пикселей в разбор не идёт вовсе,
а о каске не судят, пока вырезка головы меньше 70 пикселей: на съёмке с дрона голова
занимает сорок, и проверка отмечала отсутствие каски у всех подряд.</p></div>"""
    return panel


def _card(result: FrameResult) -> str:
    """Карточка одного кадра."""
    boxes = "".join(_box(item, result) for item in result.findings if item.box)
    card = f"""<div class="card">
  <a class="pic" href="{FRAMES_URL}/{result.preview}">
    <img src="{FRAMES_URL}/{result.preview}" loading="lazy" decoding="async"
         alt="{escape(result.title)}">{boxes}</a>
  <div class="body"><h3>{escape(result.title)}</h3>{_findings(result)}</div>
</div>"""
    return card


def _findings(result: FrameResult) -> str:
    """Перечень находок кадра словами."""
    if not result.people:
        return '<p class="none">Людей крупнее порога в кадре нет — проверять нечего.</p>'
    violations = result.violations
    if not violations:
        return (
            f'<p class="none">Людей: {len(result.people)}. Нарушений не отмечено'
            f'{f", без ответа {result.unclear}" if result.unclear else ""}.</p>'
        )
    items = "".join(
        f'<li class="bad">{escape(item.title)} — уверенность {item.confidence:.2f}</li>'
        for item in violations
    )
    return f"<p class=\"note\">Людей: {len(result.people)}</p><ul>{items}</ul>"


def _box(finding: SafetyFinding, result: FrameResult) -> str:
    """Рамка находки поверх кадра в долях его размера."""
    left, top, right, bottom = finding.box  # type: ignore[misc]
    bad = " bad" if finding.verdict == PRESENT else ""
    if finding.check_key.endswith("каски") or finding.check_key == HEAD_SCOPE:
        bottom = top + int((bottom - top) * 0.32)
    style = (
        f"left:{100 * left / result.width:.2f}%;top:{100 * top / result.height:.2f}%;"
        f"width:{100 * (right - left) / result.width:.2f}%;"
        f"height:{100 * (bottom - top) / result.height:.2f}%"
    )
    return f'<b class="box{bad}" style="{style}"></b>'
