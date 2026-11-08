from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QImage,
    QImageReader,
    QPainter,
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
from shared_ui.colors import BG_TERTIARY, BLUE_LIGHT, TEXT_PRIMARY, TEXT_SECONDARY
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD
from shared_ui.toggle_switch import ToggleSwitch

from origenerator import config
from origenerator.db_requests import Turn
from origenerator.gui.diff_text import write_request_change
from origenerator.gui.generate_button import GenerateButton
from origenerator.gui.inflight import RunReading
from origenerator.gui.progress_bar import BAR_HEIGHT, ProgressBar
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX

_ASK = "What to change, e.g. two women"
_NOTHING_TO_ASK_OF = "Pick an image to ask a change of"
_UPDATING = "updating…"
_FAILED = "couldn't work that into the prompts"
_LINES_AT_MOST = 20
_COMPARED = THUMBNAIL_BOX * 2
_NOT_MADE = "?"
_THUMBNAIL_LINES = 2
_MARK_SHARE = 0.7
_AUTO_GENERATE = "Auto-generate"
_AUTO_GENERATE_TIP = "Generate each time the model comes back with its changes"


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

    def changed_something(self) -> bool:
        return any(self._change) or bool(self._settings)

    def compare(self, before: str, thumbnail_of: Callable[[str], str | None] | None) -> None:
        if not self.changed_something():
            self.tip = ""
            return
        document = QTextDocument()
        cursor = QTextCursor(document)
        if thumbnail_of is not None:
            _write_comparison(cursor, *(thumbnail_of(made) if made else None
                                        for made in (before, self.made)))
        write_request_change(cursor, *self._change, settings=self._settings)
        self.tip = document.toHtml()


def _fitted(thumbnail: str | None, box: QSize) -> QTextImageFormat | None:
    size = QImageReader(thumbnail).size() if thumbnail else QSize()
    if not size.isValid():
        return None
    fitted = size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio)
    picture = QTextImageFormat()
    picture.setName(thumbnail)
    picture.setWidth(fitted.width())
    picture.setHeight(fitted.height())
    return picture


def _write_comparison(cursor: QTextCursor, *thumbnails: str | None) -> None:
    shape = QTextTableFormat()
    shape.setBorder(0)
    shape.setCellSpacing(GAP_SMALL)
    shape.setColumnWidthConstraints([QTextLength(QTextLength.Type.FixedLength, _COMPARED.width())]
                                    * len(thumbnails))
    table = cursor.insertTable(1, len(thumbnails), shape)
    pictures = [_fitted(thumbnail, _COMPARED) for thumbnail in thumbnails]
    made = next((picture for picture in pictures if picture is not None), None)
    size = (QSize(round(made.width()), round(made.height())) if made is not None
            else _COMPARED)
    for column, picture in enumerate(pictures):
        cell = table.cellAt(0, column).firstCursorPosition()
        cell.insertImage(picture if picture is not None else _not_made(size))
    cursor.movePosition(QTextCursor.MoveOperation.End)


def _not_made(size: QSize) -> QTextImageFormat:
    path = config.STATE_DIR / "not made" / f"not made {size.width()}x{size.height()}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        stand_in = QImage(size, QImage.Format.Format_RGB32)
        stand_in.fill(BG_TERTIARY)
        painter = QPainter(stand_in)
        font = QFont()
        font.setPixelSize(round(min(size.width(), size.height()) * _MARK_SHARE))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(TEXT_SECONDARY)
        painter.drawText(stand_in.rect(), Qt.AlignmentFlag.AlignCenter, _NOT_MADE)
        painter.end()
        stand_in.save(str(path))
    picture = QTextImageFormat()
    picture.setName(str(path))
    picture.setWidth(size.width())
    picture.setHeight(size.height())
    return picture


def _block(cursor: QTextCursor, *, indent: int = 0, above: int = 0) -> None:
    shape = QTextBlockFormat()
    shape.setLeftMargin(indent)
    shape.setTopMargin(above)
    if cursor.document().isEmpty():
        cursor.setBlockFormat(shape)
    else:
        cursor.insertBlock(shape)


def _paragraph(cursor: QTextCursor, words: str, color, *, indent: int = 0, above: int = 0) -> None:
    _block(cursor, indent=indent, above=above)
    ink = QTextCharFormat()
    ink.setForeground(color)
    cursor.insertText(words, ink)


@dataclass(frozen=True)
class _Made:
    thumbnail: str | None = None
    reading: RunReading | None = None


