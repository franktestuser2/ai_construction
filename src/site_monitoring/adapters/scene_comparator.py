"""Сверка снимков смены между собой: тот же это ракурс или другой.

Камера на объекте стоит неподвижно, и всю смену она показывает одну и ту же сцену:
меняется на ней только то, что делают люди и техника. Если очередной снимок на эту
сцену не похож, объяснение одно — кадр пришёл с другого ракурса или вовсе с другой
площадки. Судить по нему о ходе работ нельзя, и сравнивать его с соседними кадрами
тоже: разницу между двумя разными местами легко принять за работу техники.

Проверка нарочно сделана без моделей. Ответ модели про обзор от прогона к прогону
гуляет, а здесь при одних и тех же снимках результат один и тот же всегда.

Похожесть считается по разностному хешу: снимок сжимается до маленькой сетки яркостей,
и каждый бит говорит, светлее ли пиксель своего правого соседа. Такой хеш переживает
смену освещения и сжатие, но меняется, когда сцена становится другой. Эталоном смены
служит медиана хешей всех её кадров: она устойчива к паре выбивающихся снимков и не
требует считать какой-то один кадр заведомо правильным.
"""

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

HASH_SIDE = 16
GRAYSCALE_MODE = "L"
BIT_COUNT = HASH_SIDE * HASH_SIDE
MAJORITY_FACTOR = 2
NOTHING = 0


class SceneComparator:
    """Отмечает снимки смены, снятые не с той сцены, что остальные."""

    def __init__(self, mismatch_threshold: float) -> None:
        self._mismatch_threshold = mismatch_threshold

    def find_mismatches(self, image_paths: tuple[Path, ...]) -> tuple[bool, ...]:
        """Говорит по каждому снимку смены, отличается ли его сцена от общей."""
        if len(image_paths) <= 1:
            return tuple(False for _ in image_paths)
        hashes = [self._image_hash(path) for path in image_paths]
        reference = _median_hash(hashes)
        mismatches = []
        for path, current in zip(image_paths, hashes):
            share = _difference_share(reference, current)
            mismatch = share >= self._mismatch_threshold
            if mismatch:
                logger.info("Снимок %s снят с другой сцены: расхождение %.2f", path.name, share)
            mismatches.append(mismatch)
        return tuple(mismatches)

    def _image_hash(self, image_path: Path) -> tuple[int, ...]:
        """Считает разностный хеш снимка."""
        with Image.open(image_path) as source:
            grayscale = source.convert(GRAYSCALE_MODE)
            small = grayscale.resize((HASH_SIDE + 1, HASH_SIDE), Image.LANCZOS)
            pixels = small.load()
        bits = [
            1 if pixels[column, row] > pixels[column + 1, row] else 0
            for row in range(HASH_SIDE)
            for column in range(HASH_SIDE)
        ]
        return tuple(bits)


def _median_hash(hashes: list[tuple[int, ...]]) -> tuple[int, ...]:
    """Собирает портрет сцены смены: по каждому биту берётся то, что встречается чаще."""
    reference = [
        1 if sum(item[index] for item in hashes) * MAJORITY_FACTOR > len(hashes) else 0
        for index in range(BIT_COUNT)
    ]
    return tuple(reference)


def _difference_share(reference: tuple[int, ...], current: tuple[int, ...]) -> float:
    """Считает долю битов, которыми снимок расходится с портретом сцены."""
    if not reference:
        return NOTHING
    differences = sum(1 for left, right in zip(reference, current) if left != right)
    share = differences / len(reference)
    return share
