"""Страницы контура наблюдения: камеры онлайн, архив съёмок и лента охраны труда."""

from datetime import datetime
from html import escape

from camera_watch.entity import Camera, CameraState, CapturedFrame, SafetyFinding
from page_shell import STYLE, render_header

CAMERAS_URL = "/cameras"
SAFETY_URL = "/safety"
TIME_FORMAT = "%d.%m.%Y %H:%M"
SHORT_TIME_FORMAT = "%H:%M"
NEVER = "ещё не снимали"
# Три камеры, три кадра в час, восьмичасовая смена.
POOL_LIMIT = 72
# Размер кадра по умолчанию, если у камеры его не спросить.
DEFAULT_SIZE = (1920, 1080)
PAGE_STYLE = """
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.cam{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.cam .live{position:relative;display:block;background:#000;aspect-ratio:16/9;text-decoration:none}
.cam .live img{width:100%;height:100%;object-fit:cover;display:block}
.cam .body{padding:12px 14px}
.cam h3{margin:0 0 2px;font-size:15px}
.cam .place{color:var(--muted);font-size:13px;margin:0 0 8px}
.live .onair{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.6);color:#fff;
             font-size:11px;padding:2px 8px;border-radius:999px;letter-spacing:.04em}
.live .onair i{display:inline-block;width:6px;height:6px;border-radius:50%;background:#ff4d4f;
               margin-right:5px;animation:blink 1.4s infinite}
@keyframes blink{50%{opacity:.25}}
.shot{position:relative;display:inline-block;max-width:100%}
.shot img{display:block;width:100%;border-radius:8px}
.shot b.box{position:absolute;border:2px solid #ff4d4f;border-radius:3px;
            box-shadow:0 0 0 1px rgba(0,0,0,.35)}
.shot b.box.calm{border-color:#7ba4ff;opacity:.55}
.rowline{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start}
.rowline>.shot{flex:0 0 260px}
.rowline>.text{flex:1 1 260px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.actions form{margin:0}
.actions button{margin-top:0;padding:8px 14px;font-size:14px}
.actions .ghost{background:var(--bg);color:var(--ink);border:1px solid var(--line)}
.meta{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin:6px 0 0}
.meta b{color:var(--ink);font-weight:600}
.event{border-bottom:1px solid var(--line);padding:14px 0}
.event:last-child{border-bottom:none}
.badge{font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px}
.badge.sure{background:var(--bad-bg);color:var(--bad)}
.badge.maybe{background:#fdf1de;color:#b26a00}
.pill.live{background:var(--bad-bg);color:var(--bad)}
.pill.rec{background:var(--bg);color:var(--muted);border:1px solid var(--line)}
.measure{background:var(--bg);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
         padding:10px 12px;margin-top:10px;font-size:13px;color:var(--muted)}
.pool{display:grid;grid-template-columns:repeat(auto-fill,minmax(122px,1fr));gap:8px;margin-top:12px}
.pt{display:block;text-decoration:none;color:var(--ink);background:var(--bg);
    border:1px solid var(--line);border-radius:8px;overflow:hidden}
.pt:hover{border-color:var(--accent)}
.pt img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}
.pt span{display:flex;justify-content:space-between;gap:6px;padding:4px 7px;
         font-size:11px;color:var(--muted)}
.pt b{color:var(--ink);font-weight:600}
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{style}{page_style}</style></head>
<body>{header}<div class="wrap">
<h1>{heading}<span class="svc extra">дополнительный сервис</span></h1>
<p class="sub">{lead}</p>
{body}
</div></body></html>"""


