"""Оболочка страниц сервиса: общий стиль и навигация.

Навигация одна на все страницы, включая собираемый стенд: пока наборы корешков
у страниц расходились, переход уводил часть из них из виду.

Второй сервис свёрнут в одну кнопку с меню. Разложенный в ряд, он читался как
продолжение основного, и было не видно, где кончается одно и начинается другое.
У каждого пункта меню свой цвет, значок и строка о том, что там делают.
"""

from html import escape

EXTRA_SERVICE_LABEL = "Дополнительный сервис"
MAIN_TABS = (
    ("/", "Загрузка данных", ""),
    ("/dashboard", "Дашборд руководителя", "dashboard"),
    ("/demo#shifts", "Смены по слотам", "shifts"),
    ("/demo#frames", "Просмотр снимков", "frames"),
    ("/demo#about", "Что мы строим", "about"),
)
# Второй сервис свёрнут в одну кнопку с меню: разложенный в ряд, он читался как
# продолжение основного, и было не видно, где кончается одно и начинается другое.
# У каждого пункта свой цвет и строка о том, что там делают.
EXTRA_TABS = (
    ("/cameras", "Камеры онлайн", "cam", "Живая картинка, архив съёмки, снимок по кнопке"),
    ("/safety", "Охрана труда", "saf", "Отметки моделей с кадром-доказательством"),
    ("/ingest", "Снимки с камер", "ing", "Что пришло с камер и запуск разбора"),
)
EXTRA_MENU_TITLE = "Видеонаблюдение площадки"
EXTRA_MENU_NOTE = "Самостоятельный сервис: снимает площадку и отдаёт кадры основному"
ICONS = {
    "cam": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
        '<rect x="2.5" y="6.5" width="14" height="11" rx="2.5"/>'
        '<path d="M16.5 10.5l5-2.5v8l-5-2.5z"/><circle cx="9.5" cy="12" r="2.6"/></svg>'
    ),
    "saf": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
        '<path d="M4.5 13.5a7.5 7.5 0 0115 0"/><path d="M3 13.5h18"/>'
        '<path d="M9.5 13a9 9 0 012-6.2M14.5 13a9 9 0 00-2-6.2"/>'
        '<path d="M4 17h16" stroke-linecap="round"/></svg>'
    ),
    "ing": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
        '<path d="M3 13.5h5l1.5 2.5h5l1.5-2.5h5"/>'
        '<path d="M5 6.5h14l2 7v4a1.5 1.5 0 01-1.5 1.5h-15A1.5 1.5 0 013 17.5v-4z"/>'
        '<path d="M12 3v5.5M9.5 6.5L12 9l2.5-2.5" stroke-linecap="round"/></svg>'
    ),
}

STYLE = """
:root{--bg:#f4f5f7;--panel:#fff;--ink:#15181d;--muted:#5d6672;--line:#dfe3e8;
      --ok:#1f8a4c;--ok-bg:#e7f5ec;--bad:#c0392b;--bad-bg:#fbeceb;--accent:#1f6fd0;
      --extra:#6b3fb0;--extra-bg:#f4eefc;--extra-line:#dcc9f4;
      --cam:#6b3fb0;--cam-bg:#f1e8fb;--saf:#b3261e;--saf-bg:#fbeae8;
      --ing:#0d6f7d;--ing-bg:#e1f2f5}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#14171c;--panel:#1c2026;--ink:#eceff3;--muted:#9aa4b2;--line:#2c323b;
  --ok:#4ade80;--ok-bg:#16301f;--bad:#f87171;--bad-bg:#3a1c1a;--accent:#7ba4ff;
  --extra:#c0a6f0;--extra-bg:#251d33;--extra-line:#3c2f52;
  --cam:#c0a6f0;--cam-bg:#251d33;--saf:#f19790;--saf-bg:#331d1b;
  --ing:#6fc9d6;--ing-bg:#122b30}}
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
nav a{padding:9px 14px;font-size:14px;color:var(--muted);text-decoration:none;
      border-bottom:2px solid transparent;white-space:nowrap}
nav a:hover{color:var(--ink)}
nav a.here{color:var(--ink);font-weight:600;border-bottom-color:var(--accent)}
details.menu{position:relative;margin-left:auto}
details.menu>summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:9px;
     padding:7px 13px;margin-bottom:5px;font-size:14px;font-weight:600;white-space:nowrap;
     color:var(--extra);background:var(--extra-bg);border:1px solid var(--extra-line);
     border-radius:9px;transition:background .15s,border-color .15s}
details.menu>summary::-webkit-details-marker{display:none}
details.menu>summary::marker{content:""}
details.menu>summary:hover{border-color:var(--extra)}
details.menu.here>summary{color:#fff;background:var(--extra);border-color:var(--extra)}
details.menu.here>summary .mdot{background:#fff}
.mdot{width:8px;height:8px;border-radius:50%;background:var(--extra);flex:none}
.chev{width:6px;height:6px;border:solid currentColor;border-width:0 1.6px 1.6px 0;
      transform:rotate(45deg) translate(-1px,-1px);transition:transform .15s}
details[open] .chev{transform:rotate(-135deg) translate(-2px,-2px)}
.menucard{position:absolute;right:0;top:calc(100% + 4px);z-index:30;width:340px;
     max-width:calc(100vw - 32px);background:var(--panel);border:1px solid var(--line);
     border-radius:13px;box-shadow:0 14px 34px rgba(12,18,30,.18);padding:8px;
     animation:drop .14s ease-out}
@keyframes drop{from{opacity:0;transform:translateY(-5px)}}
.menuhead{padding:9px 10px 11px;font-size:13px;font-weight:700;line-height:1.35}
.menuhead span{display:block;font-weight:400;color:var(--muted);font-size:12px;margin-top:3px}
a.mi{display:grid;grid-template-columns:36px 1fr;gap:0 11px;padding:9px 10px;border-radius:10px;
     text-decoration:none;color:var(--ink);border-bottom:none}
a.mi i{grid-row:1/3;align-self:center;width:36px;height:36px;border-radius:10px;
       display:grid;place-items:center}
a.mi i svg{width:20px;height:20px}
a.mi b{font-size:14px;line-height:1.3}
a.mi span{font-size:12px;color:var(--muted);line-height:1.35}
a.mi:hover{background:var(--bg)}
a.mi.here{background:var(--bg);box-shadow:inset 0 0 0 1px var(--line)}
a.mi.cam i{color:var(--cam);background:var(--cam-bg)}
a.mi.saf i{color:var(--saf);background:var(--saf-bg)}
a.mi.ing i{color:var(--ing);background:var(--ing-bg)}
.extrapanel{border-color:var(--extra-line)}
.extrapanel h2{display:flex;align-items:center;gap:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin-top:12px}
.tiles a.mi{background:var(--bg);border:1px solid var(--line);padding:12px}
.tiles a.mi:hover{border-color:var(--extra)}
.svc{display:inline-block;vertical-align:middle;margin-left:10px;padding:3px 10px;border-radius:999px;
     font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
     background:var(--bg);color:var(--muted);border:1px solid var(--line)}
.svc.extra{color:var(--extra);border-color:var(--extra-line);background:var(--extra-bg)}
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
"""

