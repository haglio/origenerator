from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QPushButton
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import CANVAS, icon_pixmap

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
    edited = {"value": "first"}
    btn = CopyButton(lambda: edited["value"])
    qtbot.addWidget(btn)
    edited["value"] = "second"
    btn.click()
    assert QApplication.clipboard().text() == "second"


def test_is_a_button_tagged_for_styling_and_lookup(qtbot):
    btn = CopyButton("x")
    qtbot.addWidget(btn)
    assert isinstance(btn, QPushButton)
    assert btn.objectName() == "copyButton"


def test_wears_the_familys_copy_mark(qtbot):
    btn = CopyButton("x")
    qtbot.addWidget(btn)
    side = int(CANVAS)

    drawn = btn.icon().pixmap(QSize(side, side)).toImage()
    assert drawn == icon_pixmap("copy", side, TEXT_SECONDARY).toImage()
