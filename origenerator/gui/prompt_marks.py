from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit
from shared_ui.colors import BG_PRIMARY, TEXT_MUTED, YELLOW

from origenerator.gui.tracked_prompt import prompt_ranges_from

RESOLVE_UNPAIRED_PARENTHESES = "Resolve parentheses first"
RESOLVE_BAD_WEIGHTS = "Resolve bad numbers first"
RESOLVE_UNREAD_EMPHASIS = "Resolve unread emphasis first"
RESOLVE_DUPLICATES = "Resolve duplicates first"
RESOLVE_IN_BOTH_PROMPTS = "Resolve prompt conflicts first"

_SAYS = (RESOLVE_UNPAIRED_PARENTHESES, RESOLVE_BAD_WEIGHTS, RESOLVE_UNREAD_EMPHASIS,
         RESOLVE_DUPLICATES, RESOLVE_IN_BOTH_PROMPTS)

Spans = tuple[tuple[int, int], ...]


class PromptProblems(NamedTuple):
    unpaired_parentheses: Spans = ()
    bad_weights: Spans = ()
    unread_emphasis: Spans = ()
    duplicates: Spans = ()
    in_both_prompts: Spans = ()


class _PromptMarks(QSyntaxHighlighter):
    starts_at: int | None = None
    unread = False
    problems = PromptProblems()

    def highlightBlock(self, text: str) -> None:
        field = self.parent()
        if self.starts_at is not None:
            ink = TEXT_MUTED if self.unread else BG_PRIMARY
            self._mark(text, prompt_ranges_from(field, self.starts_at), ink)
        for spans in self.problems:
            for start, end in spans:
                self._mark(text, _ranges_of(field, start, end), BG_PRIMARY)

    def _mark(self, text: str, ranges: list[tuple[int, int]], ink: QColor) -> None:
        marked = QTextCharFormat()
        marked.setBackground(YELLOW)
        marked.setForeground(ink)
        block = self.currentBlock().position()
        for start, end in ranges:
            begin, finish = max(start - block, 0), min(end - block, len(text))
            if begin < finish:
                self.setFormat(begin, finish - begin, marked)


def _ranges_of(field: QPlainTextEdit, start: int, end: int) -> list[tuple[int, int]]:
    ranges, left = [], end - start
    for begin, finish in prompt_ranges_from(field, start):
        if left <= 0:
            break
        taken = min(finish - begin, left)
        ranges.append((begin, begin + taken))
        left -= taken
    return ranges


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


def mark_problems(field: QPlainTextEdit, problems: PromptProblems) -> None:
    marks = _marks_on(field)
    if marks.problems != problems:
        marks.problems = problems
        marks.rehighlight()


def _problems_found(fields: Iterable[QPlainTextEdit]) -> list[str]:
    found = [marks.problems for marks in (field.findChild(_PromptMarks) for field in fields)
             if marks is not None]
    return [says for kind, says in enumerate(_SAYS) if any(problems[kind] for problems in found)]


def problem_to_resolve(fields: Iterable[QPlainTextEdit]) -> str | None:
    return next(iter(_problems_found(fields)), None)


def only_unread_emphasis_to_resolve(fields: Iterable[QPlainTextEdit]) -> bool:
    return _problems_found(fields) == [RESOLVE_UNREAD_EMPHASIS]


def has_unread_emphasis(field: QPlainTextEdit) -> bool:
    return RESOLVE_UNREAD_EMPHASIS in _problems_found([field])
