"""The sorting window: one picture, one press, the next picture.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest
from PIL import Image
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel, QPushButton, QToolButton

from origenerator.gui.sorting_window import (
    LAST_LINE,
    SAME_BUTTON,
    SKIP_BUTTON,
    STATUS_LINE,
    UNDO_BUTTON,
    SortingWindow,
    on_a_white_square,
    one_scale_for_all,
    state_button,
)
from origenerator.sorting_session import SortingSession

_STATES = ("state one", "state two", "state three")
_ROWS = (("state one", "state two"), ("state three",))


class _Store:
    def __init__(self):
        self.states = {}

    def set_picture_state(self, prompt_id, state):
        self.states[prompt_id] = state


def _drawn(path, size=(40, 60), color="gray"):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _tile(made, state) -> QToolButton:
    return made.findChild(QToolButton, state_button(state))


def _press(made, name) -> QPushButton:
    return made.findChild(QPushButton, name)


def _said(made, name) -> str:
    return made.findChild(QLabel, name).text()


def _picture(made) -> QLabel:
    return made.findChildren(QLabel)[0]


@pytest.fixture
def window(qtbot):
    def build(*prompt_ids, pictures=None, marks=None):
        store = _Store()
        listed = pictures or [{"prompt_id": p, "name": "3FA9C0D2 000", "picture_path": None}
                              for p in prompt_ids]
        made = SortingWindow(SortingSession(listed, store), _ROWS, marks or {})
        qtbot.addWidget(made)
        return made, store

    return build


def test_the_status_line_calls_the_picture_by_the_name_the_gallery_gives_it(window):
    made, _store = window(pictures=[{"prompt_id": "first", "name": "3FA9C0D2 004",
                                     "picture_path": None}])

    assert _said(made, STATUS_LINE) == "1 left · 3FA9C0D2 004"

def test_a_tile_is_offered_for_every_state_and_pressing_one_sorts_the_picture(window):
    made, store = window("first", "second")

    _tile(made, "state two").click()

    assert sorted(tile.text() for tile in made.findChildren(QToolButton)) == sorted(_STATES)
    assert store.states == {"first": "state two"}


def test_the_count_says_how_many_are_left_and_falls_as_they_are_sorted(window):
    made, _store = window("first", "second")
    assert _said(made, STATUS_LINE).startswith("2 ")

    _tile(made, "state one").click()

    assert _said(made, STATUS_LINE).startswith("1 ")


def test_the_last_line_names_what_the_last_press_did(window):
    made, _store = window("first", "second")

    _tile(made, "state one").click()

    assert "state one" in _said(made, LAST_LINE)


def test_the_window_says_when_there_is_nothing_left_to_sort(window):
    made, _store = window("only")

    _tile(made, "state one").click()

    assert _said(made, STATUS_LINE) == SortingWindow.NOTHING_LEFT


def test_same_as_last_gives_this_picture_the_state_the_last_one_got(window):
    made, store = window("first", "second")
    _tile(made, "state three").click()

    _press(made, SAME_BUTTON).click()

    assert store.states == {"first": "state three", "second": "state three"}


def test_same_as_last_with_nothing_sorted_yet_says_so_and_sorts_nothing(window):
    made, store = window("first")

    _press(made, SAME_BUTTON).click()

    assert store.states == {}
    assert "Nothing sorted yet" in _said(made, LAST_LINE)


def test_skipping_leaves_the_picture_unsorted_and_brings_up_the_next(window):
    made, store = window("first", "second")

    _press(made, SKIP_BUTTON).click()

    assert store.states == {}
    assert _said(made, STATUS_LINE).startswith("2 ")


def test_undo_takes_the_last_answer_back_and_puts_its_picture_up_again(window):
    made, store = window("first", "second")
    _tile(made, "state one").click()

    _press(made, UNDO_BUTTON).click()

    assert store.states == {"first": None}
    assert _said(made, STATUS_LINE).startswith("2 ")


def test_undo_with_nothing_answered_yet_says_so(window):
    made, _store = window("first")

    _press(made, UNDO_BUTTON).click()

    assert "Nothing to undo" in _said(made, LAST_LINE)


# --- the drawings on the buttons --------------------------------------------


def test_each_state_wears_its_own_drawing(window, tmp_path):
    made, _store = window("first", marks={"state two": _drawn(tmp_path / "two.png")})

    assert not _tile(made, "state two").icon().isNull()


def test_a_state_with_no_drawing_installed_stands_on_its_words(window):
    made, _store = window("first")

    assert _tile(made, "state one").icon().isNull()
    assert _tile(made, "state one").text() == "state one"


def test_a_state_of_several_terms_reads_one_term_to_a_line(qtbot):
    made = SortingWindow(SortingSession([], _Store()), (("alpha, beta gamma",),), {})
    qtbot.addWidget(made)

    assert _tile(made, "alpha, beta gamma").text() == "alpha\nbeta gamma"


def test_a_drawing_that_will_not_load_is_no_worse_than_none(window, tmp_path):
    torn = tmp_path / "torn.png"
    torn.write_bytes(b"not a picture at all")

    made, _store = window("first", marks={"state one": str(torn)})

    assert _tile(made, "state one").icon().isNull()


# --- the picture itself ------------------------------------------------------


def test_the_picture_is_drawn_at_the_size_the_window_gives_it(window, tmp_path):
    made, _store = window(pictures=[{"prompt_id": "first", "name": "3FA9C0D2 001",
                                     "picture_path": _drawn(tmp_path / "p.png",
                                                            size=(400, 600))}])
    made.resize(900, 900)
    _picture(made).resize(500, 700)

    made._fill_with_the_picture()

    drawn = _picture(made).pixmap()
    assert drawn.height() == 700  # the taller side fills, the shape is kept
    assert drawn.width() == 466


def test_growing_the_window_re_reads_the_picture_rather_than_stretching_a_copy(
        window, tmp_path):
    made, _store = window(pictures=[{"prompt_id": "first", "name": "3FA9C0D2 001",
                                     "picture_path": _drawn(tmp_path / "p.png",
                                                            size=(400, 600))}])
    _picture(made).resize(50, 75)
    made._fill_with_the_picture()

    _picture(made).resize(400, 600)
    made._fill_with_the_picture()

    drawn = _picture(made).pixmap()
    assert (drawn.width(), drawn.height()) == (400, 600)


def test_a_picture_whose_file_has_gone_says_so_rather_than_showing_nothing(window):
    made, _store = window(pictures=[{"prompt_id": "first", "name": "3FA9C0D2 001",
                                     "picture_path": None}])

    assert _picture(made).text() == SortingWindow.MISSING


# --- the grid of buttons -----------------------------------------------------


def test_every_button_is_the_same_shape_and_size(window, tmp_path):
    """A column was as wide as its own widest name, so the three columns came
    out three widths and the grid did not read as a grid."""
    made, _store = window("first", marks={
        "state one": _drawn(tmp_path / "one.png"),
        "state three": _drawn(tmp_path / "three.png", size=(140, 60)),
    })

    sizes = {_tile(made, state).size() for state in _STATES}

    assert len(sizes) == 1


def test_the_buttons_sit_where_the_grid_puts_them(window):
    made, _store = window("first")
    grid = _tile(made, "state one").parent().layout().itemAt(0).layout()

    placed = {grid.itemAt(i).widget().objectName(): (
        grid.getItemPosition(i)[0], grid.getItemPosition(i)[1])
        for i in range(grid.count())}

    assert placed[state_button("state one")] == (0, 0)
    assert placed[state_button("state two")] == (0, 1)
    assert placed[state_button("state three")] == (1, 0)


def test_a_drawing_is_centered_on_a_white_square():
    source = QPixmap(40, 20)
    source.fill(Qt.GlobalColor.black)

    square = on_a_white_square(source, 96, 1.0)

    assert square.size() == QSize(96, 96)
    assert square.toImage().pixelColor(0, 0) == QColor(Qt.GlobalColor.white)
    assert square.toImage().pixelColor(48, 48) == QColor(Qt.GlobalColor.black)


def test_one_scale_fits_the_largest_drawing_and_leaves_the_others_smaller():
    big, small = QPixmap(120, 60), QPixmap(60, 30)

    scale = one_scale_for_all((big, small), 96)

    assert round(big.width() * scale) == 96
    assert round(small.width() * scale) == 48


def test_a_drawing_that_will_not_load_does_not_set_the_scale():
    torn = QPixmap()

    assert one_scale_for_all((torn,), 96) == 1.0
