from __future__ import annotations

from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import TEXT_MUTED


class _UnreadWords(QSyntaxHighlighter):
    stops_at: int | None = None

    def highlightBlock(self, text: str) -> None:
        if self.stops_at is None:
            return
        start = max(self.stops_at - self.currentBlock().position(), 0)
        if start < len(text):
            grayed = QTextCharFormat()
            grayed.setForeground(TEXT_MUTED)
            self.setFormat(start, len(text) - start, grayed)


def gray_past(field: QPlainTextEdit, stops_at: int | None) -> None:
    unread = field.findChild(_UnreadWords)
    if unread is None:
        unread = _UnreadWords(field)
        unread.setDocument(field.document())
    if unread.stops_at != stops_at:
        unread.stops_at = stops_at
        unread.rehighlight()
