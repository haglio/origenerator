from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QBrush, QKeySequence, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QPlainTextEdit

from origenerator.gui import diff_text
from origenerator.prompt_diff import ADDED, REMOVED, SAME, diff_spans

SETTLE_MS = 150

_BACK = (QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveOperation.PreviousWord)
_ON = (QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveOperation.NextWord)
_MOVES = {Qt.Key.Key_Left: _BACK, Qt.Key.Key_Right: _ON}
_ERASES = {Qt.Key.Key_Backspace: _BACK, Qt.Key.Key_Delete: _ON}


def _plain_format() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontStrikeOut(False)
    fmt.setBackground(QBrush(Qt.BrushStyle.NoBrush))
    fmt.setForeground(QBrush(Qt.BrushStyle.NoBrush))
    return fmt


def _unmark(edit: QPlainTextEdit) -> None:
    # Qt: a field writes new text in the format under the caret, so a document replaced while a word was lit comes back lit
    cursor = QTextCursor(edit.document())
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeCharFormat(_plain_format())


def _spliced(layout: list, position: int, removed: int, inserted: str) -> list:
    before, after, doc = [], [], 0
    for kind, text in layout:
        before.append((kind, text[:max(0, position - doc)]))
        after.append((kind, text[max(0, position + removed - doc):]))
        doc += len(text)
    return [(kind, text) for kind, text in [*before, (ADDED, inserted), *after] if text]


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

    def clear(self) -> None:
        self._undone.clear()
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
                # Accepted at the ShortcutOverride so Qt gives the key to the field and not to a window-wide Undo shortcut.
                event.accept()
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
    def __init__(self, edit: QPlainTextEdit, baseline: str, undo: bool):
        super().__init__(edit)
        self._edit = edit
        self._baseline = baseline
        self._value = edit.toPlainText()
        self._layout: list = [(SAME, self._value)] if self._value else []
        self._writing = False
        self._history = (UndoHistory(self, lambda: self._value, self._show_whole) if undo
                         else None)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.show_whole_change)
        self._prompt_caret = 0
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.timeout.connect(self._show_prompt_only)
        edit.setUndoRedoEnabled(False)
        edit.installEventFilter(self)
        if self._history is not None:
            self._history.watch(edit)
        edit.document().contentsChange.connect(self._on_contents_change)
        edit.cursorPositionChanged.connect(self._keep_caret_off_struck_words)

    def detach(self) -> None:
        self._settle.stop()
        self._redraw.stop()
        self._edit.removeEventFilter(self)
        if self._history is not None:
            self._history.unwatch(self._edit)
        self._edit.document().contentsChange.disconnect(self._on_contents_change)
        self._edit.cursorPositionChanged.disconnect(self._keep_caret_off_struck_words)
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

    def prompt_offset(self, doc_offset: int) -> int:
        doc = prompt = 0
        for kind, text in self._layout:
            if doc + len(text) >= doc_offset:
                return prompt if kind == REMOVED else prompt + (doc_offset - doc)
            doc += len(text)
            if kind != REMOVED:
                prompt += len(text)
        return prompt

    def document_offset(self, prompt_offset: int) -> int:
        doc = prompt = 0
        for kind, text in self._layout:
            if kind != REMOVED:
                if prompt + len(text) >= prompt_offset:
                    return doc + (prompt_offset - prompt)
                prompt += len(text)
            doc += len(text)
        return doc

    def prompt_ranges_from(self, prompt_offset: int) -> list[tuple[int, int]]:
        ranges, doc, prompt = [], 0, 0
        for kind, text in self._layout:
            if kind != REMOVED:
                start = max(prompt_offset - prompt, 0)
                if start < len(text):
                    ranges.append((doc + start, doc + len(text)))
                prompt += len(text)
            doc += len(text)
        return ranges

    def _paint(self, spans: list, caret: int) -> None:
        self._layout = spans
        text = "".join(piece for _kind, piece in spans)
        with self._own_write():
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
                    cursor.mergeCharFormat(diff_text.format_for(kind))
                cursor.setPosition(end)
            place = QTextCursor(self._edit.document())
            place.setPosition(min(self.document_offset(caret), len(text)))
            self._edit.setTextCursor(place)

    def _light(self, spans: list) -> None:
        self._layout = spans
        with self._own_write():
            _unmark(self._edit)
            cursor = QTextCursor(self._edit.document())
            cursor.setPosition(0)
            for kind, piece in spans:
                end = cursor.position() + len(piece)
                if kind == ADDED:
                    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                    cursor.mergeCharFormat(diff_text.format_for(kind))
                cursor.setPosition(end)
            diff_text.hold_value(self._edit, None)

    def show_whole_change(self) -> None:
        self._settle.stop()
        self._redraw.stop()
        caret = self.prompt_offset(self._edit.textCursor().position())
        spans = diff_spans(self._baseline, self._value)
        if (any(kind == REMOVED for kind, _piece in spans)
                or self._edit.toPlainText() != self._value):
            self._paint(spans, caret)
        else:
            self._light(spans)

    def measure_against(self, baseline: str) -> None:
        self._baseline = baseline
        self.show_whole_change()

    def _show_prompt_only(self) -> None:
        spans = [span for span in diff_spans(self._baseline, self._value)
                 if span[0] != REMOVED]
        if self._edit.toPlainText() == self._value:
            self._light(spans)
        else:
            self._paint(spans, self._prompt_caret)

    def _on_contents_change(self, position: int, removed: int, added: int) -> None:
        # Qt: a struck-through line break does not report itself as struck.
        if self._writing:
            return
        inserted = self._edit.toPlainText()[position:position + added]
        if self._history is not None and not self._settle.isActive():
            self._history.took(self._value)
        start = self.prompt_offset(position)
        end = self.prompt_offset(position + removed)
        self._value = self._value[:start] + inserted + self._value[end:]
        self._layout = _spliced(self._layout, position, removed, inserted)
        diff_text.hold_value(self._edit,
                             None if self._edit.toPlainText() == self._value else self._value)
        self._prompt_caret = start + len(inserted)
        self._redraw.start()
        self._settle.start()

    def take(self, value: str) -> None:
        if self._history is not None:
            self._history.took(self._value)
        self._show_whole(value)

    def _show_whole(self, value: str) -> None:
        self._value = value
        self._settle.stop()
        self._redraw.stop()
        self._paint(diff_spans(self._baseline, value), len(value))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusOut:
            self.show_whole_change()
        return event.type() == QEvent.Type.KeyPress and self._key_kept_off_struck_words(event)

    def _key_kept_off_struck_words(self, event) -> bool:
        if not any(kind == REMOVED for kind, _piece in self._layout):
            return False
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        mode = QTextCursor.MoveMode.KeepAnchor if shift else QTextCursor.MoveMode.MoveAnchor
        selected = self._edit.textCursor().hasSelection()
        if event.key() in _MOVES and (shift or ctrl or not selected):
            self._move_through_prompt(_MOVES[event.key()][ctrl], mode)
            return True
        if event.key() in _ERASES and not shift and not selected:
            self._erase_through_prompt(_ERASES[event.key()][ctrl])
            return True
        return event.key() == Qt.Key.Key_Down and not ctrl and self._down_past_struck_lines(mode)

    def _along_prompt(self, offset: int, move: QTextCursor.MoveOperation) -> int:
        prompt = QTextDocument(self._value)
        cursor = QTextCursor(prompt)
        cursor.setPosition(offset)
        cursor.movePosition(move)
        return cursor.position()

    def _move_through_prompt(self, move: QTextCursor.MoveOperation,
                             mode: QTextCursor.MoveMode) -> None:
        cursor = self._edit.textCursor()
        here = self.prompt_offset(cursor.position())
        there = self._along_prompt(here, move)
        if there != here:
            cursor.setPosition(self.document_offset(there), mode)
            self._edit.setTextCursor(cursor)

    def _erase_through_prompt(self, move: QTextCursor.MoveOperation) -> None:
        here = self.prompt_offset(self._edit.textCursor().position())
        there = self._along_prompt(here, move)
        if there != here:
            cursor = QTextCursor(self._edit.document())
            cursor.setPosition(self.document_offset(here))
            cursor.setPosition(self.document_offset(there), QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()

    def _down_past_struck_lines(self, mode: QTextCursor.MoveMode) -> bool:
        cursor = self._edit.textCursor()
        here = self.prompt_offset(cursor.position())
        if (not cursor.movePosition(QTextCursor.MoveOperation.Down, mode)
                or self.prompt_offset(cursor.position()) != here):
            return False
        while (self.prompt_offset(cursor.position()) == here
               and cursor.movePosition(QTextCursor.MoveOperation.Down, mode)):
            pass
        if self.prompt_offset(cursor.position()) == here:
            cursor.setPosition(self.document_offset(self._along_prompt(here, _ON[0])), mode)
        self._edit.setTextCursor(cursor)
        return True

    def _keep_caret_off_struck_words(self) -> None:
        if self._writing:
            return
        cursor = self._edit.textCursor()
        here = self.prompt_offset(cursor.position())
        place = self.document_offset(here)
        if cursor.hasSelection() and self.prompt_offset(cursor.anchor()) == here:
            cursor.setPosition(place)
        elif cursor.position() != place:
            cursor.setPosition(place, QTextCursor.MoveMode.KeepAnchor if cursor.hasSelection()
                               else QTextCursor.MoveMode.MoveAnchor)
        else:
            return
        self._edit.setTextCursor(cursor)


def _tracker_of(edit: QPlainTextEdit) -> _Tracker | None:
    return next(iter(edit.findChildren(_Tracker)), None)


def track(edit: QPlainTextEdit, baseline: str, *, undo: bool = True) -> None:
    tracker = _tracker_of(edit)
    if tracker is not None:
        tracker.measure_against(baseline)
    else:
        _Tracker(edit, baseline, undo).show_whole_change()


def write_undoably(edit: QPlainTextEdit, value: str) -> None:
    tracker = _tracker_of(edit)
    if tracker is not None:
        tracker.take(value)
        return
    whole = QTextCursor(edit.document())
    whole.select(QTextCursor.SelectionType.Document)
    whole.insertText(value)


def write(edit: QPlainTextEdit, value: str) -> None:
    tracker = _tracker_of(edit)
    if tracker is not None:
        tracker.take(value)
    else:
        diff_text.forget(edit)
        edit.setPlainText(value)


def caret_in_prompt(edit: QPlainTextEdit) -> int:
    position = edit.textCursor().position()
    tracker = _tracker_of(edit)
    return tracker.prompt_offset(position) if tracker is not None else position


def prompt_ranges_from(edit: QPlainTextEdit, offset: int) -> list[tuple[int, int]]:
    tracker = _tracker_of(edit)
    if tracker is None:
        return [(offset, len(edit.toPlainText()))]
    return tracker.prompt_ranges_from(offset)


def put_caret_in_prompt(edit: QPlainTextEdit, offset: int) -> None:
    tracker = _tracker_of(edit)
    position = tracker.document_offset(offset) if tracker is not None else offset
    cursor = QTextCursor(edit.document())
    cursor.setPosition(min(position, len(edit.toPlainText())))
    edit.setTextCursor(cursor)


def untrack(edit: QPlainTextEdit) -> None:
    caret = caret_in_prompt(edit)
    for tracker in edit.findChildren(_Tracker):
        tracker.detach()
    diff_text.clear_diff(edit)
    put_caret_in_prompt(edit, caret)
    _unmark(edit)
    # Qt: text written into a field takes the format under the caret, so reset it
    edit.setCurrentCharFormat(_plain_format())

