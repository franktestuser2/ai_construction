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
from ppe_video import VideoAnnotator, VideoSummary
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
VIDEOS_DIR_NAME = "videos"
VIDEOS_URL = "/safety/ppe/videos"
PHOTOS_KEY = "фотографии"
VIDEOS_KEY = "ролики"
FILE_KEY = "файл"
NOTE_KEY = "подпись"
SECONDS_KEY = "секунд"
EVERY_KEY = "разбор_каждые"
DEFAULT_SECONDS = 8.0
DEFAULT_EVERY = 1.5
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
    """Разбирает отобранный материал и собирает по нему страницу."""

    def __init__(
        self,
        assessment: SafetyAssessmentService,
        annotator: VideoAnnotator,
        source_dir: Path,
        output_dir: Path,
    ) -> None:
        self._assessment = assessment
        self._annotator = annotator
        self._source_dir = source_dir
        self._output_dir = output_dir

    def build(self, selection: dict[str, object]) -> tuple[tuple[FrameResult, ...], tuple[tuple[VideoSummary, str], ...]]:
        """Размечает ролики, разбирает фотографии и пишет страницу."""
        frames_dir = self._output_dir / FRAMES_DIR_NAME
        frames_dir.mkdir(parents=True, exist_ok=True)
        videos = self._annotate_videos(selection.get(VIDEOS_KEY) or [])  # type: ignore[arg-type]
        photos = self._assess_photos(selection.get(PHOTOS_KEY) or [], frames_dir)  # type: ignore[arg-type]
        page = render_ppe_page(photos, videos)
        (self._output_dir / PAGE_NAME).write_text(page, encoding="utf-8")
        logger.info("Страница проверки СИЗ собрана: роликов %d, фотографий %d", len(videos), len(photos))
        return photos, videos

    def _annotate_videos(self, items: list[dict[str, object]]) -> tuple[tuple[VideoSummary, str], ...]:
        """Размечает каждый ролик из отбора."""
        videos_dir = self._output_dir / VIDEOS_DIR_NAME
        videos_dir.mkdir(parents=True, exist_ok=True)
        marked = []
        for item in items:
            name = str(item[FILE_KEY])
            target = videos_dir / f"{Path(name).stem}.webm"
            summary = self._annotator.annotate(
                self._source_dir / name,
                target,
                max_seconds=float(item.get(SECONDS_KEY, DEFAULT_SECONDS)),  # type: ignore[arg-type]
                check_every=float(item.get(EVERY_KEY, DEFAULT_EVERY)),  # type: ignore[arg-type]
            )
            marked.append((summary, str(item.get(NOTE_KEY, ""))))
        return tuple(marked)

    def _assess_photos(
        self, items: list[dict[str, object]], frames_dir: Path
    ) -> tuple[FrameResult, ...]:
        """Разбирает каждую фотографию из отбора."""
        results = []
        for item in items:
            path = self._source_dir / str(item[FILE_KEY])
            result = self._assess_photo(path, frames_dir, str(item.get(NOTE_KEY, "")))
            results.append(result)
        return tuple(results)

    def _assess_photo(self, path: Path, frames_dir: Path, note: str) -> FrameResult:
        """Разбирает одну фотографию."""
        image = _fit(cv2.imread(str(path)))
        result = self._assess_image(image, path.name, path.stem, note or path.name, frames_dir)
        return result

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
{videos}
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
.vids{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px;margin-top:12px}
.vid{background:var(--bg);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.vid video{width:100%;display:block;background:#000}
.vid .body{padding:11px 13px}
.vid .body b{font-size:14px}
"""


def render_ppe_page(
    photos: tuple[FrameResult, ...], videos: tuple[tuple[VideoSummary, str], ...]
) -> str:
    """Собирает страницу разбора СИЗ: сначала размеченные ролики, потом фотографии."""
    page = PAGE_TEMPLATE.format(
        style=STYLE,
        page_style=PAGE_STYLE,
        header=render_header(SAFETY_URL),
        lead="Один и тот же разбор работает и по фотографии, и по видео. На ролике рамки "
        "нарисованы прямо на кадрах: красная — отметка нарушения, зелёная — найденный "
        "человек, у которого каска и жилет на месте.",
        summary=_summary(photos, videos),
        videos=_videos_block(videos),
        cards=_photos_block(photos),
    )
    return page


def _videos_block(videos: tuple[tuple[VideoSummary, str], ...]) -> str:
    """Размеченные ролики проигрывателями."""
    if not videos:
        return ""
    items = "".join(_video_card(summary, note) for summary, note in videos)
    block = f"""<div class="panel"><h2>Видео с разметкой</h2>
<p class="note">Разбор идёт не на каждом кадре: детектор людей занимает секунды, а между
соседними кадрами на стройке ничего не меняется. Находки держатся до следующего разбора,
поэтому рамки не мигают.</p>
<div class="vids">{items}</div></div>"""
    return block


def _video_card(summary: VideoSummary, note: str) -> str:
    """Один проигрыватель с подписью и числами разбора."""
    card = f"""<div class="vid">
  <video controls preload="metadata" playsinline
         src="{VIDEOS_URL}/{summary.output}"></video>
  <div class="body"><b>{escape(note or summary.source)}</b>
    <div class="meta"><span>{summary.seconds:.0f} с</span>
      <span>разборов: <b>{summary.checked}</b></span>
      <span>людей: <b>{summary.people}</b></span>
      <span>отметок: <b>{summary.violations}</b></span></div>
    <p class="note">{escape(summary.source)}</p></div>
</div>"""
    return card


def _photos_block(photos: tuple[FrameResult, ...]) -> str:
    """Отобранные фотографии с рамками."""
    if not photos:
        return ""
    cards = "".join(_card(item) for item in photos)
    block = f"""<div class="panel"><h2>Фотографии</h2>
<p class="note">Оставлены только те снимки, где отметки проверены глазами. Остальные из
набора убраны: на них проверка либо не нашла людей, либо ошиблась, и показывать их как
работу сервиса нечестно.</p>
<div class="ppe">{cards}</div></div>"""
    return block


def _summary(
    photos: tuple[FrameResult, ...], videos: tuple[tuple[VideoSummary, str], ...]
) -> str:
    """Свод по всему разобранному материалу."""
    people = sum(len(item.people) for item in photos) + sum(item.people for item, _ in videos)
    marks = sum(len(item.violations) for item in photos) + sum(item.violations for item, _ in videos)
    seconds = sum(item.seconds for item, _ in videos)
    panel = f"""<div class="panel"><h2>Что разобрано</h2>
<div class="kpis">
  <div class="kpi"><b>{len(videos)}</b><span>роликов</span></div>
  <div class="kpi"><b>{seconds:.0f} с</b><span>видео с разметкой</span></div>
  <div class="kpi"><b>{len(photos)}</b><span>фотографий</span></div>
  <div class="kpi"><b>{people}</b><span>людей найдено</span></div>
  <div class="kpi"><b>{marks}</b><span>отметок</span></div>
</div>
<p class="note">Каска проверяется по голове с плечами, жилет — по фигуре целиком: это
разные вырезки, и мерялись они порознь. Человек ниже 80 пикселей в разбор не идёт вовсе,
а о каске не судят, пока вырезка головы меньше 70 пикселей: на съёмке с дрона голова
занимает сорок, и проверка отмечала отсутствие каски у всех подряд.</p>
<p class="note">Замер по размеченным вручную снимкам: каска — полнота 0,82 при точности
0,69; жилет — полнота 0,80 при точности 0,50. Это отбор кандидатов на просмотр человеком,
а не протоколирование нарушений.</p></div>"""
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
