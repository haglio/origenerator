from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from shared_ui.colors import AMBER, RED
from shared_ui.fonts import SIZE_BODY, make_font
from shared_ui.spacing import GAP_SMALL

from origenerator.box_breaks import (
    BOX_BREAK,
    baselines_for,
    cut_into_boxes,
    prompt_boxes,
    unboxed,
)
from origenerator.gui import diff_text, tracked_prompt
from origenerator.gui.unread_words import gray_past
from origenerator.prompt_tokens import READ_IN_PIECES, PromptReading

COUNTING_DOWN_FROM = 15


class Countdown(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(make_font(size=SIZE_BODY))
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.hide()

    def show_left(self, left: int | None) -> None:
        if left is None or left > COUNTING_DOWN_FROM:
            self.hide()
            return
        self.setText(f"{left} left")
        self.setStyleSheet(f"color: {(AMBER if left >= 0 else RED).name()};")
        self.show()


def count_down(countdown: Countdown, field: QPlainTextEdit, reading: PromptReading | None) -> None:
    text = diff_text.live_text(field)
    countdown.show_left(None if reading is None else reading.reads_well - reading.tokens(text))
    gray_past(field, None if reading is None else reading.stops_at(text))


class PromptBoxes(QWidget):
    textChanged = pyqtSignal()
    boxes_changed = pyqtSignal()

    def __init__(self, make_box: Callable[[], QPlainTextEdit], parent=None):
        super().__init__(parent)
        self._make_box = make_box
        self._reading: PromptReading | None = None
        self._texts: list[str] = []
        self._as_made = True
        self._cut_from: str | None = None
        self._baseline: str | None = None
        self._shares: list[str | None] = []
        self._in_use: tuple[bool, str] | None = None
        self._writing = False
        self._flow_from: int | None = None
        self._boxes: list[QPlainTextEdit] = []
        self._countdowns: list[Countdown] = []
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(GAP_SMALL)
        self._column.addStretch()
        self._history = tracked_prompt.UndoHistory(self, self.value, self._restore)
        self._burst = QTimer(self)
        self._burst.setSingleShot(True)
        self._burst.setInterval(tracked_prompt.SETTLE_MS)
        self._reflow = QTimer(self)
        self._reflow.setSingleShot(True)
        self._reflow.timeout.connect(self._flow_the_edit)
        self._show([""])
        self.setFocusProxy(self._boxes[0])

    def boxes(self) -> list[QPlainTextEdit]:
        return list(self._boxes)

    def value(self) -> str:
        return self._cut_from if self._cut_from is not None else BOX_BREAK.join(self._texts)

    def set_value(self, value: str) -> None:
        self._take(value, as_made=True)

    def carry(self, value: str) -> None:
        self._take(value, as_made=False)

    def rewrite(self, change: Callable[[str], str]) -> None:
        self.edit(change(BOX_BREAK.join(self._texts)))

    def edit(self, value: str) -> None:
        self._history.took(self.value())
        self._burst.stop()
        self._as_made = False
        self._show_value(value)
        self.textChanged.emit()

    def set_reading(self, reading: PromptReading | None) -> None:
        if reading != self._reading:
            self._reading = reading
            if not self._reflow.isActive():
                self._show_value(self.value())

    def _take(self, value: str, *, as_made: bool) -> None:
        if self._baseline is None:
            self._history.clear()
        else:
            self._history.took(self.value())
        self._as_made = as_made
        self._show_value(value)
        self.textChanged.emit()

    def _show_value(self, value: str) -> None:
        if self._as_made:
            self._show_stored(value)
            return
        self._reflow.stop()
        self._flow_from = None
        self._cut_from = None
        self._show(prompt_boxes(value) if self._reading is None
                   else self._reading.boxes_of(value))

    def track(self, baseline: str) -> None:
        self._baseline = baseline
        self._history.clear()
        self._show(self._texts)

    def untrack(self) -> None:
        self._baseline = None
        self._show(self._texts)

    def set_in_use(self, in_use: bool, tip: str) -> None:
        self._in_use = (in_use, tip)
        for box in self._boxes:
            _mark_in_use(box, in_use, tip)

    def _flows(self) -> bool:
        return self._reading is not None and self._reading.past_it == READ_IN_PIECES

    def _one_box(self) -> bool:
        return self._reading is not None and self._reading.past_it != READ_IN_PIECES

    def _show_stored(self, value: str) -> None:
        self._reflow.stop()
        self._flow_from = None
        texts, self._cut_from = prompt_boxes(value), None
        if self._one_box():
            texts = [unboxed(value)]
        elif self._flows() and len(texts) == 1:
            starts = [start for start, _tokens in self._reading.pieces(value)]
            if len(starts) > 1:
                texts, self._cut_from = cut_into_boxes(value, starts), value
        self._show(texts)

    def _show(self, texts: list[str]) -> None:
        count = len(self._boxes)
        self._writing = True
        try:
            while len(self._boxes) < len(texts):
                self._add_box()
            while len(self._boxes) > len(texts):
                self._remove_last_box()
            shares = (baselines_for(self._baseline, texts, self._cut_from)
                      if self._baseline is not None else [None] * len(texts))
            for index, (box, text, share) in enumerate(zip(self._boxes, texts, shares)):
                if (diff_text.live_text(box), self._shares[index]) != (text, share):
                    _put(box, text, share)
                    self._shares[index] = share
        finally:
            self._writing = False
        self._texts = list(texts)
        self._count_down()
        if len(self._boxes) != count:
            self.boxes_changed.emit()

    def _add_box(self) -> None:
        box = self._make_box()
        box.setUndoRedoEnabled(False)
        self._history.watch(box)
        box.textChanged.connect(lambda box=box: self._edited(box))
        countdown = Countdown()
        self._column.insertWidget(self._column.count() - 1, box, 1)
        self._column.insertWidget(self._column.count() - 1, countdown)
        self._boxes.append(box)
        self._countdowns.append(countdown)
        self._shares.append(None)
        if self._in_use is not None:
            _mark_in_use(box, *self._in_use)

    def _remove_last_box(self) -> None:
        box, countdown = self._boxes.pop(), self._countdowns.pop()
        self._shares.pop()
        tracked_prompt.untrack(box)
        self._history.unwatch(box)
        for widget in (box, countdown):
            self._column.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

    def _edited(self, box: QPlainTextEdit) -> None:
        if self._writing or box not in self._boxes:
            return
        texts = [diff_text.live_text(each) for each in self._boxes]
        if texts == self._texts:
            return
        if not self._burst.isActive():
            self._history.took(self.value())
        self._burst.start()
        self._as_made, self._cut_from = False, None
        self._texts = texts
        self._count_down()
        if self._flows() or any(BOX_BREAK in text for text in texts):
            index = self._boxes.index(box)
            self._flow_from = index if self._flow_from is None else min(self._flow_from, index)
            self._reflow.start()
        self.textChanged.emit()

    def _flow_the_edit(self) -> None:
        start, self._flow_from = self._flow_from or 0, None
        focused = next((index for index, box in enumerate(self._boxes) if box.hasFocus()), None)
        at = start if focused is None else focused
        texts, caret = self._split_at_pasted_breaks(
            (at, tracked_prompt.caret_in_prompt(self._boxes[at])))
        if self._flows():
            texts, caret = self._reading.flow(texts, start=start, caret=caret)
        if texts == self._texts:
            return
        self._show(texts)
        if caret is not None:
            target = self._boxes[caret[0]]
            if focused is not None:
                target.setFocus()
            tracked_prompt.put_caret_in_prompt(target, caret[1])
        self.textChanged.emit()

    def _split_at_pasted_breaks(self, caret: tuple[int, int]
                                ) -> tuple[list[str], tuple[int, int]]:
        if self._one_box():
            return [unboxed(text) for text in self._texts], caret
        texts, at = [], caret
        for index, text in enumerate(self._texts):
            parts = prompt_boxes(text)
            if index == caret[0]:
                offset = caret[1]
                for part_index, part in enumerate(parts):
                    if offset <= len(part) or part_index == len(parts) - 1:
                        at = (len(texts) + part_index, min(offset, len(part)))
                        break
                    offset -= len(part) + 1
            texts.extend(parts)
        return texts, at

    def _restore(self, value: str) -> None:
        self._burst.stop()
        focused = next((index for index, box in enumerate(self._boxes) if box.hasFocus()), None)
        self._as_made = True
        self._show_stored(value)
        if focused is not None:
            target = self._boxes[min(focused, len(self._boxes) - 1)]
            target.setFocus()
            tracked_prompt.put_caret_in_prompt(target, len(diff_text.live_text(target)))
        self.textChanged.emit()

    def _count_down(self) -> None:
        if self._cut_from is not None:
            for countdown, (_start, tokens) in zip(self._countdowns,
                                                   self._reading.pieces(self._cut_from)):
                countdown.show_left(self._reading.reads_well - tokens)
            return
        for box, countdown in zip(self._boxes, self._countdowns):
            count_down(countdown, box, self._reading)


def _put(box: QPlainTextEdit, text: str, share: str | None) -> None:
    tracked_prompt.untrack(box)
    box.setPlainText(text)
    if share is not None:
        tracked_prompt.track(box, share, undo=False)
    box.setUndoRedoEnabled(False)


def set_in_use(field: QPlainTextEdit | PromptBoxes, label: QLabel, unused_because: str | None,
               help_text: str) -> None:
    in_use, tip = not unused_because, unused_because or help_text
    _mark_in_use(label, in_use, tip)
    if isinstance(field, PromptBoxes):
        field.set_in_use(in_use, tip)
    else:
        _mark_in_use(field, in_use, tip)


def _mark_in_use(widget: QWidget, in_use: bool, tip: str) -> None:
    if widget.property("inert") != (not in_use):
        widget.setProperty("inert", not in_use)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
    widget.setToolTip(tip)
    if isinstance(widget, QPlainTextEdit):
        widget.setReadOnly(not in_use)
