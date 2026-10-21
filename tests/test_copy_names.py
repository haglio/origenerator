from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from origenerator.gui.copy_names import copy_names


def test_nothing_to_copy_leaves_what_the_clipboard_held(qtbot):
    QApplication.clipboard().setText("something copied elsewhere")

    copy_names(["", ""])

    assert QApplication.clipboard().text() == "something copied elsewhere"
