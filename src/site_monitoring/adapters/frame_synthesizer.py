"""Синтез похожих кадров из одного снимка: перемещение и удаление техники.

Машина вырезается один раз, её место на фоне заделывается соседним куском
земли, дальше вырезанная машина вставляется в нужную точку с мягкими краями.
Так кадры серии не накапливают следы предыдущих вставок.

Адаптер работает только с изображением и рамками, параметры приходят через
конструктор. Переменные окружения адаптер не читает.
"""

import logging
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

RELATIVE_BOX_LENGTH = 4
DONOR_GAP_RATIO = 1.1
FEATHER_RATIO = 0.12
FEATHER_BLUR_RATIO = 0.5
BRIGHTNESS_SPAN = 0.02
MIN_BRIGHTNESS = 1.0
MASK_MODE = "L"
MASK_OPAQUE = 255
MASK_TRANSPARENT = 0
VERTICAL_OFFSET_RATIO = 0.06


class FrameSynthesizer:
    """Готовит синтетические кадры: двигает технику, убирает её и качает камеру."""

    def __init__(self, seed: int, shake_pixels: int, margin_pixels: int) -> None:
        self._random = random.Random(seed)
        self._shake_pixels = shake_pixels
        self._margin_pixels = margin_pixels

    def absolute_box(self, image: Image.Image, box: tuple[float, ...]) -> tuple[int, int, int, int]:
        """Переводит рамку из долей кадра в пиксели."""
        if len(box) != RELATIVE_BOX_LENGTH:
            raise ValueError("Рамка должна состоять из четырёх координат")
        width, height = image.size
        left, top, right, bottom = box
        absolute = (int(left * width), int(top * height), int(right * width), int(bottom * height))
        return absolute

    def crop_machine(self, image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
        """Вырезает машину из кадра для последующих вставок."""
        patch = image.crop(box)
        return patch

    def remove_machine(self, image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
        """Убирает технику с кадра, заделывая её место куском фона сбоку на той же высоте."""
        result = image.copy()
        donor = self._donor_patch(result, box)
        mask = self._feather_mask(donor.size)
        result.paste(donor, (box[0], box[1]), mask)
        return result

    def paste_machine(
        self,
        image: Image.Image,
        patch: Image.Image,
        position: tuple[int, int],
    ) -> Image.Image:
        """Вставляет машину в кадр с мягкими краями, чтобы не было рамки от вставки."""
        result = image.copy()
        mask = self._feather_mask(patch.size)
        result.paste(patch, position, mask)
        return result

    def shake_and_crop(self, image: Image.Image, shake: bool) -> Image.Image:
        """Сдвигает кадр на пару пикселей (ветер) и срезает поля, чтобы не было чёрных краёв."""
        shift_x, shift_y = self._shake_offset(shake)
        width, height = image.size
        window = (
            self._margin_pixels + shift_x,
            self._margin_pixels + shift_y,
            width - self._margin_pixels + shift_x,
            height - self._margin_pixels + shift_y,
        )
        cropped = image.crop(window)
        return cropped

    def jitter_light(self, image: Image.Image) -> Image.Image:
        """Слегка меняет яркость, чтобы соседние кадры не были побайтно одинаковыми."""
        factor = MIN_BRIGHTNESS + self._random.uniform(-BRIGHTNESS_SPAN, BRIGHTNESS_SPAN)
        enhancer = ImageEnhance.Brightness(image)
        jittered = enhancer.enhance(factor)
        return jittered

    def working_offset(self, box: tuple[int, int, int, int], span: tuple[float, float]) -> tuple[int, int]:
        """Выдаёт сдвиг техники, заведомо больший порога признака перемещения."""
        width = box[2] - box[0]
        height = box[3] - box[1]
        share = self._random.uniform(*span)
        direction = self._random.choice((-1, 1))
        vertical = self._random.uniform(-VERTICAL_OFFSET_RATIO, VERTICAL_OFFSET_RATIO)
        offset = (int(direction * share * width), int(vertical * height))
        return offset

    def walk_box(
        self,
        box: tuple[int, int, int, int],
        origin: tuple[int, int, int, int],
        offset: tuple[int, int],
        band: tuple[float, float],
        keep_out: tuple[int, int, int, int] | None = None,
    ) -> tuple[int, int, int, int]:
        """Переносит рамку на сдвиг, удерживая машину в полосе вокруг исходного места.

        Полоса нужна, чтобы за смену техника не уползла в небо или за край кадра:
        по площадке машина ходит, но остаётся на своём рабочем участке. Если новое
        место накрывает соседнюю машину, сдвиг отражается в другую сторону, иначе
        переставленная техника закрывает собой ту, которую мы же и проверяем.
        """
        moved = self._shifted_in_band(box, origin, offset, band)
        if keep_out is None or not self._overlaps(moved, keep_out):
            return moved
        mirrored = self._shifted_in_band(box, origin, (-offset[0], offset[1]), band)
        if not self._overlaps(mirrored, keep_out):
            return mirrored
        return box

    def _shifted_in_band(
        self,
        box: tuple[int, int, int, int],
        origin: tuple[int, int, int, int],
        offset: tuple[int, int],
        band: tuple[float, float],
    ) -> tuple[int, int, int, int]:
        """Считает новое положение рамки внутри разрешённой полосы."""
        width = box[2] - box[0]
        height = box[3] - box[1]
        limit_x = band[0] * width
        limit_y = band[1] * height
        left = min(max(box[0] + offset[0], origin[0] - limit_x), origin[0] + limit_x)
        top = min(max(box[1] + offset[1], origin[1] - limit_y), origin[1] + limit_y)
        shifted = (int(left), int(top), int(left) + width, int(top) + height)
        return shifted

    def _overlaps(self, box: tuple[int, int, int, int], other: tuple[int, int, int, int]) -> bool:
        """Проверяет, пересекаются ли две рамки."""
        crossed = box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]
        return crossed

    def _shake_offset(self, shake: bool) -> tuple[int, int]:
        """Возвращает смещение кадра от ветра в пикселях."""
        if not shake:
            return (0, 0)
        limit = self._shake_pixels
        offset = (self._random.randint(-limit, limit), self._random.randint(-limit, limit))
        return offset

    def _donor_patch(self, image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
        """Берёт кусок фона сбоку от техники на той же высоте: земля рядом с землёй."""
        width = box[2] - box[0]
        shift = int(width * DONOR_GAP_RATIO)
        left = box[0] - shift if box[0] - shift >= 0 else box[0] + shift
        left = min(max(left, 0), image.size[0] - width)
        donor = image.crop((left, box[1], left + width, box[3]))
        return donor

    def _feather_mask(self, size: tuple[int, int]) -> Image.Image:
        """Готовит маску вставки с размытыми краями, чтобы шов не читался прямоугольником."""
        width, height = size
        inset = int(min(width, height) * FEATHER_RATIO)
        mask = Image.new(MASK_MODE, size, MASK_TRANSPARENT)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((inset, inset, width - inset, height - inset), fill=MASK_OPAQUE)
        blur_radius = max(inset * FEATHER_BLUR_RATIO, 1.0)
        blurred = mask.filter(ImageFilter.GaussianBlur(blur_radius))
        return blurred
