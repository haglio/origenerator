import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

from origenerator.gui.copy_button import CopyButton


@pytest.fixture(autouse=True)
def _clear_clipboard():
    QApplication.clipboard().clear()


def test_copies_fixed_text(qtbot):
    btn = CopyButton("out.png")
    qtbot.addWidget(btn)
    btn.click()
    assert QApplication.clipboard().text() == "out.png"


def test_copies_a_live_value_read_at_click_time(qtbot):
    # An editable field's value changes after the button is built; the copy must
    # reflect what's in the field when clicked, not what it held at construction.
    box = {"value": "first"}
    btn = CopyButton(lambda: box["value"])
    qtbot.addWidget(btn)
    box["value"] = "second"
    btn.click()
    assert QApplication.clipboard().text() == "second"


def test_is_a_button_tagged_for_styling_and_lookup(qtbot):
    btn = CopyButton("x")
    qtbot.addWidget(btn)
    assert isinstance(btn, QPushButton)
    assert btn.objectName() == "copyButton"


def test_wears_the_familys_copy_mark(qtbot):
    # Fun Time's log panel has a copy button too, and each app drew its own
    # two-sheets glyph at its own proportions -- the same drift the microphone
    # had. Both now come out of shared_ui, so the mark is one drawing.
    from PyQt6.QtCore import QSize
    from shared_ui.colors import TEXT_SECONDARY
    from shared_ui.icons import CANVAS, glyph_pixmap

    btn = CopyButton("x")
    qtbot.addWidget(btn)
    side = int(CANVAS)

    drawn = btn.icon().pixmap(QSize(side, side)).toImage()
    assert drawn == glyph_pixmap("copy", side, TEXT_SECONDARY).toImage()
