"""Проверки геометрии и заделки фона при синтезе кадров."""

from PIL import Image

from site_monitoring.adapters.frame_synthesizer import FrameSynthesizer

SEED = 1
SHAKE_PIXELS = 4
MARGIN_PIXELS = 12
IMAGE_SIZE = (400, 300)
BOX = (100, 100, 180, 160)
BAND = (1.2, 0.25)


def build_image() -> Image.Image:
    """Готовит тестовый кадр с цветным пятном на месте техники."""
    image = Image.new("RGB", IMAGE_SIZE, (30, 60, 90))
    image.paste(Image.new("RGB", (80, 60), (250, 200, 10)), (BOX[0], BOX[1]))
    return image


def test_absolute_box_translates_shares_to_pixels() -> None:
    # Arrange
    synthesizer = FrameSynthesizer(SEED, SHAKE_PIXELS, MARGIN_PIXELS)
    image = build_image()

    # Act
    box = synthesizer.absolute_box(image, (0.25, 0.5, 0.5, 1.0))

    # Assert
    assert box == (100, 150, 200, 300)


def test_walk_box_keeps_machine_inside_band() -> None:
    # Arrange
    synthesizer = FrameSynthesizer(SEED, SHAKE_PIXELS, MARGIN_PIXELS)

    # Act
    moved = synthesizer.walk_box(BOX, BOX, (10_000, 10_000), BAND)

    # Assert
    assert moved[0] == BOX[0] + int(BAND[0] * (BOX[2] - BOX[0]))
    assert moved[1] == BOX[1] + int(BAND[1] * (BOX[3] - BOX[1]))


def test_working_offset_exceeds_movement_threshold() -> None:
    # Arrange
    synthesizer = FrameSynthesizer(SEED, SHAKE_PIXELS, MARGIN_PIXELS)
    diagonal = ((BOX[2] - BOX[0]) ** 2 + (BOX[3] - BOX[1]) ** 2) ** 0.5

    # Act
    offset = synthesizer.working_offset(BOX, (0.25, 0.55))

    # Assert
    shift = (offset[0] ** 2 + offset[1] ** 2) ** 0.5
    assert shift / diagonal > 0.15


def test_remove_machine_replaces_bright_spot_with_background() -> None:
    # Arrange
    synthesizer = FrameSynthesizer(SEED, SHAKE_PIXELS, MARGIN_PIXELS)
    image = build_image()

    # Act
    cleaned = synthesizer.remove_machine(image, BOX)

    # Assert
    center = cleaned.getpixel(((BOX[0] + BOX[2]) // 2, (BOX[1] + BOX[3]) // 2))
    assert center[0] < 100


def test_shake_and_crop_trims_margins() -> None:
    # Arrange
    synthesizer = FrameSynthesizer(SEED, SHAKE_PIXELS, MARGIN_PIXELS)
    image = build_image()

    # Act
    cropped = synthesizer.shake_and_crop(image, True)

    # Assert
    assert cropped.size == (IMAGE_SIZE[0] - 2 * MARGIN_PIXELS, IMAGE_SIZE[1] - 2 * MARGIN_PIXELS)
