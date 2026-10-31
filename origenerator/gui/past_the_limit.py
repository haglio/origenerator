from __future__ import annotations

from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import AMBER, BG_PRIMARY, TEXT_MUTED

from origenerator.gui.tracked_prompt import prompt_ranges_from


class _PastTheLimit(QSyntaxHighlighter):
    starts_at: int | None = None
    unread = False

    def highlightBlock(self, text: str) -> None:
        if self.starts_at is None:
            return
        marked = QTextCharFormat()
        marked.setBackground(AMBER)
        marked.setForeground(TEXT_MUTED if self.unread else BG_PRIMARY)
        block = self.currentBlock().position()
        for start, end in prompt_ranges_from(self.parent(), self.starts_at):
            begin, finish = max(start - block, 0), min(end - block, len(text))
            if begin < finish:
                self.setFormat(begin, finish - begin, marked)


def mark_past_the_limit(field: QPlainTextEdit, starts_at: int | None, *, unread: bool) -> None:
    marks = field.findChild(_PastTheLimit)
    if marks is None:
        marks = _PastTheLimit(field)
        marks.setDocument(field.document())
    if (marks.starts_at, marks.unread) != (starts_at, unread):
        marks.starts_at, marks.unread = starts_at, unread
        marks.rehighlight()
