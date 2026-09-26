"""Рисует схему процесса: путь от снимка с камеры до вердикта об отставании.

Схема собирается в PNG для показа коллегам и заказчику. Содержание повторяет
`docs/work_activity_methodology.md`: три уровня доказательства и два гейта.
"""

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("docs/process_overview.png")
FIGURE_SIZE = (12.0, 14.0)
FIGURE_DPI = 170
BOX_HEIGHT = 7.0
CORNER_RADIUS = 0.6
EDGE_WIDTH = 1.1
TITLE_SIZE = 13
SUBTITLE_SIZE = 11
HEADER_SIZE = 19
LEGEND_SIZE = 11
ARROW_WIDTH = 1.1
ARROW_COLOR = "#5F5E5A"

PALETTE = {
    "gray": ("#F1EFE8", "#5F5E5A", "#2C2C2A", "#5F5E5A"),
    "teal": ("#E1F5EE", "#0F6E56", "#04342C", "#0F6E56"),
    "purple": ("#EEEDFE", "#534AB7", "#26215C", "#534AB7"),
    "coral": ("#FAECE7", "#993C1D", "#4A1B0C", "#993C1D"),
    "red": ("#FCEBEB", "#A32D2D", "#501313", "#A32D2D"),
}

COLUMNS = ((4.0, 29.0), (35.5, 29.0), (67.0, 29.0))
HALVES = ((4.0, 45.0), (51.0, 45.0))
CENTER = (22.5, 55.0)

ROWS = {
    "вход": 88.0,
    "распознавание": 77.0,
    "гейт": 66.0,
    "пара": 55.0,
    "признаки": 44.0,
    "интервал": 33.0,
    "часы": 22.0,
    "вердикт": 11.0,
}

LEGEND = (
    ("gray", "снимок и план"),
    ("teal", "уровень 1: комплект техники"),
    ("purple", "уровень 2: работа шла"),
    ("coral", "уровень 3: часы и процент"),
)


def draw_box(axes, left: float, width: float, bottom: float, title: str, subtitle: str, tone: str) -> None:
    """Рисует один прямоугольник схемы с заголовком и пояснением."""
    fill, edge, title_color, subtitle_color = PALETTE[tone]
    shape = FancyBboxPatch(
        (left, bottom),
        width,
        BOX_HEIGHT,
        boxstyle=f"round,pad=0,rounding_size={CORNER_RADIUS}",
        facecolor=fill,
        edgecolor=edge,
        linewidth=EDGE_WIDTH,
    )
    axes.add_patch(shape)
    center = left + width / 2
    axes.text(center, bottom + BOX_HEIGHT * 0.62, title, ha="center", va="center", fontsize=TITLE_SIZE, color=title_color)
    axes.text(
        center,
        bottom + BOX_HEIGHT * 0.26,
        subtitle,
        ha="center",
        va="center",
        fontsize=SUBTITLE_SIZE,
        color=subtitle_color,
    )


def draw_arrow(axes, start: tuple[float, float], end: tuple[float, float]) -> None:
    """Рисует стрелку между двумя точками схемы."""
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=13,
        linewidth=ARROW_WIDTH,
        color=ARROW_COLOR,
        shrinkA=0,
        shrinkB=0,
    )
    axes.add_patch(arrow)


def draw_elbow(axes, start: tuple[float, float], end: tuple[float, float], middle: float) -> None:
    """Рисует стрелку с изломом: вниз, вбок и снова вниз."""
    axes.plot([start[0], start[0]], [start[1], middle], color=ARROW_COLOR, linewidth=ARROW_WIDTH)
    axes.plot([start[0], end[0]], [middle, middle], color=ARROW_COLOR, linewidth=ARROW_WIDTH)
    draw_arrow(axes, (end[0], middle), end)


def draw_input_row(axes) -> None:
    """Верхний ряд: снимок, его метаданные и пункт календарного плана."""
    bottom = ROWS["вход"]
    draw_box(axes, *COLUMNS[0], bottom, "Снимки с камер", "каждые 20 минут", "gray")
    draw_box(axes, *COLUMNS[1], bottom, "Метаданные снимка", "дата и время съёмки", "gray")
    draw_box(axes, *COLUMNS[2], bottom, "Пункт плана", "вид работ и комплект техники", "gray")
    draw_arrow(axes, (33.5, bottom + 3.5), (35.0, bottom + 3.5))
    draw_arrow(axes, (65.0, bottom + 3.5), (66.5, bottom + 3.5))


def draw_recognition_row(axes) -> None:
    """Ряд распознавания: детектор, арбитраж и проверка позиций комплекта."""
    bottom = ROWS["распознавание"]
    draw_box(axes, *COLUMNS[0], bottom, "Детектор техники", "рамки на снимке", "teal")
    draw_box(axes, *COLUMNS[1], bottom, "Арбитраж нейросетью", "проверка каждой рамки", "teal")
    draw_box(axes, *COLUMNS[2], bottom, "Позиции комплекта", "каждая не ниже минимума", "teal")
    draw_arrow(axes, (18.5, ROWS["вход"]), (18.5, bottom + BOX_HEIGHT))
    draw_arrow(axes, (81.5, ROWS["вход"]), (81.5, bottom + BOX_HEIGHT))
    draw_arrow(axes, (33.5, bottom + 3.5), (35.0, bottom + 3.5))
    draw_arrow(axes, (65.0, bottom + 3.5), (66.5, bottom + 3.5))


