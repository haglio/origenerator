"""Showing what a prompt edit changed, inside the field that holds the prompt.

A spoken request rewrites a prompt, and the only place that rewrite is worth
seeing is the prompt field itself — struck through where words went, lit where
they arrived. So the field's document carries both versions at once: the text
that survived, the text that left (struck, dimmed) and the text that arrived
(highlighted).

Which makes the document say more than the prompt does, so nothing may read the
field with :meth:`QPlainTextEdit.toPlainText` while a diff is up —
:func:`live_text` is what the form asks, and it answers with the prompt that
would actually generate. The moment the field is focused to be edited the diff
collapses to exactly that text, so an edited field is an ordinary field again
and the two can never disagree.

The state rides on the widget itself (a Qt property and a parented watcher)
rather than in a table here: a field outlives nothing, and a table keyed by
widget would hold every form the app ever built.
"""

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit

from origenerator.paths import ensure_shared_ui_on_path
from origenerator.prompt_diff import ADDED, REMOVED, diff_spans

ensure_shared_ui_on_path()

from shared_ui.colors import RED

# What went is struck through in red; what arrived is lit. Red rather than a
# dimmed gray: the words are still in the field, and a reader skimming a long
# prompt has to be able to tell at a glance which of it is no longer asked for.
_REMOVED_COLOR = RED
_ADDED_BG = QColor("#1f4d2a")
_ADDED_COLOR = QColor("#d8f5de")

# The field's real value while a diff is up: the prompt that would generate, as
# opposed to the document, which also holds what the edit took out.
_VALUE_PROPERTY = "promptDiffValue"


class _EditWatcher(QObject):
    """Collapses a field's diff the moment it is focused to be edited."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn:
            clear_diff(obj)
        return False


def show_diff(edit: QPlainTextEdit, before: str, after: str) -> None:
    """Fill ``edit`` with the change from ``before`` to ``after``, marked.

    A no-op when nothing changed: an unmarked field already says everything
    there is to say, and a diff of a prompt against itself would only teach the
    reader to ignore the marks.
    """
    if before == after:
        return
    forget(edit)
    spans = diff_spans(before, after)
    edit.setPlainText("".join(text for _kind, text in spans))
    cursor = QTextCursor(edit.document())
    cursor.setPosition(0)
    for kind, text in spans:
        cursor.setPosition(cursor.position() + len(text), QTextCursor.MoveMode.KeepAnchor)
        if kind in (REMOVED, ADDED):
            cursor.mergeCharFormat(_format_for(kind))
        cursor.setPosition(cursor.position())  # collapse, ready for the next span
    edit.setProperty(_VALUE_PROPERTY, after)
    edit.installEventFilter(_EditWatcher(edit))


def added_format() -> QTextCharFormat:
    """How arriving words are lit.

    Public because a field being rewritten by hand draws the same change as it
    is typed (:mod:`origenerator.gui.tracked_prompt`), and the two surfaces have
    to mark the same thing the same way.
    """
    fmt = QTextCharFormat()
    fmt.setBackground(_ADDED_BG)
    fmt.setForeground(_ADDED_COLOR)
    return fmt


def removed_format() -> QTextCharFormat:
    """How departing words are struck through.

    Public for the same reason :func:`added_format` is.
    """
    fmt = QTextCharFormat()
    fmt.setFontStrikeOut(True)
    fmt.setForeground(_REMOVED_COLOR)
    return fmt


def _format_for(kind: str) -> QTextCharFormat:
    return added_format() if kind == ADDED else removed_format()


def hold_value(edit: QPlainTextEdit, value: str | None) -> None:
    """Declare what ``edit`` is worth while its document says more than the prompt
    does — or ``None`` where the two are the same again.

    For a caller painting its own marks rather than going through
    :func:`show_diff`: the held value is the whole of what
    :func:`live_text` answers with, so a painter that doesn't set it leaves the
    form reading the struck-out words as part of the prompt.
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
    for watcher in edit.findChildren(_EditWatcher):
        edit.removeEventFilter(watcher)
        watcher.setParent(None)
        watcher.deleteLater()
