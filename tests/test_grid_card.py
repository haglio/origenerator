"""The shape and caption size every card in a folder's grid shares."""
from __future__ import annotations

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QLabel
from shared_ui.fonts import FONT_UI, SIZE_TINY

from origenerator.gui import grid_card


def test_the_caption_is_set_in_the_familys_tiny_type(qtbot):
    font = grid_card.caption_font()

    assert (font.family(), font.pointSize()) == (FONT_UI, SIZE_TINY)


def test_a_folders_count_and_breadcrumb_are_each_a_whole_line_of_the_caption(qtbot):
    width, height = grid_card.card_size()
    line = QFontMetrics(grid_card.caption_font()).height()

    assert grid_card.folder_card_size() == (width, height + grid_card.CARD_SPACING + line)
    assert grid_card.folder_card_size(breadcrumb=True) == (
        width, height + 2 * (grid_card.CARD_SPACING + line))


def test_the_band_holds_two_whole_lines_of_the_caption(qtbot):
    # A seed is twenty digits and wraps at this size, so being clipped after one
    # line is what made the number every video tile is identified by unreadable.
    line = QFontMetrics(grid_card.caption_font()).height()

    assert grid_card.caption_height() == 2 * line


def test_the_card_is_as_tall_as_its_thumbnail_and_its_caption_need(qtbot):
    # The thumbnail is what the grid is for, so the card's height is what gives when
    # the caption needs more room — a bigger caption never quietly costs a line.
    width, height = grid_card.card_size()

    assert width == grid_card.CARD_WIDTH
    assert height == (2 * grid_card.CARD_MARGIN + grid_card.THUMBNAIL_SIZE[1]
                      + grid_card.CARD_SPACING + grid_card.caption_height())


def test_the_caption_is_never_larger_than_the_app_s_own(qtbot):
    assert grid_card.caption_font().pointSizeF() <= QApplication.instance().font().pointSizeF()


def test_styling_a_caption_gives_it_the_family_font_and_band(qtbot):
    label = QLabel("3FA9C0D2 000")
    qtbot.addWidget(label)

    grid_card.style_caption(label)

    assert label.font().pointSizeF() == grid_card.caption_font().pointSizeF()
    assert label.maximumHeight() == grid_card.caption_height()


def test_the_caption_is_handed_out_as_a_copy(qtbot):
    # A caller sets it on a widget, which may then change it; the next card's
    # caption must still be the size the grid chose.
    first = grid_card.caption_font()
    first.setPointSizeF(first.pointSizeF() + 4)

    assert grid_card.caption_font().pointSizeF() != first.pointSizeF()
