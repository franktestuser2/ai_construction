"""Схема обработки снимков нескольких камер и передача пула в основной алгоритм.

Страница камер существует ради масштабирования: камер на объекте может быть сколько
угодно, и логика от их числа не меняется. Объяснить это словами мало — здесь схема,
по которой видно, где кадры сводятся и по какому правилу.
"""

SCHEME_SVG = """<svg class="scheme" viewBox="0 0 980 330" role="img"
  aria-label="Схема обработки снимков нескольких камер объекта">
  <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
    orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker></defs>
  <g class="sbox">
    <rect x="8" y="14" width="186" height="62" rx="11"/>
    <rect x="8" y="98" width="186" height="62" rx="11"/>
    <rect x="8" y="182" width="186" height="62" rx="11"/>
  </g>
  <g class="stext">
    <text x="101" y="40">Камера 1</text><text x="101" y="60" class="dim">свой ракурс</text>
    <text x="101" y="124">Камера 2</text><text x="101" y="144" class="dim">свой ракурс</text>
    <text x="101" y="208">Камера 3</text><text x="101" y="228" class="dim">свой ракурс</text>
  </g>
  <g class="sarrow">
    <path d="M198 45 C 232 45 232 118 262 125" marker-end="url(#ar)"/>
    <path d="M198 129 L262 129" marker-end="url(#ar)"/>
    <path d="M198 213 C 232 213 232 140 262 133" marker-end="url(#ar)"/>
  </g>
  <g class="sbox accent"><rect x="266" y="98" width="168" height="62" rx="11"/></g>
  <g class="stext">
    <text x="350" y="124">Пул снимков</text>
    <text x="350" y="144" class="dim">кадр раз в 20 минут</text>
  </g>
  <g class="sbox plan"><rect x="266" y="14" width="168" height="62" rx="11"/></g>
  <g class="stext">
    <text x="350" y="40">Календарный план</text>
    <text x="350" y="60" class="dim">этап на дату съёмки</text>
  </g>
  <g class="sarrow">
    <path d="M438 45 C 480 45 480 112 520 118" marker-end="url(#ar)"/>
    <path d="M438 129 L520 133" marker-end="url(#ar)"/>
  </g>
  <g class="sbox"><rect x="524" y="88" width="190" height="82" rx="11"/></g>
  <g class="stext">
    <text x="619" y="114">Разбор по камерам</text>
    <text x="619" y="134" class="dim">техника этапа,</text>
    <text x="619" y="152" class="dim">работа между кадрами</text>
  </g>
  <g class="sarrow"><path d="M718 129 L768 129" marker-end="url(#ar)"/></g>
  <g class="sbox ok"><rect x="772" y="88" width="200" height="82" rx="11"/></g>
  <g class="stext">
    <text x="872" y="114">Сведение</text>
    <text x="872" y="134" class="dim">отрезок засчитан,</text>
    <text x="872" y="152" class="dim">если работа хотя бы на одной</text>
  </g>
  <g class="sarrow"><path d="M872 174 L872 214" marker-end="url(#ar)"/></g>
  <g class="sbox ok"><rect x="524" y="218" width="448" height="62" rx="11"/></g>
  <g class="stext">
    <text x="748" y="244">Девять отрезков смены → день по графику или отставание</text>
    <text x="748" y="264" class="dim">отрезок невидим, только если площадку не видит ни одна камера</text>
  </g>
</svg>"""


def render_scheme() -> str:
    """Схема того, как снимки нескольких камер превращаются в вердикт по плану."""
    panel = f"""<div class="panel"><h2>Как это обрабатывается, когда камер несколько</h2>
<p class="note">Страница камер сделана ради масштабирования: камер на объекте может быть
сколько угодно, и логика от их числа не меняется.</p>
{SCHEME_SVG}
<ul class="rules">
  <li><b>Каждая камера разбирается своим рядом кадров.</b> Работа между кадрами
      определяется сравнением соседних снимков, а соседние снимки разных камер
      отличаются ракурсом, а не движением техники.</li>
  <li><b>Отрезок засчитан, если работа подтверждена хотя бы на одной камере.</b>
      Работа, не попавшая в одну камеру, вполне могла попасть в другую.</li>
  <li><b>Отрезок считается невидимым, только если площадку не видит ни одна камера.</b>
      Достаточно одной видящей — и отрезок разбирается по ней, а не уходит на ручную проверку.</li>
  <li><b>Вид работ не выбирается руками.</b> У снимка есть дата съёмки, у объекта —
      календарный план; этап на эту дату и задаёт, какая техника должна быть на площадке.</li>
</ul></div>"""
    return panel


def render_handoff() -> str:
    """Кнопка передачи пула в основной алгоритм и честная оговорка при нажатии."""
    panel = """<div class="panel"><h2>Передача в основной алгоритм</h2>
<p class="note">Пул готов к разбору: у каждого кадра известны камера и время съёмки —
больше основному алгоритму ничего не нужно.</p>
<details class="handoff"><summary>Отправить на обработку в основной алгоритм</summary>
<div class="hnote"><b>Кнопка демонстрирует решение и пока ничего не отправляет.</b>
Она заработает, когда по этим объектам появится календарный график: сверять факт
не с чем, пока нет плана. Всё остальное для этого готово — разбор по камерам,
сведение по правилу «хотя бы на одной» и расчёт отставания.</div></details></div>"""
    return panel

SCHEME_STYLE = """
.scheme{display:block;width:100%;height:auto;margin:14px 0 6px}
.scheme .sbox rect{fill:var(--bg);stroke:var(--line);stroke-width:1.5}
.scheme .sbox.accent rect{stroke:var(--extra);stroke-width:2}
.scheme .sbox.plan rect{stroke:var(--accent);stroke-width:2}
.scheme .sbox.ok rect{stroke:var(--ok);stroke-width:2}
.scheme .stext text{fill:var(--ink);font-size:14px;font-weight:600;text-anchor:middle}
.scheme .stext text.dim{fill:var(--muted);font-size:12px;font-weight:400}
.scheme .sarrow{color:var(--muted)}
.scheme .sarrow path{fill:none;stroke:currentColor;stroke-width:1.6}
ul.rules{margin:14px 0 0;padding-left:20px}
ul.rules li{margin-bottom:8px;font-size:14px}
ul.rules b{font-weight:600}
details.handoff{margin-top:12px}
details.handoff>summary{list-style:none;cursor:pointer;display:block;text-align:center;
     padding:13px;font-size:15px;font-weight:600;color:#fff;background:var(--extra);
     border-radius:9px}
details.handoff>summary::-webkit-details-marker{display:none}
details.handoff>summary::marker{content:""}
details.handoff[open]>summary{background:var(--bg);color:var(--extra);
     box-shadow:inset 0 0 0 1px var(--extra-line)}
.hnote{background:var(--extra-bg);border:1px solid var(--extra-line);border-radius:10px;
       padding:13px 15px;margin-top:10px;font-size:14px;line-height:1.5}
.hnote b{display:block;margin-bottom:5px}
"""
