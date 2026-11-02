from __future__ import annotations

from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import BG_PRIMARY, TEXT_MUTED, YELLOW

from origenerator.gui.tracked_prompt import prompt_ranges_from


class _PromptMarks(QSyntaxHighlighter):
    starts_at: int | None = None
    unread = False
    unpaired: tuple[int, ...] = ()

    def highlightBlock(self, text: str) -> None:
        field = self.parent()
        if self.starts_at is not None:
            ink = TEXT_MUTED if self.unread else BG_PRIMARY
            self._mark(text, prompt_ranges_from(field, self.starts_at), ink)
        for at in self.unpaired:
            for start, _end in prompt_ranges_from(field, at)[:1]:
                self._mark(text, [(start, start + 1)], BG_PRIMARY)

    def _mark(self, text: str, ranges: list[tuple[int, int]], ink: QColor) -> None:
        marked = QTextCharFormat()
        marked.setBackground(YELLOW)
        marked.setForeground(ink)
        block = self.currentBlock().position()
        for start, end in ranges:
            begin, finish = max(start - block, 0), min(end - block, len(text))
            if begin < finish:
                self.setFormat(begin, finish - begin, marked)


def _marks_on(field: QPlainTextEdit) -> _PromptMarks:
    marks = field.findChild(_PromptMarks)
    if marks is None:
        marks = _PromptMarks(field)
        marks.setDocument(field.document())
    return marks


def mark_past_the_limit(field: QPlainTextEdit, starts_at: int | None, *, unread: bool) -> None:
    marks = _marks_on(field)
    if (marks.starts_at, marks.unread) != (starts_at, unread):
        marks.starts_at, marks.unread = starts_at, unread
        marks.rehighlight()


def mark_unpaired_parentheses(field: QPlainTextEdit, unpaired: tuple[int, ...]) -> None:
    marks = _marks_on(field)
    if marks.unpaired != unpaired:
        marks.unpaired = unpaired
        marks.rehighlight()


def has_unpaired_parentheses(field: QPlainTextEdit) -> bool:
    marks = field.findChild(_PromptMarks)
    return marks is not None and bool(marks.unpaired)
