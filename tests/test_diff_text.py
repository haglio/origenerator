"""diff_text — a prompt field showing what a request changed about it.

Invented prompts throughout; what is under test is the marking and, above all,
that the field's *value* stays the prompt that would generate.
"""

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QPlainTextEdit

from origenerator.gui import diff_text


def _edit(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    return edit


def _format_at(edit, needle):
    """The character format of the first character of ``needle``."""
    cursor = QTextCursor(edit.document())
    cursor.setPosition(edit.toPlainText().index(needle) + 1)
    return cursor.charFormat()


def test_the_field_shows_what_went_as_well_as_what_stayed(qtbot):
    edit = _edit(qtbot)

    diff_text.show_diff(edit, "a woman, a hat, soft light", "a woman, soft light")

    assert "a hat" in edit.toPlainText()
    assert _format_at(edit, "hat").fontStrikeOut()


def test_what_arrived_is_lit_rather_than_struck(qtbot):
    edit = _edit(qtbot)

    diff_text.show_diff(edit, "a woman", "a woman, freckles")

    assert not _format_at(edit, "freckles").fontStrikeOut()
    assert _format_at(edit, "freckles").background().color().name() != "#000000"


def test_the_fields_value_is_the_prompt_that_would_generate(qtbot):
    # The document says more than the prompt does, so nothing may read it raw.
    edit = _edit(qtbot)

    diff_text.show_diff(edit, "a woman, a hat, soft light", "a woman, soft light")

    assert diff_text.live_text(edit) == "a woman, soft light"
    assert edit.toPlainText() != diff_text.live_text(edit)


def test_focusing_the_field_to_edit_it_collapses_the_diff(qtbot):
    edit = _edit(qtbot)
    diff_text.show_diff(edit, "a woman, a hat", "a woman")

    # Through the application, as a real focus arrives — event filters are
    # consulted on the way, which is where the collapse lives.
    QApplication.sendEvent(edit, QEvent(QEvent.Type.FocusIn))

    assert edit.toPlainText() == "a woman"
    assert diff_text.live_text(edit) == "a woman"


def test_an_unchanged_prompt_is_left_unmarked(qtbot):
    # A diff of a prompt against itself would only teach the reader to ignore
    # the marks.
    edit = _edit(qtbot)
    edit.setPlainText("a woman")

    diff_text.show_diff(edit, "a woman", "a woman")

    assert _format_at(edit, "woman").properties() == {}  # no strike, no lit ground


def test_a_field_with_no_diff_reads_as_itself(qtbot):
    edit = _edit(qtbot)
    edit.setPlainText("a woman, freckles")

    assert diff_text.live_text(edit) == "a woman, freckles"


def test_showing_a_second_diff_replaces_the_first(qtbot):
    edit = _edit(qtbot)
    diff_text.show_diff(edit, "a woman, a hat", "a woman")

    diff_text.show_diff(edit, "a woman, freckles", "a woman")

    assert diff_text.live_text(edit) == "a woman"
    assert "freckles" in edit.toPlainText() and "hat" not in edit.toPlainText()


def test_what_went_is_struck_through_in_red(qtbot):
    # The words are still in the field, so a reader skimming a long prompt has
    # to be able to tell at a glance which of it is no longer asked for.
    edit = _edit(qtbot)

    diff_text.show_diff(edit, "a woman, a hat", "a woman")

    fmt = _format_at(edit, "hat")
    assert fmt.fontStrikeOut()
    assert fmt.foreground().color().red() > 200
    assert fmt.foreground().color().green() < 100