def render_cameras(
    states: tuple[CameraState, ...],
    pool: list[tuple[Camera, CapturedFrame]],
    keep_hours: int,
) -> str:
    """Страница со всеми камерами: картинка онлайн, состояние съёмки и пул снятого."""
    cards = "".join(_camera_card(state) for state in states)
    body = f'<div class="grid">{cards}</div>' if states else _empty_panel()
    body += _pool_panel(pool, keep_hours)
    page = PAGE_TEMPLATE.format(
        title="Камеры площадки",
        style=STYLE,
        page_style=PAGE_STYLE,
        header=render_header(CAMERAS_URL),
        heading="Камеры площадки",
        lead="Каждая камера снимает кадр по расписанию, хранит его сутки и сразу отдаёт "
        "основному сервису — оттуда берутся снимки для сверки с календарным планом. "
        "По клику открывается живой просмотр и весь архив съёмки.",
        body=body,
    )
    return page


def render_camera(
    camera: Camera,
    frames: tuple[CapturedFrame, ...],
    next_at: datetime,
    size: tuple[int, int],
    keep_hours: int,
) -> str:
    """Страница одной камеры: живой просмотр и архив снятого."""
    body = _live_panel(camera, next_at) + _archive_panel(camera, frames, size, keep_hours)
    page = PAGE_TEMPLATE.format(
        title=escape(camera.title),
        style=STYLE,
        page_style=PAGE_STYLE,
        header=render_header(CAMERAS_URL),
        heading=escape(camera.title),
        lead=escape(camera.place or "Камера площадки"),
        body=body,
    )
    return page


def _pool_panel(pool: list[tuple[Camera, CapturedFrame]], keep_hours: int) -> str:
    """Пул снятых кадров объекта: миниатюры с камерой и временем съёмки.

    Пул показывается миниатюрами, а не снимками: за смену их набирается несколько
    десятков, и полноразмерными они весили бы десятки мегабайт на одной странице.
    """
    if not pool:
        return (
            '<div class="panel"><h2>Пул снимков пуст</h2><p class="note">Кадры появятся '
            "после первой съёмки по расписанию.</p></div>"
        )
    tiles = "".join(_pool_tile(camera, frame) for camera, frame in pool)
    panel = f"""<div class="panel"><h2>Пул снимков объекта · {len(pool)}</h2>
<p class="note">Отсюда основной сервис берёт снимки на сверку с календарным планом.
У каждого кадра известны камера и время съёмки — больше ему ничего не нужно.
Хранится <b>{keep_hours} ч</b>: три камеры по три кадра в час дают за смену не более
{len(pool) if len(pool) > POOL_LIMIT else POOL_LIMIT} снимков.</p>
<div class="pool">{tiles}</div></div>"""
    return panel


def _pool_tile(camera: Camera, frame: CapturedFrame) -> str:
    """Одна миниатюра пула."""
    stamp = frame.captured_at.strftime(SHORT_TIME_FORMAT)
    tile = f"""<a class="pt" href="/cameras/{camera.camera_id}/photos/{frame.file_name}"
   title="{escape(camera.title)} · {frame.captured_at.strftime(TIME_FORMAT)}">
  <img src="/cameras/{camera.camera_id}/thumbs/{frame.file_name}" loading="lazy"
       alt="{escape(camera.camera_id)} {stamp}">
  <span>{escape(camera.camera_id)}<b>{stamp}</b></span></a>"""
    return tile


def _camera_card(state: CameraState) -> str:
    """Плитка одной камеры."""
    camera = state.camera
    last = state.last_captured_at.strftime(TIME_FORMAT) if state.last_captured_at else NEVER
    violations = (
        f'<span class="pill bad">отметок: {state.violations_total}</span>'
        if state.violations_total
        else '<span class="pill ok">отметок нет</span>'
    )
    kind = (
        '<span class="pill live">прямая трансляция</span>'
        if camera.is_live
        else '<span class="pill rec">демонстрационный ролик</span>'
    )
    card = f"""<div class="cam">
  <a class="live" href="/cameras/{camera.camera_id}"><span class="onair"><i></i>СМОТРЕТЬ ОНЛАЙН</span>
    <img src="{_preview(state)}" alt="{escape(camera.title)}" loading="lazy"></a>
  <div class="body">
    <h3><a href="/cameras/{camera.camera_id}">{escape(camera.title)}</a></h3>
    <p class="place">{escape(camera.place)}</p>
    {kind} {violations}
    <div class="meta"><span>снимок раз в <b>{camera.capture_period_minutes} мин</b></span>
      <span>в архиве <b>{state.frames_stored}</b></span>
      <span>не отправлено <b>{state.unsent_frames}</b></span></div>
    <div class="meta"><span>последняя съёмка: <b>{escape(last)}</b></span></div>
    {_camera_actions(camera.camera_id)}
  </div>
</div>"""
    return card


