from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN, RED

from origenerator.gui import diff_text


def test_a_field_with_no_diff_reads_as_itself(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("a woman, freckles")

    assert diff_text.live_text(edit) == "a woman, freckles"


def test_what_arrived_is_lit_on_the_family_s_green():
    assert diff_text.added_format().background().color() == GREEN


def test_what_went_is_struck_through_in_red_so_it_reads_as_no_longer_asked_for():
    fmt = diff_text.removed_format()

    assert fmt.fontStrikeOut()
    assert fmt.foreground().color() == RED


def _edit_showing_a_diff(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("a cat dog on a couch")
    diff_text.hold_value(edit, "a dog on a couch")
    return edit


def test_while_a_diff_is_up_the_field_is_worth_the_prompt_that_would_generate(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    assert edit.toPlainText() == "a cat dog on a couch"
    assert diff_text.live_text(edit) == "a dog on a couch"


def test_holding_nothing_returns_the_field_to_its_own_text(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    diff_text.hold_value(edit, None)

    assert diff_text.live_text(edit) == "a cat dog on a couch"


def test_clearing_a_diff_collapses_the_document_to_the_prompt_it_stands_for(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    diff_text.clear_diff(edit)

    assert edit.toPlainText() == "a dog on a couch"
    assert diff_text.live_text(edit) == "a dog on a couch"


def test_forgetting_a_diff_leaves_the_text_as_it_is(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    diff_text.forget(edit)

    assert edit.toPlainText() == "a cat dog on a couch"
    assert diff_text.live_text(edit) == "a cat dog on a couch"
