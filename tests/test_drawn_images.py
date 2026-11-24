from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QColor

from origenerator.gui.drawn_images import as_qimage


def test_an_image_drawn_in_memory_reaches_the_screen_with_its_colors_and_size(qapp):
    drawn = Image.new("RGB", (7, 5), (10, 20, 30))
    drawn.putpixel((6, 4), (200, 100, 50))

    on_screen = as_qimage(drawn)

    assert (on_screen.width(), on_screen.height()) == (7, 5)
    assert on_screen.pixelColor(0, 0) == QColor(10, 20, 30)
    assert on_screen.pixelColor(6, 4) == QColor(200, 100, 50)


def test_an_image_with_see_through_parts_keeps_them(qapp):
    on_screen = as_qimage(Image.new("RGBA", (3, 3), (10, 20, 30, 40)))

    assert on_screen.pixelColor(1, 1) == QColor(10, 20, 30, 40)


def test_an_image_of_any_other_kind_is_shown_in_color(qapp):
    on_screen = as_qimage(Image.new("L", (3, 3), 128))

    assert on_screen.pixelColor(1, 1) == QColor(128, 128, 128)
