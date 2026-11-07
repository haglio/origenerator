from __future__ import annotations

from collections.abc import Callable
from math import ceil

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QImageReader,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
    QTextLength,
    QTextTableFormat,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import BLUE_LIGHT, TEXT_PRIMARY
from shared_ui.fonts import SIZE_HEADING
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD

from origenerator.db_requests import Turn
from origenerator.gui.diff_text import write_request_change
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX

_ASK = "What to change, e.g. two women"
_NOTHING_TO_ASK_OF = "Pick an image to ask a change of"
_UPDATING = "updating…"
_FAILED = "couldn't work that into the prompts"
_LINES_AT_MOST = 20
_COMPARED = THUMBNAIL_BOX * 2
_NOT_MADE = "?"


def _say(label: QLabel, words: str) -> None:
    label.setText(words)
    label.setVisible(bool(words))


def _column_without_margins(host: QWidget) -> QVBoxLayout:
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    return column


class _Entry:
    def __init__(self, turn):
        self.said = turn[0]
        self.take(turn)

    def take(self, turn) -> None:
        self.answered = turn[1]
        turn = Turn(*turn)
        self.made = turn.made
        self._change = (turn.old_positive, turn.old_negative, turn.new_positive, turn.new_negative)
        self._settings = turn.changes()
        self.tip = ""

    def compare(self, before: str, thumbnail_of: Callable[[str], str | None] | None) -> None:
        if not (any(self._change) or self._settings):
            self.tip = ""
            return
        document = QTextDocument()
        cursor = QTextCursor(document)
        if thumbnail_of is not None:
            _write_comparison(cursor, *(thumbnail_of(made) if made else None
                                        for made in (before, self.made)))
        write_request_change(cursor, *self._change, settings=self._settings)
        self.tip = document.toHtml()


def _write_comparison(cursor: QTextCursor, *thumbnails: str | None) -> None:
    shape = QTextTableFormat()
    shape.setBorder(0)
    shape.setCellSpacing(GAP_SMALL)
    shape.setColumnWidthConstraints([QTextLength(QTextLength.Type.FixedLength, _COMPARED.width())]
                                    * len(thumbnails))
    table = cursor.insertTable(1, len(thumbnails), shape)
    for column, thumbnail in enumerate(thumbnails):
        cell = table.cellAt(0, column).firstCursorPosition()
        size = QImageReader(thumbnail).size() if thumbnail else QSize()
        if size.isValid():
            fitted = size.scaled(_COMPARED, Qt.AspectRatioMode.KeepAspectRatio)
            picture = QTextImageFormat()
            picture.setName(thumbnail)
            picture.setWidth(fitted.width())
            picture.setHeight(fitted.height())
            cell.insertImage(picture)
        else:
            mark = QTextCharFormat()
            mark.setFontPointSize(SIZE_HEADING)
            mark.setFontWeight(QFont.Weight.Bold)
            cell.insertText(_NOT_MADE, mark)
    cursor.movePosition(QTextCursor.MoveOperation.End)


def _paragraph(cursor: QTextCursor, words: str, color, *, indent: int = 0, above: int = 0) -> None:
    shape = QTextBlockFormat()
    shape.setLeftMargin(indent)
    shape.setTopMargin(above)
    if cursor.document().isEmpty():
        cursor.setBlockFormat(shape)
    else:
        cursor.insertBlock(shape)
    ink = QTextCharFormat()
    ink.setForeground(color)
    cursor.insertText(words, ink)


class _Conversation(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setStyleSheet("QTextEdit { background: transparent; }")
        page = self.document()
        page.setDocumentMargin(0)
        page.documentLayout().documentSizeChanged.connect(lambda _size: self._fit())
        self._tips: list[str] = []
        self.hide()

    def show_entries(self, entries: list[_Entry]) -> None:
        self.clear()
        cursor = self.textCursor()
        self._tips = []
        for entry in entries:
            _paragraph(cursor, entry.said, BLUE_LIGHT, above=GAP_SMALL if self._tips else 0)
            self._tips.append(entry.tip)
            if entry.answered:
                _paragraph(cursor, entry.answered, TEXT_PRIMARY, indent=MARGIN_STANDARD)
                self._tips.append(entry.tip)
        self.setVisible(bool(entries))
        self._fit()

    def _fit(self) -> None:
        tallest = self.fontMetrics().lineSpacing() * _LINES_AT_MOST
        self.setFixedHeight(min(ceil(self.document().size().height()), tallest))
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def tip_at(self, place: QPoint) -> str:
        block = self.cursorForPosition(place).blockNumber()
        return self._tips[block] if block < len(self._tips) else ""

    def viewportEvent(self, event) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return super().viewportEvent(event)
        tip = self.tip_at(event.pos())
        if tip:
            QToolTip.showText(event.globalPos(), tip, self.viewport())
        else:
            QToolTip.hideText()
        return True


class RequestExchange(QWidget):
    asked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = _column_without_margins(self)
        column.setSpacing(GAP_SMALL)
        self._conversation = _Conversation()
        self._held: list[_Entry] = []
        self._started_on: str | None = None
        self._thumbnail_of: Callable[[str], str | None] | None = None
        column.addWidget(self._conversation)
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

    def _entries(self) -> list[_Entry]:
        return self._held

    def turns(self) -> list[tuple[str, str]]:
        return [(entry.said, entry.answered) for entry in self._held]

    def set_thumbnail_of(self, thumbnail_of: Callable[[str], str | None]) -> None:
        self._thumbnail_of = thumbnail_of

    def _draw(self) -> None:
        before = self._started_on or ""
        for entry in self._held:
            entry.compare(before, self._thumbnail_of)
            before = entry.made
        self._conversation.show_entries(self._held)

    def _settle(self, status: str = "", *, ready: bool = True) -> None:
        _say(self._status, status)
        self._line.setEnabled(self._available and ready)

    def show_exchange(self, turns, *, started_on: str | None = None) -> None:
        self._held = [_Entry(turn) for turn in turns]
        self._started_on = started_on
        self._draw()
        self._settle()

    def add_turn(self, said: str) -> None:
        self._held.append(_Entry((said, "")))
        self._draw()
        self._settle(_UPDATING, ready=False)

    def answered(self, turn) -> None:
        self._held[-1].take(turn)
        self._draw()
        self._settle()

    def failed(self) -> None:
        self._held.pop()
        self._draw()
        self._settle(_FAILED)

    def set_available(self, available: bool) -> None:
        self._available = available
        if not available:
            self.show_exchange([])
        self._settle()
        self._line.setPlaceholderText(_ASK if available else _NOTHING_TO_ASK_OF)
