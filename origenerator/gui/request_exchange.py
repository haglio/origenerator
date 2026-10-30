"""The Request section: the exchange so far about the item on display, oldest
first, and the line the next request is typed in and sent with Enter."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget
from shared_ui.colors import TEXT_PRIMARY, TEXT_SECONDARY
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.diff_text import request_change_html

_ASK = "What to change, e.g. two women"
_NOTHING_TO_ASK_OF = "Pick an image to ask a change of"
_UPDATING = "updating…"
_FAILED = "couldn't work that into the prompts"
_LINES_IN_VIEW = 6


class _Turn(QWidget):
    def __init__(self, turn, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.said = QLabel(turn[0])
        self.said.setWordWrap(True)
        self.said.setStyleSheet(f"color: {TEXT_PRIMARY.name()}")
        self.answered = QLabel()
        self.answered.setWordWrap(True)
        self.answered.setStyleSheet(f"color: {TEXT_SECONDARY.name()}")
        column.addWidget(self.said)
        column.addWidget(self.answered)
        self.take(turn)

    def take(self, turn) -> None:
        self.answered.setText(turn[1])
        self.answered.setVisible(bool(turn[1]))
        change = tuple(turn[2:6])
        self.setToolTip(request_change_html(*change) if any(change) else "")


class RequestExchange(QWidget):
    asked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        self._turns_box = QWidget()
        self._turns = QVBoxLayout(self._turns_box)
        self._turns.setContentsMargins(0, 0, 0, 0)
        self._turns.setSpacing(GAP_SMALL)
        self._turns.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._turns_box)
        self._scroll.setMaximumHeight(self.fontMetrics().lineSpacing() * _LINES_IN_VIEW)
        self._scroll.verticalScrollBar().rangeChanged.connect(
            lambda _low, high: self._scroll.verticalScrollBar().setValue(high))
        self._scroll.hide()
        column.addWidget(self._scroll)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._line = QLineEdit()
        self._line.setPlaceholderText(_ASK)
        self._line.returnPressed.connect(self._ask)
        self._status = QLabel()
        self._status.hide()
        row.addWidget(self._line, 1)
        row.addWidget(self._status)
        column.addLayout(row)
        self._available = True

    def _ask(self) -> None:
        words = self._line.text().strip()
        if words:
            self._line.clear()
            self.asked.emit(words)

    def _entries(self) -> list[_Turn]:
        return [self._turns.itemAt(i).widget() for i in range(self._turns.count())]

    def turns(self) -> list[tuple[str, str]]:
        return [(entry.said.text(), entry.answered.text()) for entry in self._entries()]

    def _add(self, turn) -> None:
        self._turns.addWidget(_Turn(turn))
        self._scroll.show()

    def show_exchange(self, turns) -> None:
        for entry in self._entries():
            self._turns.removeWidget(entry)
            entry.deleteLater()
        self._scroll.hide()
        for turn in turns:
            self._add(turn)
        self._status.hide()
        self._line.setEnabled(self._available)

    def add_turn(self, said: str) -> None:
        self._add((said, ""))
        self._status.setText(_UPDATING)
        self._status.show()
        self._line.setEnabled(False)

    def answered(self, turn) -> None:
        self._entries()[-1].take(turn)
        self._status.hide()
        self._line.setEnabled(self._available)

    def failed(self) -> None:
        last = self._entries()[-1]
        self._turns.removeWidget(last)
        last.deleteLater()
        self._scroll.setVisible(self._turns.count() > 0)
        self._status.setText(_FAILED)
        self._status.show()
        self._line.setEnabled(self._available)

    def set_available(self, available: bool) -> None:
        self._available = available
        if not available:
            self.show_exchange([])
        self._line.setEnabled(available)
        self._line.setPlaceholderText(_ASK if available else _NOTHING_TO_ASK_OF)
