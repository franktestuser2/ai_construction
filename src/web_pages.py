"""Страницы веб-интерфейса сервиса.

Интерфейс минимальный по требованию ТЗ: показать демонстрацию, принять свои
данные и дать быстро оценить статус площадки. Страницы собираются строками,
без шаблонизатора — зависимостей вне таблицы стека сервис не заводит.
"""

from html import escape

from page_shell import (
    EXTRA_MENU_NOTE,
    EXTRA_MENU_TITLE,
    STYLE,
    render_header,
    render_service_tiles,
)
from site_monitoring.adapters.run_storage import STATUS_DONE, STATUS_FAILED, RunState
from site_monitoring.entity import StageStatus
from site_monitoring.services.plan_fact import PlanFact

# Навигация одна на все страницы, включая собираемый стенд: пока наборы корешков
# у страниц расходились, переход уводил часть из них из виду. Третье поле непустое
# у тех страниц, которые на стенде являются не отдельным адресом, а его вкладкой.
INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Контроль стройплощадок</title><style>{style}</style></head>
<body>{header}<div class="wrap">
<h1>Загрузка данных</h1>
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

<div class="panel extrapanel">
  <h2>{menu_title}<span class="svc extra">дополнительный сервис</span></h2>
  <p class="note">{menu_note}. Работает сам по себе: план ему не нужен.</p>
  <div class="tiles">{extra_tiles}</div>
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
<h1>Прогон {run_id}</h1>
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
        menu_title=EXTRA_MENU_TITLE,
        menu_note=EXTRA_MENU_NOTE,
        extra_tiles=render_service_tiles(),
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
<h1>Идём ли мы по графику</h1>
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
