"""Страницы веб-интерфейса сервиса.

Интерфейс минимальный по требованию ТЗ: показать демонстрацию, принять свои
данные и дать быстро оценить статус площадки. Страницы собираются строками,
без шаблонизатора — зависимостей вне таблицы стека сервис не заводит.
"""

from html import escape

from site_monitoring.adapters.run_storage import STATUS_DONE, STATUS_FAILED, RunState

STYLE = """
:root{--bg:#f4f5f7;--panel:#fff;--ink:#15181d;--muted:#5d6672;--line:#dfe3e8;
      --ok:#1f8a4c;--ok-bg:#e7f5ec;--bad:#c0392b;--bad-bg:#fbeceb;--accent:#1f6fd0}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#14171c;--panel:#1c2026;--ink:#eceff3;--muted:#9aa4b2;--line:#2c323b;
  --ok:#4ade80;--ok-bg:#16301f;--bad:#f87171;--bad-bg:#3a1c1a;--accent:#7ba4ff}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;padding:28px 16px;background:var(--bg);color:var(--ink);
     font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:23px;margin:0 0 4px}
h2{font-size:17px;margin:0 0 10px}
.sub{color:var(--muted);margin:0 0 22px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;
       padding:18px;margin-bottom:16px}
label{display:block;margin:12px 0 4px;font-weight:600;font-size:14px}
input[type=file]{width:100%;font:inherit;padding:8px;border:1px dashed var(--line);
                 border-radius:8px;background:var(--bg)}
button{font:inherit;font-weight:600;padding:10px 18px;border-radius:9px;border:none;
       background:var(--accent);color:#fff;cursor:pointer;margin-top:14px}
a.btn{display:inline-block;text-decoration:none}
.note{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:12px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.ok{background:var(--ok-bg);color:var(--ok)}
.bad{background:var(--bad-bg);color:var(--bad)}
.bar{height:10px;border-radius:5px;background:var(--bg);overflow:hidden;margin:10px 0 6px}
.bar i{display:block;height:100%;background:var(--accent);transition:width .4s}
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Контроль стройплощадок</title><style>{style}</style></head>
<body><div class="wrap">
<h1>Контроль строительных площадок по снимкам</h1>
<p class="sub">План-факт по календарному графику: какая техника нужна этапу, видна ли она
на снимках, работала ли, и какова готовность фасада.</p>

<div class="panel">
  <h2>Посмотреть демонстрацию</h2>
  <p class="note">Готовый разбор семи этапов открывается сразу, без обращения к моделям.</p>
  {demo_link}
</div>

<div class="panel">
  <h2>Загрузить свои данные</h2>
  <form method="post" action="/runs" enctype="multipart/form-data">
    <label for="plan">Календарный план — Excel или CSV</label>
    <input id="plan" type="file" name="plan" accept=".xlsx,.xlsm,.csv,.txt" required>
    <p class="note">Колонки: вид работ, дата начала, дата окончания. Сведения о технике
    не нужны — правила берёт на себя сервис.</p>
    <label for="photos">Снимки с камер</label>
    <input id="photos" type="file" name="photos" accept="image/*" multiple required>
    <p class="note">Снимки привязываются к этапам по времени съёмки из метаданных.
    Если времени нет, они раскладываются по этапам в порядке загрузки, и это будет
    отмечено в отчёте.</p>
    <button type="submit">Разобрать</button>
  </form>
</div>

<div class="panel">
  <h2>Прогоны</h2>
  {runs}
</div>
</div></body></html>
"""

RUN_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Прогон {run_id}</title><style>{style}</style></head>
<body><div class="wrap">
<h1>Прогон {run_id}</h1>
<p class="sub">Загружен {created_at}. План: {plan_file}, снимков: {photo_count}.</p>

<div class="panel">
  <h2>Состояние</h2>
  <div id="status">{status_block}</div>