def _preview(state: CameraState) -> str:
    """Картинка плитки: последний снятый кадр, а пока его нет — кадр из камеры.

    Живые потоки на плитках не открываются намеренно: каждая открытая плитка
    держала бы на сервере свой декодер ради картинки величиной с ладонь.
    """
    if state.last_photo:
        return f"/cameras/{state.camera.camera_id}/photos/{state.last_photo}"
    return f"/cameras/{state.camera.camera_id}/frame.jpg"


def _camera_actions(camera_id: str) -> str:
    """Кнопки камеры: снять кадр и отправить снятое основному сервису."""
    block = f"""<div class="actions">
  <form method="post" action="/cameras/{camera_id}/capture"><button>Снять кадр</button></form>
  <form method="post" action="/cameras/{camera_id}/send">
    <button class="ghost">Отправить в основной сервис</button></form>
</div>"""
    return block


def _live_panel(camera: Camera, next_at: datetime) -> str:
    """Большой живой просмотр и расписание съёмки."""
    panel = f"""<div class="panel">
  <div class="live" style="position:relative;background:#000;border-radius:10px;overflow:hidden">
    <span class="onair"><i></i>ОНЛАЙН</span>
    <img src="/cameras/{camera.camera_id}/stream" style="width:100%;display:block"
         alt="{escape(camera.title)}"></div>
  <div class="meta"><span>съёмка раз в <b>{camera.capture_period_minutes} мин</b></span>
    <span>следующий кадр: <b>{next_at.strftime(SHORT_TIME_FORMAT)}</b></span>
    <span>проверка охраны труда: <b>{"включена" if camera.safety_enabled else "выключена"}</b></span></div>
  {f'<p class="note">{escape(camera.origin)}</p>' if camera.origin else ''}
  {f'<p class="note">{escape(camera.notes)}</p>' if camera.notes else ''}
  {_camera_actions(camera.camera_id)}
</div>"""
    return panel


def _archive_panel(
    camera: Camera, frames: tuple[CapturedFrame, ...], size: tuple[int, int], keep_hours: int
) -> str:
    """Архив снятых кадров камеры."""
    if not frames:
        return '<div class="panel"><h2>Архив съёмки</h2><p class="note">Кадров пока нет.</p></div>'
    rows = "".join(_archive_row(camera, frame, size) for frame in frames)
    panel = f"""<div class="panel"><h2>Архив съёмки · {len(frames)} кадров</h2>
<p class="note">Снимки хранятся с датой съёмки в метаданных: основной сервис разносит их
по этапам плана именно по ней. К отметке охраны труда пишется отрезок записи.
Срок хранения — <b>{keep_hours} ч</b>: кадр нужен, пока его не разобрали и не сверили
с планом, дальше он только занимает место.</p>
{rows}</div>"""
    return panel


