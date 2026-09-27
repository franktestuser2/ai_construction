"""Страница охраны труда: отметки моделей с кадром-доказательством.

Отделена от страниц камер: там показывают, что камеры сняли, а здесь — что модели
на снятом заметили и с какой достоверностью.
"""

from camera_watch.entity import Camera, CapturedFrame, SafetyCheck, SafetyFinding
from camera_pages import DEFAULT_SIZE, PAGE_STYLE, PAGE_TEMPLATE, box_overlay
from page_shell import STYLE, render_header

CAMERAS_URL = "/cameras"
SAFETY_URL = "/safety"
TIME_FORMAT = "%d.%m.%Y %H:%M"


def render_safety(
    events: list[tuple[Camera, CapturedFrame, SafetyFinding]],
    checks: tuple[SafetyCheck, ...],
    sizes: dict[str, tuple[int, int]],
) -> str:
    """Лента охраны труда: отметки моделей с кадром-доказательством."""
    if events:
        rows = "".join(_event_row(camera, frame, finding, sizes) for camera, frame, finding in events)
        body = f'<div class="panel">{rows}</div>{_checks_panel(checks)}'
    else:
        body = (
            '<div class="panel"><p class="note">Отметок пока нет. Снимите кадр на странице '
            f'<a href="{CAMERAS_URL}">камер</a> или дождитесь съёмки по расписанию.</p></div>'
            + _checks_panel(checks)
        )
    page = PAGE_TEMPLATE.format(
        title="Охрана труда",
        style=STYLE,
        page_style=PAGE_STYLE,
        header=render_header(SAFETY_URL),
        heading="Охрана труда",
        lead="Отметки модели по снятым кадрам. Отметка — повод посмотреть кадр, а не "
        "установленный факт: подтверждает нарушение человек.",
        body=body,
    )
    return page


def _event_row(
    camera: Camera,
    frame: CapturedFrame,
    finding: SafetyFinding,
    sizes: dict[str, tuple[int, int]],
) -> str:
    """Строка ленты охраны труда."""
    size = sizes.get(camera.camera_id, DEFAULT_SIZE)
    clip = (
        f'<a href="/cameras/{camera.camera_id}/clips/{frame.clip_name}">отрезок записи</a>'
        if frame.clip_name
        else '<span class="note">записи нет</span>'
    )
    row = f"""<div class="event"><div class="rowline">
  {_single_shot(camera.camera_id, frame, finding, size)}
  <div class="text">
    <b>{escape(finding.title)}</b> {_finding_badge(finding)}
    <div class="meta"><span>камера: <b>{escape(camera.title)}</b></span>
      <span>снято: <b>{frame.captured_at.strftime(TIME_FORMAT)}</b></span></div>
    <p class="note">уверенность {finding.confidence:.2f}, отрыв {finding.margin:+.3f};
      ближе всего «{escape(finding.best_positive)}», против «{escape(finding.best_negative)}»</p>
    <p class="note">{clip} · <a href="/cameras/{camera.camera_id}">камера</a></p>
  </div></div></div>"""
    return row


def _finding_badge(finding: SafetyFinding) -> str:
    """Отметка уверенности находки."""
    badge = (
        '<span class="badge sure">уверенная отметка</span>'
        if finding.confident
        else '<span class="badge maybe">кандидат на проверку</span>'
    )
    return badge


def _single_shot(
    camera_id: str, frame: CapturedFrame, finding: SafetyFinding, size: tuple[int, int]
) -> str:
    """Кадр события с одной обведённой областью."""
    width, height = size
    box = _box(finding.box, "", width, height) if finding.box else ""
    shot = (
        f'<span class="shot"><img src="/cameras/{camera_id}/photos/{frame.file_name}" '
        f'alt="кадр события" loading="lazy">{box}</span>'
    )
    return shot


def _checks_panel(checks: tuple[SafetyCheck, ...]) -> str:
    """Панель с тем, что именно проверяется и на чём это измерено."""
    if not checks:
        return (
            '<div class="panel"><h2>Проверки охраны труда</h2>'
            '<p class="note">Проверки не настроены или не найдены веса модели.</p></div>'
        )
    items = "".join(
        f"<li><b>{escape(item.title)}</b> — порог отметки {item.threshold:.2f}, "
        f"уверенной отметки {item.strict_threshold:.2f}"
        f'<div class="measure">{escape(item.measured_on)}</div></li>'
        for item in checks
    )
    panel = f"""<div class="panel"><h2>Проверки охраны труда</h2>
<p class="note">Проверка сравнивает кадр с формулировками «за» и «против»: абсолютная
близость у этой модели ничего не значит, значит только сравнение. Исхода три — признак
есть, признака нет и «не ясно», когда сравнение не разделило формулировки.</p>
<ul>{items}</ul></div>"""
    return panel


