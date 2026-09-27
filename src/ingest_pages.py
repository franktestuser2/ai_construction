"""Страница приёмной: что пришло с камер и как пустить это в разбор."""

from html import escape

from web_pages import STYLE, render_header

INGEST_URL = "/ingest"
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Приёмная камер</title><style>{style}</style></head>
<body>{header}<div class="wrap">
<h1>Снимки с камер</h1>
<p class="sub">Сюда камеры складывают кадры, снятые по расписанию. Разбор запускается
по ним так же, как по загруженному архиву: сервис сверяет дату съёмки с датами плана.</p>
{body}
</div></body></html>"""


def render_ingest(queue: dict[str, int], works: dict[str, str], note: str) -> str:
    """Собирает страницу приёмной."""
    body = _queue_panel(queue) + _run_panel(queue, works) + _note_panel(note)
    page = PAGE_TEMPLATE.format(style=STYLE, header=render_header(INGEST_URL), body=body)
    return page


def _queue_panel(queue: dict[str, int]) -> str:
    """Что лежит в очереди по камерам."""
    total = sum(queue.values())
    if not total:
        return (
            '<div class="panel"><h2>Очередь пуста</h2><p class="note">Снимите кадр на странице '
            '<a href="/cameras">камер</a> и нажмите «Отправить в основной сервис» — '
            "либо дождитесь съёмки по расписанию.</p></div>"
        )
    rows = "".join(
        f"<tr><td>{escape(camera_id)}</td><td>{count}</td></tr>" for camera_id, count in sorted(queue.items())
    )
    panel = f"""<div class="panel"><h2>В очереди {total} снимков</h2>
<table><tr><th>Камера</th><th>Снимков</th></tr>{rows}</table></div>"""
    return panel


def _run_panel(queue: dict[str, int], works: dict[str, str]) -> str:
    """Форма запуска разбора по накопленным кадрам."""
    if not sum(queue.values()):
        return ""
    options = "".join(
        f'<option value="{escape(work_id)}">{escape(title)}</option>'
        for work_id, title in sorted(works.items())
    )
    panel = f"""<div class="panel"><h2>Пустить в разбор</h2>
<p class="note">Календарного плана у камер нет, поэтому для разбора он составляется здесь:
один этап на сегодняшний день. Так снятое сегодня попадает в тот вид работ, который
на площадке действительно идёт.</p>
<form method="post" action="/ingest/run">
  <label for="work">Вид работ на сегодня</label>
  <select id="work" name="work_id" style="width:100%;padding:10px;border-radius:8px;
          border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit">
    {options}
  </select>
  <button class="primary">Запустить разбор</button>
</form></div>"""
    return panel


def _note_panel(note: str) -> str:
    """Оговорка о том, что видно на кадрах симулятора."""
    if not note:
        return ""
    panel = f'<div class="panel"><h2>О чём предупредить</h2><p class="note">{escape(note)}</p></div>'
    return panel
