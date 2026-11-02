from __future__ import annotations

from PyQt6.QtGui import QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN, RED, TEXT_PRIMARY

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
