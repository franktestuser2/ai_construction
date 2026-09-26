"""Приведение находок детектора ячеек в пригодный для счёта вид.

Детектор обводит один и тот же проём несколько раз и нередко разными классами,
поэтому перед подсчётом дубли снимаются. Затем ячейки раскладываются по рядам:
нижний ряд исключается из проверки ограждений — на уровне земли падать некуда,
а ограждения там ставят иначе.
"""

import logging

from ..entity import FacadeCell

logger = logging.getLogger(__name__)

DUPLICATE_IOU_THRESHOLD = 0.1
# Новый ряд начинается, когда разрыв по вертикали превышает долю от высоты ячейки.
ROW_GAP_RATIO = 0.6
EMPTY_AREA = 0.0
NO_CELLS = 0


def _area(box: tuple[float, float, float, float]) -> float:
    """Площадь рамки."""
    value = abs(box[2] - box[0]) * abs(box[3] - box[1])
    return value


def _intersection_over_union(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """Доля пересечения двух рамок в их общей площади."""
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return EMPTY_AREA
    overlap = (right - left) * (bottom - top)
    union = _area(first) + _area(second) - overlap
    if union <= EMPTY_AREA:
        return EMPTY_AREA
    ratio = overlap / union
    return ratio


def deduplicate_cells(cells: tuple[FacadeCell, ...]) -> tuple[FacadeCell, ...]:
    """Оставляет на каждом проёме одну ячейку — самую уверенную.

    Классы детектора конкурируют за один и тот же проём: одна и та же дыра в стене
    приходит и монолитом, и блоком. Побеждает находка с наибольшей уверенностью.
    """
    ordered = sorted(cells, key=lambda cell: cell.score, reverse=True)
    kept: list[FacadeCell] = []
    for cell in ordered:
        overlaps = any(
            _intersection_over_union(cell.box, chosen.box) > DUPLICATE_IOU_THRESHOLD
            for chosen in kept
        )
        if not overlaps:
            kept.append(cell)
    logger.info("Дубли сняты: было %d ячеек, осталось %d", len(cells), len(kept))
    return tuple(kept)


def split_into_rows(cells: tuple[FacadeCell, ...]) -> tuple[tuple[FacadeCell, ...], ...]:
    """Раскладывает ячейки по рядам сверху вниз.

    Перспективу мы не выравниваем, поэтому ряд — это не строго этаж, а полоса ячеек
    на близкой высоте. Ряды нужны лишь для того, чтобы исключить нижний из проверки
    ограждений, поэтому такой точности достаточно.
    """
    if not cells:
        return ()
    ordered = sorted(cells, key=lambda cell: (cell.box[1] + cell.box[3]) / 2)
    rows: list[list[FacadeCell]] = [[ordered[0]]]
    for cell in ordered[1:]:
        center = (cell.box[1] + cell.box[3]) / 2
        previous = rows[-1][-1]
        previous_center = (previous.box[1] + previous.box[3]) / 2
        # Порог считается от высоты соседней ячейки, а не от общей медианы: из-за
        # перспективы дальние ячейки в разы мельче ближних, и общая мера их склеивает.
        limit = (previous.box[3] - previous.box[1]) * ROW_GAP_RATIO
        if center - previous_center > limit:
            rows.append([])
        rows[-1].append(cell)
    result = tuple(tuple(row) for row in rows)
    return result


def cells_above_lowest_row(cells: tuple[FacadeCell, ...]) -> tuple[FacadeCell, ...]:
    """Возвращает ячейки всех рядов, кроме самого нижнего."""
    rows = split_into_rows(cells)
    if len(rows) <= 1:
        return ()
    upper = tuple(cell for row in rows[:-1] for cell in row)
    return upper
