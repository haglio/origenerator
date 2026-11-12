from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QSize

from origenerator.gui.blurred import blurred_backdrop


def _hard_edged_checkerboard(path, size=(64, 48)):
    image = Image.new("RGB", size, (255, 255, 255))
    for x in range(size[0]):
        for y in range(size[1]):
            if (x // 4 + y // 4) % 2:
                image.putpixel((x, y), (0, 0, 0))
    image.save(path)
    return str(path)


def test_the_backdrop_fills_the_space_it_is_given(qtbot, tmp_path):
    backdrop = blurred_backdrop(_hard_edged_checkerboard(tmp_path / "src.png"), QSize(172, 160))

    assert (backdrop.width(), backdrop.height()) == (172, 160)


def test_a_tall_image_is_cropped_to_cover_the_plate_rather_than_barred(qtbot, tmp_path):
    def side_lightness(name, size):
        Image.new("RGB", size, (255, 255, 255)).save(tmp_path / name)
        image = blurred_backdrop(str(tmp_path / name), QSize(172, 160)).toImage()
        return [image.pixelColor(x, 80).lightness() for x in (0, 171)]

    assert side_lightness("tall.png", (40, 200)) == side_lightness("plate_shaped.png", (172, 160)), (
        "bars down a plate's sides read as an image that failed rather than as a backdrop")


def test_nothing_to_stand_there_is_not_an_error(qtbot, tmp_path):
    assert blurred_backdrop(str(tmp_path / "gone.png"), QSize(172, 160)) is None
    assert blurred_backdrop(None, QSize(172, 160)) is None
    assert blurred_backdrop(_hard_edged_checkerboard(tmp_path / "s.png"), QSize(0, 0)) is None


def test_the_backdrop_is_soft_and_dim_rather_than_the_image_itself(qtbot, tmp_path):
    backdrop = blurred_backdrop(_hard_edged_checkerboard(tmp_path / "src.png"), QSize(172, 160))
    image = backdrop.toImage()

    levels = [image.pixelColor(x, 80).lightness() for x in range(0, 172, 4)]
    assert max(levels) < 200
    assert max(levels) - min(levels) < 120


def test_the_same_image_at_the_same_size_is_only_rendered_once(qtbot, tmp_path):
    path = _hard_edged_checkerboard(tmp_path / "src.png")

    first = blurred_backdrop(path, QSize(172, 160))
    second = blurred_backdrop(path, QSize(172, 160))

    assert first is second, (
        "the collections rebuild on every poll, and this reads a full-size render off disk")
