from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

from origenerator.gui.eliding import (
    ElidingButton,
    ElidingLabel,
    open_the_list_in_full,
)
from origenerator.gui.stylesheet import build_stylesheet

_LONG = "Show in Explorer"


@pytest.fixture(autouse=True)
def _wearing_the_apps_own_chrome():
    """Measure these widgets dressed the way the app dresses them.

    Every assertion here is a width against another width, and a stylesheet moves
    both: bare, a stock button's minimum is 116 px and the eliding one's is the
    style's own 80 px floor; under the app's sheet they are 132 and 61. So the
    file used to read whichever chrome the tests before it happened to leave on
    the application — passing in a full forward run and failing on its own, which
    says nothing about the widget either way.
    """
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(prior)


def test_it_does_not_hold_a_pane_open_at_its_label(qtbot):
    # The failure this exists for: a button's own minimum is its whole label, so
    # one sitting in a file row set a floor under the info pane and the settings
    # scroll grew a horizontal bar rather than let the row shrink.
    stock = QPushButton(_LONG)
    qtbot.addWidget(stock)
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)

    assert button.minimumSizeHint().width() < stock.minimumSizeHint().width() / 2
    assert button.minimumSizeHint().width() < button.fontMetrics().horizontalAdvance(_LONG)


def test_it_asks_for_its_whole_label_when_there_is_room(qtbot):
    # Only the floor moves: given the space, it still wants to read in full.
    stock = QPushButton(_LONG)
    qtbot.addWidget(stock)
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)

    assert button.sizeHint() == stock.sizeHint()


def test_a_squeezed_label_elides_rather_than_cuts_off(qtbot):
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)
    whole = button.fontMetrics().horizontalAdvance(_LONG)

    assert button.display_text(whole) == _LONG
    squeezed = button.display_text(whole // 3)
    assert squeezed != _LONG
    assert squeezed.endswith("…")


def test_an_ampersand_survives_as_a_character_not_a_mnemonic(qtbot):
    # Qt eats a lone "&" as an accelerator marker, so the button's text carries it
    # doubled — and the eliding happens on the raw label, which is what stops a
    # cut landing between the pair.
    button = ElidingButton("Models & LoRAs")
    qtbot.addWidget(button)

    assert button.text() == "Models && LoRAs"
    assert button.display_text(10_000) == "Models & LoRAs"


# --- the label ---------------------------------------------------------------

_PHRASE = "CFG (High) (0 = CFG Scale)"


def test_a_label_does_not_set_the_width_of_its_column(qtbot):
    # A form label's minimum is its whole phrase on one line, and a form takes that
    # as a floor under every row — which is what put a horizontal scroll bar under
    # the settings, and, once the rows were allowed to wrap instead, what put the
    # label out past the pane's edge.
    stock = QLabel(_PHRASE)
    qtbot.addWidget(stock)
    label = ElidingLabel(_PHRASE)
    qtbot.addWidget(label)

    assert label.minimumSizeHint().width() < stock.minimumSizeHint().width() / 4
    assert label.sizeHint() == stock.sizeHint()      # it still asks for the room


def test_a_squeezed_label_elides_but_keeps_its_text(qtbot):
    # Only what is drawn is shortened: the text is what a tooltip and a test read.
    label = ElidingLabel(_PHRASE)
    qtbot.addWidget(label)
    whole = label.fontMetrics().horizontalAdvance(_PHRASE)

    assert label.display_text(whole) == _PHRASE
    assert label.display_text(whole // 3).endswith("…")
    assert label.text() == _PHRASE


def test_a_dropdowns_list_keeps_room_for_its_longest_entry_and_a_scroll_bar(qtbot):
    """What widens the list is a minimum on it, and the scroll bar is why the
    minimum is not simply the longest entry: nineteen entries scroll, and the bar
    takes its width out of the room the names are read in."""
    dropdown = QComboBox()
    dropdown.addItems(["short", "an entry far longer than the field is ever given"])
    qtbot.addWidget(dropdown)
    bar = dropdown.view().verticalScrollBar().sizeHint().width()
    longest = dropdown.fontMetrics().horizontalAdvance(dropdown.itemText(1))
    assert dropdown.view().minimumWidth() < longest  # nothing asks for it yet

    open_the_list_in_full(dropdown)

    assert dropdown.view().minimumWidth() >= longest + bar