class _Conversation(QTextEdit):
    generate_asked = pyqtSignal(int)

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
        self.verticalScrollBar().valueChanged.connect(lambda _value: self._place())
        self._tips: list[str] = []
        self._placed: list[tuple[QWidget, int]] = []
        self.hide()

    def show_entries(self, entries: list[_Entry], made: list[_Made]) -> None:
        for widget, _block_number in self._placed:
            widget.hide()
            widget.deleteLater()
        self._placed = []
        self.clear()
        cursor = self.textCursor()
        self._tips = []
        for index, entry in enumerate(entries):
            _paragraph(cursor, entry.said, BLUE_LIGHT, above=GAP_SMALL if self._tips else 0)
            self._tips.append(entry.tip)
            if entry.answered:
                _paragraph(cursor, entry.answered, TEXT_PRIMARY, indent=MARGIN_STANDARD)
                self._tips.append(entry.tip)
            self._show_what_was_made(cursor, index, entry, made[index])
        self.setVisible(bool(entries))
        self._fit()

    def _show_what_was_made(self, cursor: QTextCursor, index: int, entry: _Entry,
                            made: _Made) -> None:
        if made.reading is not None:
            bar = ProgressBar(self.viewport())
            bar.setFixedHeight(BAR_HEIGHT)
            bar.show_progress(made.reading.caption(), *made.reading.bars())
            self._reserve(cursor, bar, entry)
        elif entry.made:
            picture = _fitted(made.thumbnail, self._thumbnail_box())
            if picture is not None:
                _block(cursor, indent=MARGIN_STANDARD, above=GAP_SMALL)
                cursor.insertImage(picture)
                self._tips.append(entry.tip)
        elif entry.changed_something():
            button = GenerateButton(self.viewport())
            button.clicked.connect(lambda _checked=False, at=index: self.generate_asked.emit(at))
            self._reserve(cursor, button, entry)

    def _thumbnail_box(self) -> QSize:
        tall = self.fontMetrics().lineSpacing() * _THUMBNAIL_LINES
        return QSize(tall * 2, tall)

    def _reserve(self, cursor: QTextCursor, widget: QWidget, entry: _Entry) -> None:
        widget.adjustSize()
        _block(cursor, indent=MARGIN_STANDARD, above=GAP_SMALL)
        room = QTextBlockFormat(cursor.blockFormat())
        room.setLineHeight(widget.height(), QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        cursor.setBlockFormat(room)
        self._tips.append(entry.tip)
        self._placed.append((widget, cursor.blockNumber()))
        widget.show()

    def _place(self) -> None:
        page = self.document()
        scrolled = self.verticalScrollBar().value()
        for widget, block_number in self._placed:
            block = page.findBlockByNumber(block_number)
            top = page.documentLayout().blockBoundingRect(block).top()
            widget.move(MARGIN_STANDARD, round(top + block.blockFormat().topMargin()) - scrolled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def _fit(self) -> None:
        tallest = self.fontMetrics().lineSpacing() * _LINES_AT_MOST
        self.setFixedHeight(min(ceil(self.document().size().height()), tallest))
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._place()

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
    generate_asked = pyqtSignal(int)
    auto_generate_chosen = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = _column_without_margins(self)
        column.setSpacing(GAP_SMALL)
        self._conversation = _Conversation()
        self._conversation.generate_asked.connect(self.generate_asked)
        self._in_flight: dict[str, RunReading] = {}
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
        self._auto_generate = ToggleSwitch(_AUTO_GENERATE)
        self._auto_generate.setToolTip(_AUTO_GENERATE_TIP)
        self._auto_generate.clicked.connect(self.auto_generate_chosen)
        row.addWidget(self._auto_generate)
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
        self._conversation.show_entries(self._held, [self._made_of(entry) for entry in self._held])

    def _made_of(self, entry: _Entry) -> _Made:
        if not entry.made:
            return _Made()
        return _Made(thumbnail=self._thumbnail_of(entry.made) if self._thumbnail_of else None,
                     reading=self._in_flight.get(entry.made))

    def mark_made(self, index: int, prompt_id: str) -> None:
        self._held[index].made = prompt_id
        self._draw()

    def note_in_flight(self, readings: dict[str, RunReading]) -> None:
        made = {entry.made for entry in self._held if entry.made}
        if any(self._in_flight.get(key) != readings.get(key) for key in made):
            self._in_flight = {key: reading for key, reading in readings.items() if key in made}
            self._draw()

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
        if self._auto_generate.isChecked() and self._held[-1].changed_something():
            self.generate_asked.emit(len(self._held) - 1)

    def set_auto_generate(self, on: bool) -> None:
        self._auto_generate.setChecked(on)

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
