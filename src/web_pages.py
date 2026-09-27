"""Страницы веб-интерфейса сервиса.

Интерфейс минимальный по требованию ТЗ: показать демонстрацию, принять свои
данные и дать быстро оценить статус площадки. Страницы собираются строками,
без шаблонизатора — зависимостей вне таблицы стека сервис не заводит.
"""

from html import escape

from site_monitoring.adapters.run_storage import STATUS_DONE, STATUS_FAILED, RunState
from site_monitoring.entity import StageStatus
from site_monitoring.services.plan_fact import PlanFact

# Навигация одна на все страницы, включая собираемый стенд: пока наборы корешков
# у страниц расходились, переход уводил часть из них из виду. Третье поле непустое
# у тех страниц, которые на стенде являются не отдельным адресом, а его вкладкой.
MAIN_SERVICE_LABEL = "Основной сервис"
EXTRA_SERVICE_LABEL = "Дополнительный · видеонаблюдение"
MAIN_TABS = (
    ("/", "Загрузка данных", ""),
    ("/dashboard", "Дашборд руководителя", "dashboard"),
    ("/demo#shifts", "Смены по слотам", "shifts"),
    ("/demo#frames", "Просмотр снимков", "frames"),
    ("/demo#about", "Что мы строим", "about"),
)
EXTRA_TABS = (
    ("/cameras", "Камеры онлайн", ""),
    ("/safety", "Охрана труда", ""),
    ("/ingest", "Снимки с камер", ""),
)

STYLE = """
:root{--bg:#f4f5f7;--panel:#fff;--ink:#15181d;--muted:#5d6672;--line:#dfe3e8;
      --ok:#1f8a4c;--ok-bg:#e7f5ec;--bad:#c0392b;--bad-bg:#fbeceb;--accent:#1f6fd0;
      --extra:#7a4bbd}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#14171c;--panel:#1c2026;--ink:#eceff3;--muted:#9aa4b2;--line:#2c323b;
  --ok:#4ade80;--ok-bg:#16301f;--bad:#f87171;--bad-bg:#3a1c1a;--accent:#7ba4ff;
  --extra:#b79be8}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;padding:28px 16px;background:var(--bg);color:var(--ink);
     font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1120px;margin:0 auto}
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
.warn{background:#fdf1de;color:#b26a00}
.bar{height:10px;border-radius:5px;background:var(--bg);overflow:hidden;margin:10px 0 6px}
.bar i{display:block;height:100%;background:var(--accent);transition:width .4s}
.big{font-size:32px;font-weight:700;margin:0}
.big.delayed{color:var(--bad)} .big.ok{color:var(--ok)}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 4px}
.kpi{flex:1 1 150px;background:var(--bg);border-radius:10px;padding:10px 12px}
.kpi b{display:block;font-size:22px;line-height:1.25}
.kpi span{color:var(--muted);font-size:12px}
.conclusion{background:var(--bg);border-left:3px solid var(--accent);
            border-radius:0 8px 8px 0;padding:12px 14px;margin-top:12px}
.share{height:8px;border-radius:4px;background:var(--bg);overflow:hidden;min-width:90px}
.share i{display:block;height:100%;background:var(--accent)}
header{max-width:1120px;margin:0 auto 20px}
header .brand{font-size:13px;color:var(--muted);letter-spacing:.02em;margin-bottom:10px}
nav{display:flex;gap:2px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--line)}
nav.extra{border-bottom:none;margin-top:2px}
nav .railname{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
              color:var(--muted);padding:0 12px 0 0;white-space:nowrap}
nav.extra .railname{color:var(--extra)}
nav a{padding:9px 14px;font-size:14px;color:var(--muted);text-decoration:none;
      border-bottom:2px solid transparent;white-space:nowrap}
nav a:hover{color:var(--ink)}
nav a.here{color:var(--ink);font-weight:600;border-bottom-color:var(--accent)}
nav.extra a.here{border-bottom-color:var(--extra)}
form .field{margin-bottom:18px}
form .field:last-of-type{margin-bottom:8px}
.drop{border:1px dashed var(--line);border-radius:10px;background:var(--bg);
      padding:16px;text-align:center}
.drop input[type=file]{width:100%;border:none;background:none;padding:0;font:inherit;
                       color:var(--muted);cursor:pointer}
.drop b{display:block;font-size:14px;margin-bottom:4px;color:var(--ink)}
.hintline{color:var(--muted);font-size:13px;margin:6px 0 0}
button.primary{width:100%;padding:13px;font-size:15px}
.sample{background:var(--bg);border-radius:10px;padding:12px 14px;margin-top:16px}
.sample a{color:var(--accent)}
.done{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.done a{flex:1 1 200px;text-decoration:none;background:var(--bg);border-radius:10px;
        padding:12px 14px;color:var(--ink);border:1px solid var(--line)}
.done a:hover{border-color:var(--accent)}
.done b{display:block;font-size:14px}
.done span{color:var(--muted);font-size:12px}
.svc{display:inline-block;vertical-align:middle;margin-left:10px;padding:3px 10px;border-radius:999px;
     font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
     background:var(--bg);color:var(--muted);border:1px solid var(--line)}
.svc.extra{color:var(--extra);border-color:var(--extra)}
"""

