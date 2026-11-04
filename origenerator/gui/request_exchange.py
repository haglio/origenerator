from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget
from shared_ui.colors import BLUE_LIGHT, TEXT_PRIMARY
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD

from origenerator.db_requests import Turn
from origenerator.gui.diff_text import request_change_html

_ASK = "What to change, e.g. two women"
_NOTHING_TO_ASK_OF = "Pick an image to ask a change of"
_UPDATING = "updating…"
_FAILED = "couldn't work that into the prompts"
_LINES_AT_MOST = 20


def _worded(color) -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {color.name()}")
    return label


def _say(label: QLabel, words: str) -> None:
    label.setText(words)
    label.setVisible(bool(words))


def _column_without_margins(host: QWidget) -> QVBoxLayout:
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    return column


def _scrolling(box: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(box)
    bar = scroll.verticalScrollBar()
    bar.rangeChanged.connect(lambda _low, high: bar.setValue(high))
    scroll.hide()
    return scroll


class _Turn(QWidget):
    def __init__(self, turn, parent=None):
        super().__init__(parent)
        column = _column_without_margins(self)
        column.setSpacing(0)
        self.said = _worded(BLUE_LIGHT)
        self.said.setText(turn[0])
        self.answered = _worded(TEXT_PRIMARY)
        column.addWidget(self.said)
        step = QHBoxLayout()
        step.setContentsMargins(MARGIN_STANDARD, 0, 0, 0)
        step.addWidget(self.answered)
        column.addLayout(step)
        self.take(turn)

    def take(self, turn) -> None:
        _say(self.answered, turn[1])
        turn = Turn(*turn)
        change = (turn.old_positive, turn.old_negative, turn.new_positive, turn.new_negative)
        settings = turn.changes()
        self.setToolTip(request_change_html(*change, settings=settings)
                        if any(change) or settings else "")


class RequestExchange(QWidget):
    asked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = _column_without_margins(self)
        column.setSpacing(GAP_SMALL)
        box = QWidget()
        turns = _column_without_margins(box)
        turns.setSpacing(GAP_SMALL)
        turns.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._turns = turns
        self._scroll = _scrolling(box)
        column.addWidget(self._scroll)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit()
        line.setPlaceholderText(_ASK)
        line.returnPressed.connect(self._ask)
        self._line = line
        self._status = QLabel()
        self._status.hide()
        row.addWidget(line, 1)
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
        entry = _Turn(turn)
        self._turns.addWidget(entry)
        entry.show()
        self._fit()

    def _take_off(self, entry: _Turn) -> None:
        self._turns.removeWidget(entry)
        entry.deleteLater()
        self._fit()

    def _fit(self) -> None:
        self._turns.invalidate()
        wanted = self._turns.totalHeightForWidth(self.width())
        self._scroll.setVisible(self._turns.count() > 0)
        self._scroll.setFixedHeight(min(wanted, self.fontMetrics().lineSpacing() * _LINES_AT_MOST))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._turns.count():
            self._fit()

    def _settle(self, status: str = "", *, ready: bool = True) -> None:
        _say(self._status, status)
        self._line.setEnabled(self._available and ready)

    def show_exchange(self, turns) -> None:
        for entry in self._entries():
            self._take_off(entry)
        for turn in turns:
            self._add(turn)
        self._settle()

    def add_turn(self, said: str) -> None:
        self._add((said, ""))
        self._settle(_UPDATING, ready=False)

    def answered(self, turn) -> None:
        self._entries()[-1].take(turn)
        self._fit()
        self._settle()

    def failed(self) -> None:
        self._take_off(self._entries()[-1])
        self._settle(_FAILED)

    def set_available(self, available: bool) -> None:
        self._available = available
        if not available:
            self.show_exchange([])
        self._settle()
        self._line.setPlaceholderText(_ASK if available else _NOTHING_TO_ASK_OF)
