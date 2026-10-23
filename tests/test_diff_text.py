"""diff_text — what a prompt field is worth while it shows a change."""
from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN

from origenerator.gui import diff_text


def test_a_field_with_no_diff_reads_as_itself(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("a woman, freckles")

    assert diff_text.live_text(edit) == "a woman, freckles"


def test_what_arrived_is_lit_on_the_family_s_green():
    assert diff_text.added_format().background().color() == GREEN
