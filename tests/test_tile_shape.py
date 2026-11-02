"""The shape and caption size every tile in a folder's grid shares."""
from __future__ import annotations

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QLabel
from shared_ui.fonts import FONT_UI, SIZE_TINY

from origenerator.gui import tile_shape


def test_the_caption_is_set_in_the_familys_tiny_type(qtbot):
    font = tile_shape.caption_font()

    assert (font.family(), font.pointSize()) == (FONT_UI, SIZE_TINY)


def test_a_folders_count_and_folder_path_are_each_a_whole_line_of_the_caption(qtbot):
    width, height = tile_shape.tile_size()
    line = QFontMetrics(tile_shape.caption_font()).height()

    assert tile_shape.folder_tile_size() == (width, height + tile_shape.TILE_SPACING + line)
    assert tile_shape.folder_tile_size(folder_path=True) == (
        width, height + 2 * (tile_shape.TILE_SPACING + line))


def test_the_band_holds_two_whole_lines_of_the_caption(qtbot):
    # A seed is twenty digits and wraps at this size, so being clipped after one
    # line is what made the number every video tile is identified by unreadable.
    line = QFontMetrics(tile_shape.caption_font()).height()

    assert tile_shape.caption_height() == 2 * line


def test_the_tile_is_as_tall_as_its_thumbnail_and_its_caption_need(qtbot):
    # The thumbnail is what the grid is for, so the tile's height is what gives when
    # the caption needs more room — a bigger caption never quietly costs a line.
    width, height = tile_shape.tile_size()

    assert width == tile_shape.TILE_WIDTH
    assert height == (2 * tile_shape.TILE_MARGIN + tile_shape.THUMBNAIL_SIZE[1]
                      + tile_shape.TILE_SPACING + tile_shape.caption_height())


def test_the_caption_is_never_larger_than_the_app_s_own(qtbot):
    assert tile_shape.caption_font().pointSizeF() <= QApplication.instance().font().pointSizeF()


def test_styling_a_caption_gives_it_the_family_font_and_band(qtbot):
    label = QLabel("3FA9C0D2 000")
    qtbot.addWidget(label)

    tile_shape.style_caption(label)

    assert label.font().pointSizeF() == tile_shape.caption_font().pointSizeF()
    assert label.maximumHeight() == tile_shape.caption_height()


def test_the_caption_is_handed_out_as_a_copy(qtbot):
    # A caller sets it on a widget, which may then change it; the next tile's
    # caption must still be the size the grid chose.
    first = tile_shape.caption_font()
    first.setPointSizeF(first.pointSizeF() + 4)

    assert tile_shape.caption_font().pointSizeF() != first.pointSizeF()
