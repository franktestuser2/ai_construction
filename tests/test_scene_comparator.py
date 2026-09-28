"""Тесты сверки снимков смены между собой: тот же ракурс или другой."""

import random
from pathlib import Path

from PIL import Image

from site_monitoring.adapters.scene_comparator import SceneComparator

MISMATCH_THRESHOLD = 0.425
IMAGE_SIDE = 128
CORNER_SIDE = 20
BRIGHT = 255


def _scene_image(path: Path, seed: int, changed_corner: bool = False) -> Path:
    """Рисует картинку сцены.

    Сцена задаётся зерном: одно зерно — один ракурс. Светлый угол изображает то,
    что на площадке меняется от кадра к кадру, сама сцена при этом остаётся прежней.
    """
    generator = random.Random(seed)
    image = Image.new("L", (IMAGE_SIDE, IMAGE_SIDE))
    pixels = image.load()
    for row in range(IMAGE_SIDE):
        for column in range(IMAGE_SIDE):
            pixels[column, row] = generator.randrange(BRIGHT + 1)
    if changed_corner:
        for row in range(CORNER_SIDE):
            for column in range(CORNER_SIDE):
                pixels[column, row] = BRIGHT
    image.save(path)
    return path


def test_кадр_с_другой_сценой_помечается(tmp_path) -> None:
    # Arrange: пять кадров одной сцены и один, снятый с другого ракурса
    paths = [_scene_image(tmp_path / f"кадр-{index}.png", seed=1, changed_corner=index % 2 == 0)
             for index in range(5)]
    paths.append(_scene_image(tmp_path / "чужой.png", seed=2))
    comparator = SceneComparator(MISMATCH_THRESHOLD)

    # Act
    mismatches = comparator.find_mismatches(tuple(paths))

    # Assert
    assert mismatches[-1] is True
    assert any(mismatches[:-1]) is False


def test_кадры_одной_сцены_не_помечаются(tmp_path) -> None:
    # Arrange: одна сцена, меняется только угол кадра
    paths = tuple(
        _scene_image(tmp_path / f"кадр-{index}.png", seed=1, changed_corner=index % 2 == 0)
        for index in range(6)
    )
    comparator = SceneComparator(MISMATCH_THRESHOLD)

    # Act
    mismatches = comparator.find_mismatches(paths)

    # Assert
    assert any(mismatches) is False


def test_одиночный_кадр_сравнивать_не_с_чем(tmp_path) -> None:
    # Arrange
    paths = (_scene_image(tmp_path / "единственный.png", seed=1),)
    comparator = SceneComparator(MISMATCH_THRESHOLD)

    # Act
    mismatches = comparator.find_mismatches(paths)

    # Assert
    assert mismatches == (False,)
