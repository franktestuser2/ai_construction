"""Тесты разбора фасада: снятие дублей, ряды и сборка измерения."""

from pathlib import Path

from site_monitoring.entity import FacadeCell, FacadeCellKind, FacadeReadiness
from site_monitoring.services.facade_cell_layout import (
    cells_above_lowest_row,
    deduplicate_cells,
    split_into_rows,
)
from site_monitoring.services.facade_readiness import FacadeReadinessService

IMAGE_PATH = Path("data/photos_v2/W07/W07_2027-06-18_frame20.jpg")
FRAME_ID = "кадр-1"
BUILDING_SCORE = 0.91


def _cell(kind: FacadeCellKind, left: float, top: float, score: float = 0.9) -> FacadeCell:
    """Собирает ячейку размером 10 на 10 в заданной точке."""
    cell = FacadeCell(kind=kind, box=(left, top, left + 10.0, top + 10.0), score=score)
    return cell


class _StubBuildingDetector:
    """Заглушка детектора зданий."""

    def __init__(self, building: object | None) -> None:
        self._building = building

    def detect(self, image_path: Path) -> object | None:
        return self._building


class _StubCellDetector:
    """Заглушка детектора ячеек."""

    def __init__(self, cells: tuple[FacadeCell, ...]) -> None:
        self._cells = cells

    def detect(self, image_path: Path, crop: object = None) -> tuple[FacadeCell, ...]:
        return self._cells


class _StubBarrierClassifier:
    """Заглушка классификатора ограждений: первый проём считает нарушением."""

    def classify(self, image_path: Path, boxes: tuple) -> tuple[bool, ...]:
        verdicts = tuple(index == 0 for index in range(len(boxes)))
        return verdicts


class _Building:
    """Минимальная замена рамки здания."""

    box = (0.0, 0.0, 100.0, 100.0)
    score = BUILDING_SCORE


def test_дубли_на_одном_проёме_схлопываются_в_самую_уверенную_ячейку() -> None:
    # Arrange
    cells = (
        _cell(FacadeCellKind.MONOLITH, 0.0, 0.0, score=0.4),
        _cell(FacadeCellKind.BLOCK, 1.0, 1.0, score=0.8),
        _cell(FacadeCellKind.WINDOW, 50.0, 0.0, score=0.6),
    )

    # Act
    unique = deduplicate_cells(cells)

    # Assert
    assert len(unique) == 2
    assert unique[0].kind is FacadeCellKind.BLOCK


def test_ячейки_на_разной_высоте_попадают_в_разные_ряды() -> None:
    # Arrange
    cells = (
        _cell(FacadeCellKind.WINDOW, 0.0, 0.0),
        _cell(FacadeCellKind.WINDOW, 20.0, 1.0),
        _cell(FacadeCellKind.MONOLITH, 0.0, 40.0),
    )

    # Act
    rows = split_into_rows(cells)

    # Assert
    assert len(rows) == 2
    assert len(rows[0]) == 2


def test_нижний_ряд_не_идёт_на_проверку_ограждений() -> None:
    # Arrange
    cells = (
        _cell(FacadeCellKind.MONOLITH, 0.0, 0.0),
        _cell(FacadeCellKind.MONOLITH, 0.0, 40.0),
    )

    # Act
    upper = cells_above_lowest_row(cells)

    # Assert
    assert len(upper) == 1
    assert upper[0].box[1] == 0.0


def test_единственный_ряд_ячеек_к_проверке_ограждений_не_допускается() -> None:
    # Arrange
    cells = (_cell(FacadeCellKind.MONOLITH, 0.0, 0.0), _cell(FacadeCellKind.MONOLITH, 20.0, 1.0))

    # Act
    upper = cells_above_lowest_row(cells)

    # Assert
    assert upper == ()


def test_без_здания_в_кадре_измерение_не_строится() -> None:
    # Arrange
    service = FacadeReadinessService(
        building_detector=_StubBuildingDetector(None),
        cell_detector=_StubCellDetector(()),
        barrier_classifier=_StubBarrierClassifier(),
    )

    # Act
    readiness = service.assess_frame(FRAME_ID, IMAGE_PATH)

    # Assert
    assert readiness is None


def test_измерение_считает_доли_стадий_и_нарушения() -> None:
    # Arrange
    cells = (
        _cell(FacadeCellKind.MONOLITH, 0.0, 0.0),
        _cell(FacadeCellKind.MONOLITH, 20.0, 1.0),
        _cell(FacadeCellKind.BLOCK, 0.0, 40.0),
        _cell(FacadeCellKind.WINDOW, 20.0, 41.0),
    )
    service = FacadeReadinessService(
        building_detector=_StubBuildingDetector(_Building()),
        cell_detector=_StubCellDetector(cells),
        barrier_classifier=_StubBarrierClassifier(),
    )

    # Act
    readiness = service.assess_frame(FRAME_ID, IMAGE_PATH)

    # Assert
    assert isinstance(readiness, FacadeReadiness)
    assert readiness.cells_total == 4
    assert readiness.monolith == 2
    assert readiness.closed_share == 0.5
    assert readiness.glazed_share == 0.25
    # Проверены только монолитные ячейки верхнего ряда, нарушение из них одно.
    assert readiness.barrier_checked == 2
    assert readiness.barrier_violations == 1