HEADER_TEMPLATE = """<header>
  <div class="brand">Контроль строительных площадок · ЛЦТ-2026, задача №7</div>
  <nav><span class="railname">{main_label}</span>{main_tabs}</nav>
  <nav class="extra"><span class="railname">{extra_label}</span>{extra_tabs}</nav>
</header>"""


def render_header(current: str) -> str:
    """Собирает шапку с корешками обоих сервисов, подсвечивая текущую страницу."""
    header = HEADER_TEMPLATE.format(
        main_label=MAIN_SERVICE_LABEL,
        extra_label=EXTRA_SERVICE_LABEL,
        main_tabs=_render_links(MAIN_TABS, current),
        extra_tabs=_render_links(EXTRA_TABS, current),
    )
    return header


def _render_links(tabs: tuple[tuple[str, str, str], ...], current: str) -> str:
    """Корешки одного ряда обычными ссылками."""
    links = "".join(
        f'<a href="{href}" class="{"here" if href == current else ""}">{escape(title)}</a>'
        for href, title, _ in tabs
    )
    return links


def render_stand_nav() -> str:
    """Те же корешки для собираемой страницы стенда.

    Страницы, которые на стенде являются его вкладками, остаются кнопками — иначе
    переход между ними перезагружал бы страницу ради того, что уже загружено.
    """
    header = HEADER_TEMPLATE.format(
        main_label=MAIN_SERVICE_LABEL,
        extra_label=EXTRA_SERVICE_LABEL,
        main_tabs=_render_stand_links(MAIN_TABS),
        extra_tabs=_render_stand_links(EXTRA_TABS),
    )
    return header


def _render_stand_links(tabs: tuple[tuple[str, str, str], ...]) -> str:
    """Корешки ряда для стенда: свои вкладки кнопками, чужие страницы ссылками."""
    parts = []
    for href, title, view in tabs:
        if view:
            parts.append(f'<button class="tab" role="tab" data-view="{view}">{escape(title)}</button>')
        else:
            parts.append(f'<a class="tablink" href="{href}">{escape(title)}</a>')
    return "".join(parts)

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Контроль стройплощадок</title><style>{style}</style></head>
<body>{header}<div class="wrap">
<h1>Загрузка данных<span class="svc">основной сервис</span></h1>
<p class="sub">Приложите календарный план и снимки с камер — сервис разнесёт снимки
по этапам, определит технику, её работу и готовность фасада, а затем ответит,
идёт ли стройка по графику.</p>

