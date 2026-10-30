from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from shared_ui.colors import AMBER, RED
from shared_ui.spacing import GAP_SMALL

from origenerator.gui import diff_text, tracked_prompt
from origenerator.gui.prompt_field import PromptField, PromptHeights
from origenerator.gui.unread_words import gray_past
from origenerator.prompt_tokens import PromptReading

COUNTING_DOWN_FROM = 15


class Countdown(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
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

    def __init__(self, key: str, parent=None, *, heights: PromptHeights | None = None):
        super().__init__(parent)
        self._reading: PromptReading | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        self._box = PromptField(key, heights=heights)
        self._countdown = Countdown()
        column.addWidget(self._box)
        column.addWidget(self._countdown)
        self._box.textChanged.connect(self._count_down)
        self._box.textChanged.connect(self.textChanged)

    def boxes(self) -> list[PromptField]:
        return [self._box]

    def value(self) -> str:
        return diff_text.live_text(self._box)

    def set_value(self, value: str) -> None:
        tracked_prompt.write(self._box, value)

    def set_reading(self, reading: PromptReading | None) -> None:
        if reading != self._reading:
            self._reading = reading
            self._count_down()

    def track(self, baseline: str) -> None:
        tracked_prompt.track(self._box, baseline)

    def _count_down(self) -> None:
        count_down(self._countdown, self._box, self._reading)


def set_in_use(field: QPlainTextEdit | PromptBoxes, label: QLabel, unused_because: str | None,
               help_text: str) -> None:
    typed_into = field.boxes() if isinstance(field, PromptBoxes) else [field]
    for widget in (*typed_into, label):
        _mark_inert(widget, bool(unused_because))
        widget.setToolTip(unused_because or help_text)
    for box in typed_into:
        box.setReadOnly(bool(unused_because))


def _mark_inert(widget, inert: bool) -> None:
    if widget.property("inert") == inert:
        return
    widget.setProperty("inert", inert)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