HEADER_TEMPLATE = """<header>
  <div class="brand">Контроль строительных площадок · ЛЦТ-2026, задача №7</div>
  <nav>{main_tabs}
    <details class="menu{active}">
      <summary title="Второй сервис: видеонаблюдение площадки">
        <span class="mdot"></span>{extra_label}<span class="chev"></span></summary>
      <div class="menucard">
        <div class="menuhead">{menu_title}<span>{menu_note}</span></div>
        {extra_items}
      </div>
    </details>
  </nav>
</header>
<script>
// Меню закрывается щелчком мимо и клавишей Esc: без этого оно висит открытым,
// пока не попадёшь ровно по кнопке.
document.addEventListener('click', function(event){{
  document.querySelectorAll('details.menu[open]').forEach(function(menu){{
    if(!menu.contains(event.target)){{ menu.removeAttribute('open'); }}
  }});
}});
document.addEventListener('keydown', function(event){{
  if(event.key === 'Escape'){{
    document.querySelectorAll('details.menu[open]').forEach(function(menu){{
      menu.removeAttribute('open');
    }});
  }}
}});
</script>"""

MENU_ITEM_TEMPLATE = """<a class="mi {kind}{here}" href="{href}">
  <i>{icon}</i><b>{title}</b><span>{note}</span></a>"""


def render_service_tiles() -> str:
    """Плитки дополнительного сервиса для первой страницы."""
    tiles = "".join(
        MENU_ITEM_TEMPLATE.format(
            kind=kind, here="", href=href, icon=ICONS[kind], title=escape(title), note=escape(note)
        )
        for href, title, kind, note in EXTRA_TABS
    )
    return tiles


def render_header(current: str) -> str:
    """Собирает шапку: вкладки основного сервиса и кнопку дополнительного."""
    header = _build_header(_render_links(MAIN_TABS, current), current)
    return header


def render_stand_nav() -> str:
    """Та же шапка для собираемой страницы стенда.

    Страницы, которые на стенде являются его вкладками, остаются кнопками — иначе
    переход между ними перезагружал бы страницу ради того, что уже загружено.
    """
    header = _build_header(_render_stand_links(MAIN_TABS), "")
    return header


def _build_header(main_tabs: str, current: str) -> str:
    """Собирает шапку вокруг готового ряда вкладок."""
    inside = any(href == current for href, _, _, _ in EXTRA_TABS)
    header = HEADER_TEMPLATE.format(
        main_tabs=main_tabs,
        extra_label=EXTRA_SERVICE_LABEL,
        menu_title=EXTRA_MENU_TITLE,
        menu_note=EXTRA_MENU_NOTE,
        extra_items=_render_menu(current),
        active=" here" if inside else "",
    )
    return header


def _render_menu(current: str) -> str:
    """Пункты выпадающего меню дополнительного сервиса."""
    items = "".join(
        MENU_ITEM_TEMPLATE.format(
            kind=kind,
            here=" here" if href == current else "",
            href=href,
            icon=ICONS[kind],
            title=escape(title),
            note=escape(note),
        )
        for href, title, kind, note in EXTRA_TABS
    )
    return items


def _render_links(tabs: tuple[tuple[str, str, str], ...], current: str) -> str:
    """Вкладки основного сервиса обычными ссылками."""
    links = "".join(
        f'<a href="{href}" class="{"here" if href == current else ""}">{escape(title)}</a>'
        for href, title, _ in tabs
    )
    return links


def _render_stand_links(tabs: tuple[tuple[str, str, str], ...]) -> str:
    """Вкладки для стенда: свои разделы кнопками, чужие страницы ссылками."""
    parts = []
    for href, title, view in tabs:
        if view:
            parts.append(f'<button class="tab" role="tab" data-view="{view}">{escape(title)}</button>')
        else:
            parts.append(f'<a class="tablink" href="{href}">{escape(title)}</a>')
    return "".join(parts)

