"""The shape and caption size every card in a folder's grid shares."""

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QLabel

from origenerator.gui import grid_card


def test_the_caption_is_set_a_step_below_the_app_s_own_font():
    # Not far below: the first pass went small enough to fit a whole twenty-digit
    # seed on one line, and came out too small to read comfortably.
    assert grid_card.scaled_point_size(13.5) == 11.0
    assert grid_card.scaled_point_size(10.0) == 8.0


def test_a_caption_is_never_shrunk_past_reading():
    assert grid_card.scaled_point_size(2.0) == 7.0


def test_sizes_land_on_the_half_point():
    # Qt renders between the half points, but a caption asked for 10.8pt and one
    # asked for 10.5 measure the same — so the family picks a size it can predict.
    for base in (11.0, 12.0, 13.0, 14.0, 15.0, 16.0):
        assert grid_card.scaled_point_size(base) % 0.5 == 0


def test_the_band_holds_two_whole_lines_of_the_caption(qtbot):
    # A seed is twenty digits and wraps at this size, so being clipped after one
    # line is what made the number every video tile is identified by unreadable.
    line = QFontMetrics(grid_card.caption_font()).height()

    assert grid_card.caption_height() == 2 * line


def test_the_card_is_as_tall_as_its_picture_and_its_caption_need(qtbot):
    # The picture is what the grid is for, so the card's height is what gives when
    # the caption needs more room — a bigger caption never quietly costs a line.
    width, height = grid_card.card_size()

    assert width == grid_card.CARD_WIDTH
    assert height == (2 * grid_card.CARD_MARGIN + grid_card.PICTURE_SIZE[1]
                      + grid_card.CARD_SPACING + grid_card.caption_height())


def test_the_caption_is_never_larger_than_the_app_s_own(qtbot):
    assert grid_card.caption_font().pointSizeF() <= QApplication.instance().font().pointSizeF()


def test_styling_a_caption_gives_it_the_family_font_and_band(qtbot):
    label = QLabel("seed 1")
    qtbot.addWidget(label)

    grid_card.style_caption(label)

    assert label.font().pointSizeF() == grid_card.caption_font().pointSizeF()
    assert label.maximumHeight() == grid_card.caption_height()