</div>
{works_block}
<p><a href="/">← к началу</a></p>
</div>
{script}
</body></html>
"""

PROGRESS_SCRIPT = """<script>
const target = document.getElementById('status');
async function poll(){
  const response = await fetch(location.pathname + '/state');
  if(!response.ok){ return; }
  const state = await response.json();
  target.innerHTML = `<div class="bar"><i style="width:${state.percent}%"></i></div>
    <p class="note">${state.status}: разобрано ${state.done_frames} из ${state.total_frames} снимков.
    ${state.stage_title ? 'Сейчас: ' + state.stage_title : ''}</p>`;
  if(state.status === 'готов' || state.status === 'ошибка'){ location.reload(); return; }
  setTimeout(poll, 3000);
}
poll();
</script>"""

NO_RUNS_TEXT = '<p class="note">Пока ни одного прогона.</p>'
DEMO_READY_LINK = '<a class="btn" href="/demo"><button type="button">Открыть отчёт</button></a>'
DEMO_MISSING_LINK = '<p class="note">Отчёт не собран: запустите <code>scripts/build_demo_stand.py</code>.</p>'
ON_SCHEDULE_PILL = '<span class="pill ok">по графику</span>'
OFF_SCHEDULE_PILL = '<span class="pill bad">не подтверждён</span>'


def _runs_table(runs: tuple[RunState, ...]) -> str:
    """Список прогонов со ссылками."""
    if not runs:
        return NO_RUNS_TEXT
    rows = "".join(
        f'<tr><td><a href="/runs/{escape(run.run_id)}">{escape(run.run_id)}</a></td>'
        f"<td>{escape(run.created_at)}</td><td>{escape(run.status)}</td>"
        f"<td>{run.photo_count}</td></tr>"
        for run in runs
    )
    table = f"<table><thead><tr><th>Прогон</th><th>Загружен</th><th>Состояние</th>"
    table += f"<th>Снимков</th></tr></thead><tbody>{rows}</tbody></table>"
    return table


def render_index(runs: tuple[RunState, ...], demo_ready: bool) -> str:
    """Собирает главную страницу."""
    page = INDEX_TEMPLATE.format(
        style=STYLE,
        demo_link=DEMO_READY_LINK if demo_ready else DEMO_MISSING_LINK,
        runs=_runs_table(runs),
    )
    return page


def _status_block(state: RunState) -> str:
    """Блок состояния прогона."""
    if state.status == STATUS_FAILED:
        return f'<p><span class="pill bad">ошибка</span> {escape(state.error)}</p>'
    if state.status == STATUS_DONE:
        return (
            f'<p><span class="pill ok">готов</span> Разобрано {state.done_frames} снимков '
            f"по {state.stages_total} этапам.</p>"
            f'<p class="note">Привязка снимков: {escape(state.binding)}.</p>'
        )
    block = f'<div class="bar"><i style="width:{state.percent}%"></i></div>'
    block += f'<p class="note">{escape(state.status)}: разобрано {state.done_frames} из {state.total_frames}.</p>'
    return block


def _works_block(state: RunState) -> str:
    """Таблица итогов по этапам плана."""
    if state.status != STATUS_DONE or not state.works:
        return ""
    rows = ""
    for work in state.works:
        verdict = ON_SCHEDULE_PILL if work.get("on_schedule") else OFF_SCHEDULE_PILL
        rows += (
            f'<tr><td>{escape(str(work["title"]))}</td>'
            f'<td>{escape(str(work["work_id"]))}</td>'
            f'<td>{work["photo_count"]}</td>'
            f'<td>{work["counted_slots"]} из {work["planned_slots"]}</td>'
            f"<td>{verdict}</td></tr>"
        )
    block = '<div class="panel"><h2>Этапы плана</h2><table><thead><tr>'
    block += "<th>Вид работ</th><th>Правила</th><th>Снимков</th><th>Слотов засчитано</th>"
    block += f"<th>Вывод</th></tr></thead><tbody>{rows}</tbody></table></div>"
    return block


def render_run(state: RunState) -> str:
    """Собирает страницу прогона."""
    finished = state.status in (STATUS_DONE, STATUS_FAILED)
    page = RUN_TEMPLATE.format(
        style=STYLE,
        run_id=escape(state.run_id),
        created_at=escape(state.created_at),
        plan_file=escape(state.plan_file or "не приложен"),
        photo_count=state.photo_count,
        status_block=_status_block(state),
        works_block=_works_block(state),
        script="" if finished else PROGRESS_SCRIPT,
    )
    return page
