"""A prompt field that shows what you are changing to it, while you change it.

Every prompt on a tab showing an image is marked against the prompt that made
the image, or that a request was asked of, and a folder's Modify against the
folder's own, so a glance shows how far the words have come. The marks keep up with the
typing: type over a word and the word you replaced is struck through beside what
replaced it, right there, without waiting for you to click somewhere else.

Which means the document holds more than the prompt: the words that survived,
the words that arrived, and the words that left. So the field is worth what
:func:`origenerator.gui.diff_text.live_text` says it is rather than what it
literally contains, exactly as a request's diff is, and the form reads it
through that.

Keeping the two in step is the whole of this module. The rule is that the
rendered spans always spell the document exactly, so any edit the user makes can
be translated from where it landed in the *document* to where it belongs in the
*prompt* — which is what ``QTextDocument.contentsChange`` reports precisely
enough to do. Nothing is read back out of the character formats: a struck-through
line break does not report itself as struck, so a reader built on the marks would
silently gain and lose newlines.

Two states, and the field moves between them on its own:

* **Being typed in.** The document is the prompt, with arriving words lit.
  Lighting adds no text and moves no cursor, so this costs a keystroke nothing.
* **Settled.** A moment after the typing stops, the words that left are put back
  in, struck through. The next keystroke takes them out again and the clock
  restarts, so the strikes are never in the way of the typing they describe.

The document's own undo is off while a field is tracked: it is rewritten under
the typist on every settle, so its undo would step back through renders rather
than through edits. The tracker keeps its own instead, one step per burst of
typing, over the prompt rather than the document.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QBrush, QKeySequence, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit

from origenerator.gui import diff_text
from origenerator.prompt_diff import ADDED, REMOVED, SAME, diff_spans

# How long after the last keystroke the departed words are put back. Short
# enough to read as "while I type" — the complaint this answers was a strike
# that waited for the field to be left — and long enough that a burst of typing
# rewrites the document once rather than once per letter.
SETTLE_MS = 150


def _plain_format() -> QTextCharFormat:
    """The unmarked look, spelled out rather than left default: the marks are
    re-applied from scratch on every pass, so a pass has to be able to take one
    back off a word that is no longer new."""
    fmt = QTextCharFormat()
    fmt.setFontStrikeOut(False)
    fmt.setBackground(QBrush(Qt.BrushStyle.NoBrush))
    fmt.setForeground(QBrush(Qt.BrushStyle.NoBrush))
    return fmt


def _unmark(edit: QPlainTextEdit) -> None:
    """Take every mark off the whole field, ready for a pass to put back only the
    ones that still apply.

    Needed even straight after the text is rewritten: a field writes new text in
    whatever format was under the caret, so a document replaced while a word was
    lit comes back lit end to end.
    """
    cursor = QTextCursor(edit.document())
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeCharFormat(_plain_format())


def _spliced(layout: list, position: int, removed: int, inserted: str) -> list:
    before, after, doc = [], [], 0
    for kind, text in layout:
        before.append((kind, text[:max(0, position - doc)]))
        after.append((kind, text[max(0, position + removed - doc):]))
        doc += len(text)
    return [(kind, text) for kind, text in before + [(ADDED, inserted)] + after if text]


class UndoHistory(QObject):
    def __init__(self, parent: QObject, read: Callable[[], str], show: Callable[[str], None]):
        super().__init__(parent)
        self._read = read
        self._show = show
        self._undone: list[str] = []
        self._redone: list[str] = []

    def took(self, before: str) -> None:
        self._undone.append(before)
        self._redone.clear()

    def watch(self, edit: QPlainTextEdit) -> None:
        edit.installEventFilter(self)

    def unwatch(self, edit: QPlainTextEdit) -> None:
        edit.removeEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            undo = event.matches(QKeySequence.StandardKey.Undo)
            redo = event.matches(QKeySequence.StandardKey.Redo)
            if undo or redo:
                event.accept()  # the field's, not the window's own Undo
                if event.type() == QEvent.Type.KeyPress:
                    self._step(*((self._undone, self._redone) if undo
                                 else (self._redone, self._undone)))
                return True
        return False

    def _step(self, back: list[str], forth: list[str]) -> None:
        if not back:
            return
        forth.append(self._read())
        self._show(back.pop())


class _Tracker(QObject):
    """Keeps one field's marks — and the prompt under them — in step with what is
    typed into it."""

    def __init__(self, edit: QPlainTextEdit, baseline: str):
        super().__init__(edit)
        self._edit = edit
        self._baseline = baseline
        self._value = edit.toPlainText()  # the prompt the field is worth
        # The spans the document is currently spelled out of. Their texts joined
        # are exactly its text, which is the invariant every translation below
        # rests on.
        self._layout: list = [(SAME, self._value)] if self._value else []
        self._writing = False  # our own rewrites, which must not re-enter
        self._history = UndoHistory(self, lambda: self._value, self._show_whole)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.show_whole_change)
        self._prompt_caret = 0
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.timeout.connect(self._show_prompt_only)
        edit.setUndoRedoEnabled(False)  # see the module docstring
        edit.installEventFilter(self)
        self._history.watch(edit)
        edit.document().contentsChange.connect(self._on_contents_change)

    def detach(self) -> None:
        self._settle.stop()
        self._redraw.stop()
        self._edit.removeEventFilter(self)
        self._history.unwatch(self._edit)
        self._edit.document().contentsChange.disconnect(self._on_contents_change)
        self._edit.setUndoRedoEnabled(True)
        self.setParent(None)
        self.deleteLater()

    @contextmanager
    def _own_write(self):
        self._writing = True
        try:
            yield
        finally:
            self._writing = False

    # --- translating between the document and the prompt --------------------

    def _prompt_offset(self, doc_offset: int) -> int:
        """Where a position in the document falls in the prompt.

        A position inside a struck-through run is the point that run sits at:
        those words are not in the prompt, so there is nowhere else for it to be.
        """
        doc = prompt = 0
        for kind, text in self._layout:
            if doc + len(text) >= doc_offset:
                return prompt if kind == REMOVED else prompt + (doc_offset - doc)
            doc += len(text)
            if kind != REMOVED:
                prompt += len(text)
        return prompt

    def _document_offset(self, prompt_offset: int) -> int:
        """Where a position in the prompt falls in the document — the earliest
        such position, so a caret at the end of a word lands before the struck
        run that follows it rather than after it."""
        doc = prompt = 0
        for kind, text in self._layout:
            if kind != REMOVED:
                if prompt + len(text) >= prompt_offset:
                    return doc + (prompt_offset - prompt)
                prompt += len(text)
            doc += len(text)
        return doc

    # --- rendering ----------------------------------------------------------

    def _paint(self, spans: list, caret: int) -> None:
        """Spell the document out of ``spans`` and put the caret back at
        ``caret`` — a position in the prompt, not in the document, since the
        document is about to be a different length."""
        self._layout = spans
        text = "".join(piece for _kind, piece in spans)
        with self._own_write():
            # What the field is worth, whenever that is no longer what it says.
            diff_text.hold_value(self._edit,
                                 None if text == self._value else self._value)
            self._edit.setPlainText(text)
            _unmark(self._edit)
            cursor = QTextCursor(self._edit.document())
            cursor.setPosition(0)
            for kind, piece in spans:
                end = cursor.position() + len(piece)
                if kind != SAME:
                    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                    cursor.mergeCharFormat(diff_text.added_format() if kind == ADDED
                                           else diff_text.removed_format())
                cursor.setPosition(end)
            place = QTextCursor(self._edit.document())
            place.setPosition(min(self._document_offset(caret), len(text)))
            self._edit.setTextCursor(place)

    def _light(self, spans: list) -> None:
        """Re-mark the document without touching its text — every arriving word
        lit, everything else plain.

        Formatting only, so the caret stays exactly where the typist left it.
        This is what a keystroke costs; the struck-through words wait for
        :meth:`show_whole_change`, which cannot avoid rewriting.
        """
        self._layout = spans
        with self._own_write():
            _unmark(self._edit)
            cursor = QTextCursor(self._edit.document())
            cursor.setPosition(0)
            for kind, piece in spans:
                end = cursor.position() + len(piece)
                if kind == ADDED:
                    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                    cursor.mergeCharFormat(diff_text.added_format())
                cursor.setPosition(end)
            diff_text.hold_value(self._edit, None)

    def show_whole_change(self) -> None:
        """Put the words that left back into the field, struck through beside the
        ones that arrived. What a settled field shows."""
        self._settle.stop()
        self._redraw.stop()
        caret = self._prompt_offset(self._edit.textCursor().position())
        spans = diff_spans(self._baseline, self._value)
        if any(kind == REMOVED for kind, _piece in spans):
            self._paint(spans, caret)
        else:
            self._light(spans)  # nothing left: the document already reads right

    def _show_prompt_only(self) -> None:
        """The field as the prompt alone, arriving words still lit — what it is
        while being typed in."""
        spans = [span for span in diff_spans(self._baseline, self._value)
                 if span[0] != REMOVED]
        if self._edit.toPlainText() == self._value:
            self._light(spans)  # already the prompt: mark it, don't rewrite it
        else:
            self._paint(spans, self._prompt_caret)

    # --- what the typist does -----------------------------------------------

    def _on_contents_change(self, position: int, removed: int, added: int) -> None:
        """Follow one edit of the document through to the prompt under it.

        The document may hold struck-through words at this point, so where the
        edit landed in it is not where it landed in the prompt — which is why
        this works off the reported offsets and the spans the document was last
        spelled out of, rather than off what the field now says.
        """
        if self._writing:
            return
        inserted = self._edit.toPlainText()[position:position + added]
        if not self._settle.isActive():  # the first keystroke of a burst
            self._history.took(self._value)
        start = self._prompt_offset(position)
        end = self._prompt_offset(position + removed)
        self._value = self._value[:start] + inserted + self._value[end:]
        self._layout = _spliced(self._layout, position, removed, inserted)
        diff_text.hold_value(self._edit,
                             None if self._edit.toPlainText() == self._value else self._value)
        self._prompt_caret = start + len(inserted)
        self._redraw.start()
        self._settle.start()  # ...and the strikes come back once the typing stops

    def take(self, value: str) -> None:
        self._history.took(self._value)
        self._show_whole(value)

    def _show_whole(self, value: str) -> None:
        self._value = value
        self._settle.stop()
        self._redraw.stop()
        self._paint(diff_spans(self._baseline, value), len(value))

    def eventFilter(self, obj, event):
        # Leaving the field ends the typing, whatever the clock still says.
        if event.type() == QEvent.Type.FocusOut:
            self.show_whole_change()
        return False


def track(edit: QPlainTextEdit, baseline: str) -> None:
    """Start showing ``edit`` as a rewrite of ``baseline``.

    Nothing is marked yet — a prompt is not a change to itself — and everything
    typed from here on is.
    """
    untrack(edit)
    _Tracker(edit, baseline).show_whole_change()


def write(edit: QPlainTextEdit, value: str) -> None:
    trackers = edit.findChildren(_Tracker)
    if trackers:
        trackers[0].take(value)
    else:
        diff_text.forget(edit)
        edit.setPlainText(value)


def untrack(edit: QPlainTextEdit) -> None:
    """Stop tracking ``edit`` and leave it an ordinary field holding its prompt."""
    for tracker in edit.findChildren(_Tracker):
        tracker.detach()
    diff_text.clear_diff(edit)
    _unmark(edit)
    # ...and off whatever is typed or written into it next, which would otherwise
    # take the format that was under the caret when the marks came off.
    edit.setCurrentCharFormat(_plain_format())