<div class="panel">
  <form method="post" action="/runs" enctype="multipart/form-data">
    <div class="field">
      <label for="plan">1. Календарный план</label>
      <div class="drop">
        <b>Таблица Excel или CSV</b>
        <input id="plan" type="file" name="plan" accept=".xlsx,.xlsm,.csv,.txt" required>
      </div>
      <p class="hintline">Колонки: вид работ, дата начала, дата окончания.
      Сведений о технике не нужно — правила задаёт сервис.</p>
    </div>

    <div class="field">
      <label for="photos">2. Снимки с камер</label>
      <div class="drop">
        <b>Файлы изображений или архив ZIP</b>
        <input id="photos" type="file" name="photos" accept="image/*,.zip" multiple required>
      </div>
      <p class="hintline">Архив можно приложить как есть, сервис распакует его сам.
      Снимки привязываются к этапам по времени съёмки из метаданных; если времени нет —
      по порядку загрузки, и это будет отмечено в отчёте.</p>
    </div>

    <button class="primary" type="submit">Запустить сервис</button>
  </form>

  <div class="sample">
    <b>Нечего загрузить?</b> Возьмите готовый набор:
    <a href="/sample/plan">календарный план</a> на семь этапов и
    <a href="/sample/photos">49 снимков</a> с датами съёмки в метаданных.
  </div>
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
<body>{header}<div class="wrap">
<h1>Прогон {run_id}<span class="svc">основной сервис</span></h1>
<p class="sub">Загружен {created_at}. План: {plan_file}, снимков: {photo_count}.</p>

<div class="panel">
  <h2>Состояние</h2>
  <div id="status">{status_block}</div>
  {links_block}
</div>
{works_block}
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
DONE_LINKS_TEMPLATE = """<div class="done">
  <a href="/runs/{run_id}/dashboard"><b>Дашборд руководителя</b>
    <span>идём ли по графику, процент выполнения, заключение модели</span></a>
  <a href="/runs/{run_id}/report#shifts"><b>Смены по слотам</b>
    <span>календарный план с разбором каждого отрезка и снимками</span></a>
  <a href="/demo#about"><b>Что мы строим</b>
    <span>методика: правила этапов, признаки работы, ограничения</span></a>
</div>"""
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
        header=render_header("/"),
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
    links = DONE_LINKS_TEMPLATE.format(run_id=escape(state.run_id)) if state.status == STATUS_DONE else ""
    page = RUN_TEMPLATE.format(
        style=STYLE,
        header=render_header(""),
        run_id=escape(state.run_id),
        created_at=escape(state.created_at),
        plan_file=escape(state.plan_file or "не приложен"),
        photo_count=state.photo_count,
        status_block=_status_block(state),
        links_block=links,
        works_block=_works_block(state),
        script="" if finished else PROGRESS_SCRIPT,
    )
    return page


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ход работ по графику</title><style>{style}{chart_style}</style></head>
<body>{header}<div class="wrap">
<h1>Идём ли мы по графику<span class="svc">основной сервис</span></h1>
<p class="sub">План — объём смен по календарному графику в отрезках по {slot_minutes} минут.
Факт — отрезки, по которым подтверждена работа.</p>

<div class="panel hero">
  <div class="heronum">
    <p class="verdict {verdict_class}">{verdict}</p>
    <p class="heroshare">{completion}<span>% плана выполнено</span></p>
  </div>
  <div class="meter" title="Выполнено {counted} из {measured} измеренных отрезков">
    <i style="width:{completion}%"></i>
  </div>
  <p class="note">{counted} отрезков подтверждено из {measured} измеренных.
  Всего по графику {planned}.</p>
  {conclusion}
</div>

<div class="kpirow">
  <div class="stat"><b>{lag}</b><span>дня отставания</span></div>
  <div class="stat"><b>{limited}</b><span>вне контроля ИИ</span></div>
  <div class="stat"><b>{foreign}</b><span>с техникой не по этапу</span></div>
  <div class="stat"><b>{stage_count}</b><span>этапов в плане</span></div>
</div>

