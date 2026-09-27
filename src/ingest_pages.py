"""Страница приёмной: что пришло с камер объекта и как пустить это в разбор."""

from html import escape

from page_shell import STYLE, render_header
from site_monitoring.adapters.uploaded_plan_reader import UploadedStage

INGEST_URL = "/ingest"
DATE_FORMAT = "%d.%m.%Y"
PAGE_STYLE = """
.stage{background:var(--bg);border-left:3px solid var(--accent);border-radius:0 10px 10px 0;
       padding:14px 16px;margin-top:12px}
.stage b{display:block;font-size:16px;line-height:1.35}
.stage span{color:var(--muted);font-size:13px}
.flow{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.step{background:var(--bg);border-radius:10px;padding:12px 14px}
.step b{display:block;font-size:13px;margin-bottom:3px}
.step span{color:var(--muted);font-size:12px}
"""
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Приёмная камер</title><style>{style}{page_style}</style></head>
<body>{header}<div class="wrap">
<h1>Снимки с камер<span class="svc extra">дополнительный сервис</span></h1>
<p class="sub">Камеры объекта складывают сюда кадры, снятые по расписанию. Вид работ
руками не выбирается: этап берётся из календарного плана объекта по дате съёмки.</p>
{body}
</div></body></html>"""


def render_ingest(
    queue: dict[str, int], stage: UploadedStage | None, stages_total: int, note: str
) -> str:
    """Собирает страницу приёмной."""
    body = _plan_panel(stage, stages_total) + _queue_panel(queue, stage) + _note_panel(note)
    page = PAGE_TEMPLATE.format(
        style=STYLE, page_style=PAGE_STYLE, header=render_header(INGEST_URL), body=body
    )
    return page


def _plan_panel(stage: UploadedStage | None, stages_total: int) -> str:
    """Что говорит календарный план про сегодняшний день."""
    if stage is None:
        inside = (
            '<p class="note">На сегодняшний день в плане объекта работ нет: '
            "снятое разбирать не с чем.</p>"
        )
    else:
        period = f"{stage.start.strftime(DATE_FORMAT)} — {stage.finish.strftime(DATE_FORMAT)}"
        inside = f"""<div class="stage"><b>{escape(stage.full_name)}</b>
<span>этап плана на сегодня · {period}</span></div>
<p class="note">Для этого вида работ сервис знает, какая техника должна быть на площадке, —
по ней и проверяются снимки.</p>"""
    panel = f"""<div class="panel"><h2>Календарный план объекта</h2>
<p class="note">Этапов в плане: {stages_total}. Снимок попадает в этап по дате съёмки
из своих метаданных, поэтому выбирать вид работ не нужно.</p>
{inside}{_flow()}</div>"""
    return panel


def _flow() -> str:
    """Короткая схема пути кадра от камеры до вердикта."""
    steps = (
        ("Камеры объекта", "снимают раз в 20 минут, каждая со своего ракурса"),
        ("Очередь", "кадры приходят сюда с именем камеры и датой съёмки"),
        ("Этап из плана", "по дате съёмки — вид работ и положенная ему техника"),
        ("Разбор по камерам", "каждая камера разбирается своим рядом кадров"),
        ("Сведение", "отрезок засчитан, если работа видна хотя бы на одной камере"),
    )
    cards = "".join(
        f'<div class="step"><b>{escape(title)}</b><span>{escape(text)}</span></div>'
        for title, text in steps
    )
    return f'<div class="flow">{cards}</div>'


def _queue_panel(queue: dict[str, int], stage: UploadedStage | None) -> str:
    """Что лежит в очереди и кнопка разбора."""
    total = sum(queue.values())
    if not total:
        return (
            '<div class="panel"><h2>Очередь пуста</h2><p class="note">Снимите кадр на странице '
            '<a href="/cameras">камер</a> или дождитесь съёмки по расписанию — '
            "контур отдаёт снятое сам.</p></div>"
        )
    rows = "".join(
        f"<tr><td>{escape(camera_id)}</td><td>{count}</td></tr>"
        for camera_id, count in sorted(queue.items())
    )
    button = (
        '<form method="post" action="/ingest/run"><button class="primary">'
        "Разобрать снимки с камер</button></form>"
        if stage is not None
        else '<p class="note">Разбор не запускается: на сегодня в плане работ нет.</p>'
    )
    panel = f"""<div class="panel"><h2>В очереди {total} снимков</h2>
<table><tr><th>Камера</th><th>Снимков</th></tr>{rows}</table>
{button}</div>"""
    return panel


def _note_panel(note: str) -> str:
    """Оговорка о том, что видно на кадрах камер."""
    if not note:
        return ""
    panel = f'<div class="panel"><h2>О чём предупредить</h2><p class="note">{escape(note)}</p></div>'
    return panel
