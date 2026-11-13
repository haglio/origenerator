from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton

from origenerator.gui.eliding import (
    ElidingButton,
    ElidingLabel,
    open_the_list_in_full,
)
from origenerator.gui.stylesheet import build_stylesheet

_LONG = "Show in Explorer"


@pytest.fixture(autouse=True)
def _wearing_the_apps_own_chrome(sheet_put_back_for_later_tests):
    """A Qt stylesheet moves both widths of every comparison, so measure under the app's own."""
    sheet_put_back_for_later_tests.setStyleSheet(build_stylesheet())


def test_it_does_not_hold_a_pane_open_at_its_label(qtbot):
    stock = QPushButton(_LONG)
    qtbot.addWidget(stock)
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)

    assert button.minimumSizeHint().width() < stock.minimumSizeHint().width() / 2
    assert button.minimumSizeHint().width() < button.fontMetrics().horizontalAdvance(_LONG)


def test_it_asks_for_its_whole_label_when_there_is_room(qtbot):
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
    button = ElidingButton("Models & LoRAs")
    qtbot.addWidget(button)

    assert button.text() == "Models && LoRAs"
    assert button.display_text(10_000) == "Models & LoRAs"


_PHRASE = "CFG (High) (0 = CFG Scale)"


def test_a_label_does_not_set_the_width_of_its_column(qtbot):
    stock = QLabel(_PHRASE)
    qtbot.addWidget(stock)
    label = ElidingLabel(_PHRASE)
    qtbot.addWidget(label)

    assert label.minimumSizeHint().width() < stock.minimumSizeHint().width() / 4
    assert label.sizeHint() == stock.sizeHint()


def test_a_squeezed_label_elides_but_keeps_its_text(qtbot):
    label = ElidingLabel(_PHRASE)
    qtbot.addWidget(label)
    whole = label.fontMetrics().horizontalAdvance(_PHRASE)

    assert label.display_text(whole) == _PHRASE
    assert label.display_text(whole // 3).endswith("…")
    assert label.text() == _PHRASE


def test_a_label_paints_its_colors_and_alignment_as_qlabel_does(qtbot):
    def painted(label):
        qtbot.addWidget(label)
        label.setStyleSheet("color: rgb(220, 40, 40); background: rgb(30, 60, 200);")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        label.resize(label.sizeHint().width() * 2, label.sizeHint().height() * 2)
        return label.grab().toImage()

    assert painted(ElidingLabel(_PHRASE)) == painted(QLabel(_PHRASE)), (
        "the label paints through the style as QLabel does, so it keeps the colors and the "
        "alignment its stylesheet and its owner give it")


@pytest.mark.parametrize("alignment", [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight])
def test_a_framed_label_indents_its_text_from_the_frame_as_qlabel_does(qtbot, alignment):
    def painted(label):
        qtbot.addWidget(label)
        label.setFrameShape(QFrame.Shape.Box)
        label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        label.resize(label.sizeHint().width() * 2, label.sizeHint().height())
        return label.grab().toImage()

    assert painted(ElidingLabel(_PHRASE)) == painted(QLabel(_PHRASE)), (
        "a stock label keeps half an x of room between its frame and its text, so a label "
        "beside it that elides keeps the same room")


def test_a_dropdowns_list_keeps_room_for_its_longest_entry_and_a_scroll_bar(qtbot):
    dropdown = QComboBox()
    dropdown.addItems(["short", "an entry far longer than the field is ever given"])
    qtbot.addWidget(dropdown)
    bar = dropdown.view().verticalScrollBar().sizeHint().width()
    longest = dropdown.fontMetrics().horizontalAdvance(dropdown.itemText(1))
    assert dropdown.view().minimumWidth() < longest

    open_the_list_in_full(dropdown)

    assert dropdown.view().minimumWidth() >= longest + bar
