"""Тесты детектора ячеек фасада: сборка сети и разбор её вывода."""

from pathlib import Path

import torch

from site_monitoring.adapters.facade_detector import (
    FacadeCellDetector,
    build_faster_rcnn,
)
from site_monitoring.entity import FacadeCellKind

CELL_CLASSES = 3
THRESHOLD = 0.35
WEIGHTS_STUB = Path("models/facade/weights/torchvision/facade_cells.pt")


def test_сеть_собрана_в_caffe_варианте_с_шагом_на_свёртке_один_на_один() -> None:
    # Arrange
    model = build_faster_rcnn(CELL_CLASSES)

    # Act
    block = model.backbone.body.layer2[0]

    # Assert
    assert block.conv1.stride == (2, 2)
    assert block.conv2.stride == (1, 1)


def test_голова_классификации_рассчитана_на_фон_и_три_класса() -> None:
    # Arrange
    model = build_faster_rcnn(CELL_CLASSES)

    # Act
    outputs = model.roi_heads.box_predictor.cls_score.out_features

    # Assert
    assert outputs == CELL_CLASSES + 1


def test_слабые_находки_отсеиваются_по_порогу() -> None:
    # Arrange
    detector = FacadeCellDetector(WEIGHTS_STUB, THRESHOLD)
    output = {
        "boxes": torch.tensor([[0.0, 0.0, 10.0, 10.0], [5.0, 5.0, 20.0, 20.0]]),
        "scores": torch.tensor([0.9, 0.1]),
        "labels": torch.tensor([1, 2]),
    }

    # Act
    cells = detector._collect_cells(output, None, (100, 100))

    # Assert
    assert len(cells) == 1
    assert cells[0].kind is FacadeCellKind.WINDOW


def test_метки_сети_раскладываются_по_стадиям_готовности() -> None:
    # Arrange
    detector = FacadeCellDetector(WEIGHTS_STUB, 0.0)
    output = {
        "boxes": torch.zeros((3, 4)),
        "scores": torch.tensor([0.5, 0.5, 0.5]),
        "labels": torch.tensor([1, 2, 3]),
    }

    # Act
    kinds = tuple(cell.kind for cell in detector._collect_cells(output, None, (100, 100)))

    # Assert
    assert kinds == (FacadeCellKind.WINDOW, FacadeCellKind.MONOLITH, FacadeCellKind.BLOCK)


def test_рамки_переводятся_в_доли_исходного_кадра() -> None:
    # Arrange: вырез занимает правую нижнюю четверть кадра
    detector = FacadeCellDetector(WEIGHTS_STUB, 0.0)
    crop = (0.5, 0.5, 1.0, 1.0)
    output = {
        "boxes": torch.tensor([[0.0, 0.0, 50.0, 50.0]]),
        "scores": torch.tensor([0.9]),
        "labels": torch.tensor([1]),
    }

    # Act: сеть видела вырез размером 100 на 100 и нашла рамку в его левой верхней четверти
    cells = detector._collect_cells(output, crop, (100, 100))

    # Assert
    assert cells[0].box == (0.5, 0.5, 0.75, 0.75)
