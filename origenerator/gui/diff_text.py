from __future__ import annotations

from PyQt6.QtGui import QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN, RED, TEXT_PRIMARY

from origenerator.prompt_diff import ADDED, REMOVED, diff_spans

_REMOVED_COLOR = RED
_ADDED_BG = GREEN
_ADDED_COLOR = TEXT_PRIMARY

_VALUE_PROPERTY = "promptDiffValue"


def added_format() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setBackground(_ADDED_BG)
    fmt.setForeground(_ADDED_COLOR)
    return fmt


def removed_format() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontStrikeOut(True)
    fmt.setForeground(_REMOVED_COLOR)
    return fmt


def format_for(kind: str) -> QTextCharFormat:
    if kind == ADDED:
        return added_format()
    if kind == REMOVED:
        return removed_format()
    return QTextCharFormat()


def write_request_change(cursor: QTextCursor, old_positive: str, old_negative: str,
                         new_positive: str, new_negative: str, settings=()) -> None:
    heading = QTextCharFormat()
    heading.setFontWeight(QFont.Weight.Bold)

    def head(label: str) -> None:
        if cursor.position():
            cursor.insertBlock()
        cursor.insertText(label, heading)
        cursor.insertBlock()

    for label, before, after in (("Positive Prompt", old_positive, new_positive),
                                 ("Negative Prompt", old_negative, new_negative)):
        if not (before or after):
            continue
        head(label)
        for kind, piece in diff_spans(before, after):
            cursor.insertText(piece, format_for(kind))
    if settings:
        head("Settings")
        for n, (label, before, after) in enumerate(settings):
            if n:
                cursor.insertBlock()
            cursor.insertText(f"{label}: ")
            cursor.insertText(before, format_for(REMOVED))
            cursor.insertText(" ")
            cursor.insertText(after, format_for(ADDED))


def hold_value(edit: QPlainTextEdit, value: str | None) -> None:
    edit.setProperty(_VALUE_PROPERTY, value)


def live_text(edit: QPlainTextEdit) -> str:
    held = edit.property(_VALUE_PROPERTY)
    return held if held is not None else edit.toPlainText()


def clear_diff(edit: QPlainTextEdit) -> None:
    held = edit.property(_VALUE_PROPERTY)
    forget(edit)
    if held is not None and edit.toPlainText() != held:
        edit.setPlainText(held)


def forget(edit: QPlainTextEdit) -> None:
    edit.setProperty(_VALUE_PROPERTY, None)
