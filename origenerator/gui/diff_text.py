"""How a prompt field marks what changed, and what the field is worth meanwhile.

A field being edited against the picture it came from shows the change inside
itself (:mod:`origenerator.gui.tracked_prompt`): struck through in red where
words went, lit where they arrived. So its document can carry both versions at
once, and while it does, nothing may read the field with
:meth:`QPlainTextEdit.toPlainText` -- :func:`live_text` is what the form asks,
and it answers with the prompt that would actually generate.

The state rides on the widget itself (a Qt property) rather than in a table
here: a field outlives nothing, and a table keyed by widget would hold every
form the app ever built.
"""
from __future__ import annotations

from PyQt6.QtGui import QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN, RED, TEXT_PRIMARY

# What went is struck through in red; what arrived is lit. Red rather than a
# dimmed gray: the words are still in the field, and a reader skimming a long
# prompt has to be able to tell at a glance which of it is no longer asked for.
_REMOVED_COLOR = RED
_ADDED_BG = GREEN
_ADDED_COLOR = TEXT_PRIMARY

# The field's real value while a diff is up: the prompt that would generate, as
# opposed to the document, which also holds what the edit took out.
_VALUE_PROPERTY = "promptDiffValue"


def added_format() -> QTextCharFormat:
    """How arriving words are lit."""
    fmt = QTextCharFormat()
    fmt.setBackground(_ADDED_BG)
    fmt.setForeground(_ADDED_COLOR)
    return fmt


def removed_format() -> QTextCharFormat:
    """How departing words are struck through."""
    fmt = QTextCharFormat()
    fmt.setFontStrikeOut(True)
    fmt.setForeground(_REMOVED_COLOR)
    return fmt


def hold_value(edit: QPlainTextEdit, value: str | None) -> None:
    """Declare what ``edit`` is worth while its document says more than the prompt
    does — or ``None`` where the two are the same again. The held value is the
    whole of what :func:`live_text` answers with, so a painter that doesn't set
    it leaves the form reading the struck-out words as part of the prompt.
    """
    edit.setProperty(_VALUE_PROPERTY, value)


def live_text(edit: QPlainTextEdit) -> str:
    """What ``edit`` is really worth: the prompt that would generate.

    The same as its text, except while a diff is up — where the document also
    holds the words the edit removed, which are shown but are no longer part of
    the prompt.
    """
    held = edit.property(_VALUE_PROPERTY)
    return held if held is not None else edit.toPlainText()


def clear_diff(edit: QPlainTextEdit) -> None:
    """Collapse any diff on ``edit`` to the plain prompt it stands for."""
    held = edit.property(_VALUE_PROPERTY)
    forget(edit)
    if held is not None and edit.toPlainText() != held:
        edit.setPlainText(held)


def forget(edit: QPlainTextEdit) -> None:
    """Drop a diff's bookkeeping without touching the text — for a caller about
    to write its own value into the field anyway."""
    edit.setProperty(_VALUE_PROPERTY, None)
