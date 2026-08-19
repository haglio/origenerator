"""A prompt field showing what is being typed into it as a change to what it said."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from origenerator.gui import diff_text, tracked_prompt
from origenerator.gui.tracked_prompt import SETTLE_MS


class _Pair(QWidget):
    """The field under test and somewhere else to click.

    A window with two fields in it, because leaving a field is one of the things
    that settles it — and a field can only be left for something. Shown, since an
    unshown widget takes no focus and so is never left either.
    """

    def __init__(self, text):
        super().__init__()
        box = QVBoxLayout(self)
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        self.elsewhere = QPlainTextEdit()
        box.addWidget(self.edit)
        box.addWidget(self.elsewhere)


@pytest.fixture
def pair(qtbot):
    widget = _Pair("a cat on a couch")
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _settle(qtbot):
    """Wait out the pause after which the departed words are put back."""
    qtbot.wait(SETTLE_MS + 80)


def _type_over(edit, word: str, replacement: str):
    """Select ``word`` and type ``replacement`` over it — the gesture this whole
    module exists for."""
    start = edit.toPlainText().index(word)
    cursor = edit.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(start + len(word), QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cursor)
    edit.insertPlainText(replacement)


def _marks(edit: QPlainTextEdit) -> list[tuple]:
    """``(text, mark)`` runs down the field, where mark is "lit", "struck" or
    "plain" — how the change reads to someone looking at it."""
    cursor = QTextCursor(edit.document())
    runs = []
    for _ in range(len(edit.toPlainText())):
        cursor.setPosition(cursor.position() + 1, QTextCursor.MoveMode.KeepAnchor)
        fmt = cursor.charFormat()
        mark = ("struck" if fmt.fontStrikeOut()
                else "lit" if fmt.background().style() != Qt.BrushStyle.NoBrush
                else "plain")
        piece = cursor.selectedText()
        if runs and runs[-1][1] == mark:
            runs[-1] = (runs[-1][0] + piece, mark)
        else:
            runs.append((piece, mark))
        cursor.setPosition(cursor.position())
    return runs


def _marked(edit, mark) -> str:
    """What is marked this way, with the whitespace either side of it dropped —
    a diff may hand a changed word its leading or trailing space, and which of
    the two it picks says nothing about the change."""
    return "".join(text for text, kind in _marks(edit) if kind == mark).strip()


def test_a_prompt_is_not_a_change_to_itself(pair):
    tracked_prompt.track(pair.edit, pair.edit.toPlainText())

    assert _marks(pair.edit) == [("a cat on a couch", "plain")]
    assert diff_text.live_text(pair.edit) == "a cat on a couch"


def test_words_typed_in_are_lit_as_they_are_typed(pair):
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()

    pair.edit.setPlainText("a ginger cat on a couch")

    assert _marked(pair.edit, "lit") == "ginger"
    # Lighting a word adds no text: the field still says exactly the prompt.
    assert pair.edit.toPlainText() == "a ginger cat on a couch"
    assert diff_text.live_text(pair.edit) == "a ginger cat on a couch"


def test_lighting_a_word_does_not_move_the_cursor(pair):
    # A keystroke only re-marks; if it rewrote the text the typist would be
    # thrown to the end of the field mid-word.
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()
    cursor = pair.edit.textCursor()
    cursor.setPosition(2)
    pair.edit.setTextCursor(cursor)

    pair.edit.insertPlainText("ginger ")

    assert pair.edit.textCursor().position() == len("a ginger ")
    assert _marked(pair.edit, "lit") == "ginger"


def test_typing_over_a_word_strikes_it_through_without_leaving_the_field(pair, qtbot):
    # The complaint this answers: the green arrived at once and the red waited
    # for a click somewhere else.
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()

    _type_over(pair.edit, "cat", "dog")
    _settle(qtbot)

    assert _marked(pair.edit, "struck") == "cat"
    assert _marked(pair.edit, "lit") == "dog"
    # The struck word is shown, not asked for: the prompt is what would generate.
    assert diff_text.live_text(pair.edit) == "a dog on a couch"


def test_the_caret_stays_where_it_was_typed_when_the_strike_arrives(pair, qtbot):
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()

    _type_over(pair.edit, "cat", "dog")
    _settle(qtbot)

    # Still just after "dog", which is now further along the document than it is
    # along the prompt — the struck "cat" sits in front of it.
    after_dog = pair.edit.toPlainText().index("dog") + len("dog")
    assert pair.edit.textCursor().position() == after_dog


def test_typing_on_takes_the_strike_back_out_and_keeps_the_prompt_right(pair, qtbot):
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()
    _type_over(pair.edit, "cat", "dog")
    _settle(qtbot)

    pair.edit.insertPlainText("gy")  # carry on typing: "dog" -> "doggy"

    assert pair.edit.toPlainText() == "a doggy on a couch"  # no strike in the way
    assert diff_text.live_text(pair.edit) == "a doggy on a couch"
    _settle(qtbot)
    assert _marked(pair.edit, "struck") == "cat"
    assert diff_text.live_text(pair.edit) == "a doggy on a couch"


def test_a_word_typed_and_taken_back_out_stops_being_marked(pair, qtbot):
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()

    _type_over(pair.edit, "cat", "dog")
    _settle(qtbot)
    _type_over(pair.edit, "dog", "cat")
    _settle(qtbot)

    assert _marks(pair.edit) == [("a cat on a couch", "plain")]
    assert diff_text.live_text(pair.edit) == "a cat on a couch"


def test_leaving_the_field_settles_it_without_waiting_out_the_clock(pair):
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()
    _type_over(pair.edit, "cat", "dog")

    pair.elsewhere.setFocus()

    assert _marked(pair.edit, "struck") == "cat"
    assert diff_text.live_text(pair.edit) == "a dog on a couch"


def test_a_rewrite_across_lines_keeps_the_prompt_whole(qtbot):
    # A struck-through line break doesn't report itself as struck, so a field
    # that read its own marks back would gain or lose newlines here.
    widget = _Pair("a cat\non a couch")
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    tracked_prompt.track(widget.edit, "a cat\non a couch")
    widget.edit.setFocus()

    _type_over(widget.edit, "cat", "dog")
    _settle(qtbot)

    assert diff_text.live_text(widget.edit) == "a dog\non a couch"
    assert _marked(widget.edit, "struck") == "cat"


def test_deleting_a_whole_line_keeps_the_prompt_whole(qtbot):
    widget = _Pair("a cat\non a couch")
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    tracked_prompt.track(widget.edit, "a cat\non a couch")
    widget.edit.setFocus()

    cursor = widget.edit.textCursor()
    cursor.setPosition(5)  # end of "a cat"
    cursor.setPosition(len("a cat\non a couch"), QTextCursor.MoveMode.KeepAnchor)
    widget.edit.setTextCursor(cursor)
    widget.edit.insertPlainText("")  # delete the selection
    _settle(qtbot)

    assert diff_text.live_text(widget.edit) == "a cat"


def test_untracking_leaves_an_ordinary_field_holding_its_prompt(pair, qtbot):
    tracked_prompt.track(pair.edit, "a cat on a couch")
    pair.edit.setFocus()
    _type_over(pair.edit, "cat", "dog")
    _settle(qtbot)

    tracked_prompt.untrack(pair.edit)

    assert tracked_prompt.baseline(pair.edit) is None
    assert pair.edit.toPlainText() == "a dog on a couch"
    # And no longer marks anything typed into it.
    pair.edit.setPlainText("a dog on a rug")
    _settle(qtbot)
    assert _marks(pair.edit) == [("a dog on a rug", "plain")]


def test_the_baseline_says_what_is_being_rewritten(pair):
    assert tracked_prompt.baseline(pair.edit) is None

    tracked_prompt.track(pair.edit, "a cat on a couch")

    assert tracked_prompt.baseline(pair.edit) == "a cat on a couch"
