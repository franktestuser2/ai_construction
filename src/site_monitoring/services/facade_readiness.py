"""Разбор фасада по снимку: степень готовности и нарушения по ограждениям.

Порядок шагов повторяет пайплайн авторов моделей, кроме перспективной
трансформации: она берёт четыре точки из калибровки камеры, которой у нас нет.
На подсчёт долей ячеек по классам это не влияет, помешало бы измерению геометрии.
"""

import logging
from collections import Counter
from pathlib import Path

from ..adapters.barrier_classifier import BarrierClassifier
from ..adapters.facade_detector import BuildingDetector, FacadeCellDetector
from ..entity import BuildingBox, FacadeCell, FacadeCellKind, FacadeReadiness
from .facade_cell_layout import cells_above_lowest_row, deduplicate_cells, split_into_rows

logger = logging.getLogger(__name__)

NO_CELLS = 0
# Разметка камеры задана человеком, сомневаться в ней незачем.
MARKUP_SCORE = 1.0


class FacadeReadinessService:
    """Считает готовность фасада и нарушения по ограждениям на одном снимке."""

    def __init__(
        self,
        building_detector: BuildingDetector,
        cell_detector: FacadeCellDetector,
        barrier_classifier: BarrierClassifier,
    ) -> None:
        self._building_detector = building_detector
        self._cell_detector = cell_detector
        self._barrier_classifier = barrier_classifier

    def assess_frame(
        self,
        frame_id: str,
        image_path: Path,
        marked_box: tuple[float, float, float, float] | None = None,
    ) -> FacadeReadiness | None:
        """Разбирает снимок и возвращает измерение готовности фасада.

        Если для камеры задана разметка, область здания берётся из неё, а детектор
        зданий не запускается: на сцене с одной точки съёмки разметка надёжнее.
        Возвращает ничего, если здания в кадре нет или на нём не нашлось ячеек —
        это не отклонение, а признак того, что фронт работ не попал в кадр.
        """
        building = self._locate_building(image_path, marked_box)
        if building is None:
            return None
        cells = self._cell_detector.detect(image_path, building.box)
        unique = deduplicate_cells(cells)
        if len(unique) == NO_CELLS:
            logger.info("На снимке %s здание найдено, но ячеек фасада нет", image_path.name)
            return None
        readiness = self._build_readiness(frame_id, image_path, building, unique)
        return readiness

    def _locate_building(
        self,
        image_path: Path,
        marked_box: tuple[float, float, float, float] | None,
    ) -> BuildingBox | None:
        """Берёт область здания из разметки камеры либо ищет её детектором."""
        if marked_box is not None:
            marked = BuildingBox(box=marked_box, score=MARKUP_SCORE)
            return marked
        found = self._building_detector.detect(image_path)
        return found

    def _build_readiness(
        self,
        frame_id: str,
        image_path: Path,
        building: BuildingBox,
        cells: tuple[FacadeCell, ...],
    ) -> FacadeReadiness:
        """Собирает измерение из разобранных ячеек."""
        counts = Counter(cell.kind for cell in cells)
        checked, violations = self._check_barriers(image_path, cells)
        readiness = FacadeReadiness(
            frame_id=frame_id,
            building_score=building.score,
            building_box=building.box,
            cells=cells,
            cells_total=len(cells),
            monolith=counts[FacadeCellKind.MONOLITH],
            block=counts[FacadeCellKind.BLOCK],
            window=counts[FacadeCellKind.WINDOW],
            rows=len(split_into_rows(cells)),
            barrier_checked=checked,
            barrier_violations=violations,
        )
        logger.info(
            "Фасад на %s: ячеек %d, заполнено %.0f%%, остеклено %.0f%%, нарушений ОТиПБ %d",
            image_path.name,
            readiness.cells_total,
            readiness.closed_share * 100,
            readiness.glazed_share * 100,
            readiness.barrier_violations,
        )
        return readiness

    def _check_barriers(
        self,
        image_path: Path,
        cells: tuple[FacadeCell, ...],
    ) -> tuple[int, int]:
        """Проверяет ограждения в пустых проёмах выше нижнего ряда."""
        upper = cells_above_lowest_row(cells)
        empty = tuple(cell for cell in upper if cell.kind is FacadeCellKind.MONOLITH)
        if not empty:
            return NO_CELLS, NO_CELLS
        boxes = tuple(cell.box for cell in empty)
        verdicts = self._barrier_classifier.classify(image_path, boxes)
        counted = (len(verdicts), sum(verdicts))
        return counted