def _archive_row(camera: Camera, frame: CapturedFrame, size: tuple[int, int]) -> str:
    """Одна строка архива: кадр, находки и что с ним стало."""
    sent = frame.sent_at.strftime(TIME_FORMAT) if frame.sent_at else "не отправлен"
    clip = (
        f' · <a href="/cameras/{camera.camera_id}/clips/{frame.clip_name}">отрезок записи</a>'
        if frame.clip_name
        else ""
    )
    origin = "прямая трансляция" if camera.is_live else f"секунда ролика {frame.source_second:.1f}"
    row = f"""<div class="event"><div class="rowline">
  {_shot(camera.camera_id, frame, size)}
  <div class="text">
    <b>{frame.captured_at.strftime(TIME_FORMAT)}</b>
    <div class="meta"><span>людей в кадре: <b>{len(frame.people)}</b></span>
      <span>отметок: <b>{len(frame.violations)}</b></span>
      <span>в основной сервис: <b>{escape(sent)}</b></span></div>
    {_findings_list(frame, camera)}
    <p class="note">{origin}{clip}</p>
  </div></div></div>"""
    return row


def _findings_list(frame: CapturedFrame, camera: Camera) -> str:
    """Перечень находок кадра."""
    if not frame.findings:
        return _nothing_checked(frame, camera)
    items = "".join(f"<li>{_finding_line(item)}</li>" for item in frame.violations)
    unclear = len(frame.unclear)
    tail = f'<p class="note">не разделено моделью: {unclear}</p>' if unclear else ""
    if not items:
        return f'<p class="note">Отметок нет.</p>{tail}'
    return f"<ul>{items}</ul>{tail}"


def _nothing_checked(frame: CapturedFrame, camera: Camera) -> str:
    """Объясняет, почему по кадру нет ни одной находки.

    Пустой перечень читается как «нарушений нет», а это разные вещи: чаще всего
    людей в кадре просто не нашлось или они слишком мелкие, чтобы судить о каске.
    """
    if not camera.safety_enabled:
        return '<p class="note">Проверка охраны труда для этой камеры выключена.</p>'
    if not frame.people:
        return (
            '<p class="note">Людей в кадре не нашлось — проверять было нечего. '
            "Это не значит, что нарушений нет: на обзорной камере человек занимает "
            "два десятка пикселей, и по такому силуэту о каске не судят.</p>"
        )
    return '<p class="note">Проверки по этому кадру не выполнялись.</p>'


def _finding_line(finding: SafetyFinding) -> str:
    """Одна находка словами."""
    badge = (
        '<span class="badge sure">уверенная отметка</span>'
        if finding.confident
        else '<span class="badge maybe">кандидат на проверку</span>'
    )
    line = (
        f"{escape(finding.title)} {badge} "
        f'<span class="note">уверенность {finding.confidence:.2f}, отрыв {finding.margin:+.3f}</span>'
    )
    return line


def _shot(camera_id: str, frame: CapturedFrame, size: tuple[int, int]) -> str:
    """Кадр с обведёнными областями."""
    width, height = size
    boxes = "".join(box_overlay(item.box, "" if item.is_violation else "calm", width, height) for item in frame.findings if item.box)
    if not frame.findings:
        boxes = "".join(box_overlay(region.box, "calm", width, height) for region in frame.people)
    shot = (
        f'<span class="shot"><img src="/cameras/{camera_id}/photos/{frame.file_name}" '
        f'alt="кадр {frame.captured_at.strftime(TIME_FORMAT)}" loading="lazy">{boxes}</span>'
    )
    return shot


def box_overlay(box: tuple[int, int, int, int], extra: str, width: int, height: int) -> str:
    """Рамка поверх кадра в долях его размера."""
    left, top, right, bottom = box
    style = (
        f"left:{100 * left / width:.2f}%;top:{100 * top / height:.2f}%;"
        f"width:{100 * (right - left) / width:.2f}%;height:{100 * (bottom - top) / height:.2f}%"
    )
    return f'<b class="box {extra}" style="{style}"></b>'


def _empty_panel() -> str:
    """Сообщение, когда камер нет вовсе."""
    panel = (
        '<div class="panel"><h2>Камер нет</h2><p class="note">Опишите камеры в '
        "<code>config/cameras.json</code> и соберите ролики командой "
        "<code>python materials/external/video-monitoring-master/docker/scene_gen.py "
        "--out data/cameras/scenes</code>.</p></div>"
    )
    return panel