def draw_gate_row(axes) -> None:
    """Гейт комплекта: полон или нет, окно проверки — час."""
    bottom = ROWS["гейт"]
    draw_box(axes, *HALVES[0], bottom, "Комплект собран", "все позиции, окно — час", "teal")
    draw_box(axes, *HALVES[1], bottom, "Комплект неполон", "час обнулён, пометка в отчёт", "red")
    draw_elbow(axes, (81.5, ROWS["распознавание"]), (26.5, bottom + BOX_HEIGHT), ROWS["распознавание"] - 2.0)
    draw_elbow(axes, (81.5, ROWS["распознавание"]), (73.5, bottom + BOX_HEIGHT), ROWS["распознавание"] - 2.0)


def draw_activity_rows(axes) -> None:
    """Уровень 2: пара соседних кадров и три признака работы."""
    pair_bottom = ROWS["пара"]
    draw_box(axes, *CENTER, pair_bottom, "Пара соседних кадров", "интервал 20 минут, одна камера", "purple")
    draw_elbow(axes, (26.5, ROWS["гейт"]), (50.0, pair_bottom + BOX_HEIGHT), ROWS["гейт"] - 2.0)
    signs_bottom = ROWS["признаки"]
    draw_box(axes, *COLUMNS[0], signs_bottom, "Человек в кабине", "оператор на месте", "purple")
    draw_box(axes, *COLUMNS[1], signs_bottom, "Машина сместилась", "сдвиг больше порога", "purple")
    draw_box(axes, *COLUMNS[2], signs_bottom, "Изменился силуэт", "стрела, ковш, размер", "purple")
    level = pair_bottom - 2.0
    for target in (18.5, 50.0, 81.5):
        draw_elbow(axes, (50.0, pair_bottom), (target, signs_bottom + BOX_HEIGHT), level)
    interval_bottom = ROWS["интервал"]
    draw_box(axes, *CENTER, interval_bottom, "Интервал засчитан как рабочий", "сработал хотя бы один признак", "purple")
    level = signs_bottom - 2.0
    for source in (18.5, 50.0, 81.5):
        draw_elbow(axes, (source, signs_bottom), (50.0, interval_bottom + BOX_HEIGHT), level)


def draw_hours_row(axes) -> None:
    """Уровень 3: пропуски, часы за смену и процент от плана."""
    bottom = ROWS["часы"]
    draw_box(axes, *COLUMNS[0], bottom, "Пропуски закрыты", "да — нет — да считаем работой", "coral")
    draw_box(axes, *COLUMNS[1], bottom, "Часы за смену", "интервалы по 20 минут", "coral")
    draw_box(axes, *COLUMNS[2], bottom, "Процент от плана", "факт к плановой смене", "coral")
    draw_elbow(axes, (50.0, ROWS["интервал"]), (18.5, bottom + BOX_HEIGHT), ROWS["интервал"] - 2.0)
    draw_arrow(axes, (33.5, bottom + 3.5), (35.0, bottom + 3.5))
    draw_arrow(axes, (65.0, bottom + 3.5), (66.5, bottom + 3.5))


def draw_verdict_row(axes) -> None:
    """Итоговый вердикт по этапу работ."""
    bottom = ROWS["вердикт"]
    draw_box(axes, *HALVES[0], bottom, "Соответствие графику", "факт не ниже 90 % плана", "coral")
    draw_box(axes, *HALVES[1], bottom, "Отставание", "факт ниже 90 % плана", "red")
    draw_elbow(axes, (81.5, ROWS["часы"]), (26.5, bottom + BOX_HEIGHT), ROWS["часы"] - 2.0)
    draw_elbow(axes, (81.5, ROWS["часы"]), (73.5, bottom + BOX_HEIGHT), ROWS["часы"] - 2.0)


def draw_legend(axes) -> None:
    """Подпись цветов: три уровня доказательства."""
    for number, (tone, caption) in enumerate(LEGEND):
        fill, edge, _, _ = PALETTE[tone]
        left = 4.0 + (number % 2) * 48.0
        bottom = 5.6 - (number // 2) * 3.4
        patch = FancyBboxPatch(
            (left, bottom),
            2.0,
            1.6,
            boxstyle="round,pad=0,rounding_size=0.3",
            facecolor=fill,
            edgecolor=edge,
            linewidth=EDGE_WIDTH,
        )
        axes.add_patch(patch)
        axes.text(left + 2.8, bottom + 0.8, caption, ha="left", va="center", fontsize=LEGEND_SIZE, color="#2C2C2A")


def main() -> None:
    """Собирает схему процесса и сохраняет её в PNG."""
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    axes.set_xlim(0, 100)
    axes.set_ylim(0, 100)
    axes.axis("off")
    axes.text(
        50,
        97,
        "Как сервис отвечает на вопрос об отставании от графика",
        ha="center",
        va="center",
        fontsize=HEADER_SIZE,
        color="#2C2C2A",
    )
    draw_input_row(axes)
    draw_recognition_row(axes)
    draw_gate_row(axes)
    draw_activity_rows(axes)
    draw_hours_row(axes)
    draw_verdict_row(axes)
    draw_legend(axes)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT_PATH, dpi=FIGURE_DPI, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    logger.info("Схема сохранена: %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