<div class="panel">
  <h2>Выполнение по этапам</h2>
  <div class="chartlegend">
    <span><i class="sw done"></i>подтверждено</span>
    <span><i class="sw miss"></i>не подтверждено</span>
    <span><i class="sw blind"></i>вне контроля ИИ</span>
  </div>
  <div class="bars">{bars}</div>
  <p class="hintline">Отрезки вне контроля ИИ вычтены из плана, а не записаны
  в невыполненные: фронт работ не попал в кадр, и это не простой подрядчика.</p>
</div>

<div class="panel">
  <h2>Таблица</h2>
  <table><thead><tr><th>Вид работ</th><th>Дата</th><th>Подтверждено</th>
  <th>Выполнение</th><th>Вне контроля</th><th>Вывод</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>
</div></body></html>
"""

CHART_STYLE = """
.hero{display:grid;grid-template-columns:auto 1fr;gap:6px 24px;align-items:end;padding:22px 24px}
.heronum{grid-column:1/-1;display:flex;align-items:baseline;gap:18px;flex-wrap:wrap}
.verdict{font-size:30px;font-weight:700;margin:0;letter-spacing:-.01em}
.verdict.delayed{color:var(--bad)} .verdict.ok{color:var(--ok)}
.heroshare{font-size:60px;font-weight:700;margin:0;line-height:1;letter-spacing:-.02em}
.heroshare span{font-size:15px;font-weight:600;color:var(--muted);margin-left:8px;letter-spacing:0}
.meter{grid-column:1/-1;height:12px;border-radius:6px;background:var(--track);overflow:hidden;margin:14px 0 4px}
.meter i{display:block;height:100%;border-radius:6px;background:var(--done)}
.kpirow{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.stat{flex:1 1 150px;background:var(--panel);border:1px solid var(--line);
      border-radius:12px;padding:14px 16px}
.stat b{display:block;font-size:26px;font-weight:700;line-height:1.15}
.stat span{color:var(--muted);font-size:12px}
.chartlegend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-bottom:14px}
.sw{display:inline-block;width:14px;height:14px;border-radius:4px;margin-right:6px;vertical-align:-2px}
.sw.done{background:var(--done)} .sw.miss{background:var(--miss)} .sw.blind{background:var(--blind)}
.bars{display:flex;flex-direction:column;gap:14px}
.barrow{display:grid;grid-template-columns:minmax(180px,300px) 1fr auto;gap:16px;align-items:center}
.barname{font-size:13px;line-height:1.3}
.barname span{display:block;color:var(--muted);font-size:11px}
.stack{display:flex;gap:2px;height:26px}
.seg{height:100%;min-width:2px}
.seg:first-child{border-radius:5px 0 0 5px} .seg:last-child{border-radius:0 5px 5px 0}
.seg.only{border-radius:5px}
.seg.done{background:var(--done)} .seg.miss{background:var(--miss)} .seg.blind{background:var(--blind)}
.barvalue{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;min-width:44px;text-align:right}
.barempty{color:var(--muted);font-size:12px}
:root{--done:#1f8a4c;--miss:#b9bcc2;--blind:#b26a00;--track:#e8eaed}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --done:#4ade80;--miss:#6b7280;--blind:#fbbf24;--track:#2c323b}}
"""

NO_CONCLUSION_TEMPLATE = (
    '<p class="note">Заключение не сформировано. '
    '<a href="/dashboard/summary">Сформировать</a> — это обращение к модели, около десяти секунд.</p>'
)
CONCLUSION_TEMPLATE = (
    '<div class="conclusion"><p>{summary}</p>'
    '<p class="note">В первую очередь заняться: <b>{risk}</b>. '
    'Заключение сформировано языковой моделью по посчитанным числам.</p></div>'
)
NO_DATA_TEXT = '<tr><td colspan="6" class="note">Разобранных смен нет.</td></tr>'
NO_BARS_TEXT = '<p class="note">Разобранных смен нет.</p>'
STATUS_PILLS = {
    StageStatus.ON_SCHEDULE: '<span class="pill ok">по графику</span>',
    StageStatus.RISK_OF_DELAY: '<span class="pill warn">риск</span>',
    StageStatus.DELAYED: '<span class="pill bad">отставание</span>',
}
DELAYED_CLASSES = {StageStatus.DELAYED: "delayed", StageStatus.ON_SCHEDULE: "ok"}
PERCENT = 100
SEGMENT_TITLES = {
    "done": "подтверждено отрезков",
    "miss": "не подтверждено отрезков",
    "blind": "вне контроля ИИ, отрезков",
}


def _segment(kind: str, count: int, planned: int, only: bool) -> str:
    """Одна доля столбика: ширина по доле от планового объёма."""
    if count <= 0:
        return ""
    width = round(PERCENT * count / planned, 2) if planned else 0
    extra = " only" if only else ""
    title = f"{SEGMENT_TITLES[kind]}: {count}"
    return f'<div class="seg {kind}{extra}" style="width:{width}%" title="{title}"></div>'


def _stage_bars(report: PlanFact) -> str:
    """Столбики выполнения: подтверждено, не подтверждено, вне контроля."""
    if not report.stages:
        return NO_BARS_TEXT
    rows = ""
    for stage in report.stages:
        planned = stage.planned_slots or 1
        parts = (("done", stage.counted_slots), ("miss", stage.lag_slots), ("blind", stage.limited_slots))
        filled = [kind for kind, count in parts if count > 0]
        stack = "".join(
            _segment(kind, count, planned, only=len(filled) == 1) for kind, count in parts
        )
        value = f"{round(stage.completion * PERCENT)}%" if stage.measured_slots else "—"
        rows += (
            f'<div class="barrow"><div class="barname">{escape(stage.title)}'
            f"<span>{escape(stage.work_id)} · {escape(stage.plan_date)}</span></div>"
            f'<div class="stack">{stack}</div>'
            f'<div class="barvalue">{value}</div></div>'
        )
    return rows


def _stage_rows(report: PlanFact) -> str:
    """Строки таблицы по этапам."""
    if not report.stages:
        return NO_DATA_TEXT
    rows = ""
    for stage in report.stages:
        share = round(stage.completion * PERCENT)
        rows += (
            f"<tr><td>{escape(stage.title)}</td><td>{escape(stage.plan_date)}</td>"
            f"<td>{stage.counted_slots} из {stage.measured_slots}</td>"
            f"<td>{share}%</td>"
            f"<td>{stage.limited_slots or '—'}</td>"
            f"<td>{STATUS_PILLS[stage.status]}</td></tr>"
        )
    return rows


def render_dashboard(report: PlanFact, conclusion: dict[str, str] | None, foreign: int = 0) -> str:
    """Собирает страницу с ответом на вопрос, идём ли мы по графику."""
    block = NO_CONCLUSION_TEMPLATE
    if conclusion is not None:
        block = CONCLUSION_TEMPLATE.format(
            summary=escape(conclusion.get("заключение", "")),
            risk=escape(conclusion.get("на_что_смотреть", "")),
        )
    slot_minutes = report.stages[0].slot_minutes if report.stages else 0
    page = DASHBOARD_TEMPLATE.format(
        style=STYLE,
        chart_style=CHART_STYLE,
        header=render_header("/dashboard"),
        verdict=escape(report.status.value),
        verdict_class=DELAYED_CLASSES.get(report.status, ""),
        completion=round(report.completion * PERCENT),
        counted=report.counted_slots,
        measured=report.measured_slots,
        planned=report.planned_slots,
        lag=report.lag_days,
        limited=report.limited_slots,
        foreign=foreign,
        stage_count=len(report.stages),
        slot_minutes=slot_minutes,
        conclusion=block,
        bars=_stage_bars(report),
        rows=_stage_rows(report),
    )
    return page
