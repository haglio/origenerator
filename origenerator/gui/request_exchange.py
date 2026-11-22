from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import (
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import BLUE_LIGHT, TEXT_PRIMARY
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD
from shared_ui.toggle_switch import ToggleSwitch

from origenerator.db_requests import Turn
from origenerator.gui.cancel_bar import CancelBar
from origenerator.gui.change_tip import change_tip, fitted
from origenerator.gui.generate_button import GenerateButton
from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import RunReading, cancel_tooltip
from origenerator.gui.progress_bar import ProgressBar

_ASK = "What to change, e.g. two women"
_REQUEST = "Request"
_FAILED = "couldn't work that into the prompts"
_LINES_AT_MOST = 20
_THUMBNAIL_LINES = 2
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
    def __init__(self, turn, *, waiting: bool = False):
        self.said = turn[0]
        self.take(turn)
        self.waiting = waiting

    def take(self, turn) -> None:
        self.waiting = False
        self.answered = turn[1]
        turn = Turn(*turn)
        self.made = turn.made
        self._change = (turn.old_positive, turn.old_negative, turn.new_positive, turn.new_negative)
        self._settings = turn.changes()
        self.tip = ""

    def has_a_change_recorded(self) -> bool:
        return any(self._change) or bool(self._settings)

    def changed_anything(self) -> bool:
        old_positive, old_negative, new_positive, new_negative = self._change
        return (old_positive, old_negative) != (new_positive, new_negative) or bool(self._settings)

    def compare(self, before: str, thumbnail_of: Callable[[str], str | None] | None) -> None:
        if not self.has_a_change_recorded():
            self.tip = ""
            return
        before_thumbnail, after_thumbnail = (
            thumbnail_of(made) if thumbnail_of is not None and made else None
            for made in (before, self.made))
        self.tip = change_tip(before_thumbnail, after_thumbnail, self._change, self._settings,
                              with_thumbnails=thumbnail_of is not None)


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
    item: str = ""
    thumbnail: str | None = None
    reading: RunReading | None = None
    generate: bool = False


class _Thumbnail(QLabel):
    clicked = Signal()

    def __init__(self, parent: QWidget, item: str, image: QPixmap, *, opens: bool, tip: str):
        super().__init__(parent)
        self.item = item
        self._opens = opens
        self.setPixmap(image)
        self.setToolTip(tip)
        if opens:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if self._opens and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()


def _scaled_to(image_format: QTextImageFormat) -> QPixmap:
    return QPixmap(image_format.name()).scaled(
        round(image_format.width()), round(image_format.height()),
        Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


class _Conversation(QTextEdit):
    generate_asked = Signal(int)
    cancel_asked = Signal(str)
    item_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setStyleSheet("QTextEdit { background: transparent; }")
        page = self.document()
        page.setDocumentMargin(0)
        page.documentLayout().documentSizeChanged.connect(lambda _size: self._fit())
        self.verticalScrollBar().valueChanged.connect(lambda _value: self._place())
        self._tips: list[str] = []
        self._placed: list[tuple[QWidget, int]] = []
        self._generate_buttons: dict[int, GenerateButton] = {}
        self.hide()

    def show_entries(self, entries: list[_Entry], made: list[_Made], showing: str | None) -> None:
        for widget, _block_number in self._placed:
            widget.hide()
            widget.deleteLater()
        self._placed = []
        self._generate_buttons = {}
        self.clear()
        cursor = self.textCursor()
        self._tips = []
        for index, entry in enumerate(entries):
            _paragraph(cursor, entry.said, BLUE_LIGHT, above=GAP_SMALL if self._tips else 0)
            self._tips.append(entry.tip)
            if entry.answered:
                _paragraph(cursor, entry.answered, TEXT_PRIMARY, indent=MARGIN_STANDARD)
                self._tips.append(entry.tip)
            self._show_what_was_made(cursor, index, entry, made[index], showing)
        self.setVisible(bool(entries))
        self._fit()

    def _show_what_was_made(self, cursor: QTextCursor, index: int, entry: _Entry,
                            made: _Made, showing: str | None) -> None:
        if made.reading is not None:
            bar = CancelBar(cancel_tooltip(False), self.viewport())
            bar.setFixedSize(self._generate_button_size())
            bar.show_progress(made.reading.caption(), *made.reading.bars())
            bar.clicked.connect(lambda item=made.item: self.cancel_asked.emit(item))
            self._reserve(cursor, bar, entry)
        elif made.item:
            image_format = fitted(made.thumbnail, self._thumbnail_box())
            if image_format is not None:
                thumbnail = _Thumbnail(self.viewport(), made.item, _scaled_to(image_format),
                                       opens=made.item != showing, tip=entry.tip)
                thumbnail.clicked.connect(lambda item=made.item: self.item_activated.emit(item))
                self._reserve(cursor, thumbnail, entry)
        elif made.generate:
            button = GenerateButton(self.viewport(), sizes_itself=True)
            button.clicked.connect(lambda _checked=False, at=index: self.generate_asked.emit(at))
            self._generate_buttons[index] = button
            self._reserve(cursor, button, entry)

    def refuse_generate(self, index: int, why: str) -> None:
        button = self._generate_buttons.get(index)
        if button is not None:
            button.flash_guard(why)

    def _generate_button_size(self) -> QSize:
        button = GenerateButton(self.viewport())
        button.hide()
        button.adjustSize()
        size = button.size()
        button.deleteLater()
        return size

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
            if isinstance(widget, CancelBar):
                widget.hover_if_the_pointer_is_on_it()

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
    asked = Signal(str)
    generate_asked = Signal(int)
    cancel_asked = Signal(str)
    item_activated = Signal(str)
    auto_generate_chosen = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = _column_without_margins(self)
        column.setSpacing(GAP_SMALL)
        self._conversation = _Conversation()
        self._conversation.generate_asked.connect(self.generate_asked)
        self._conversation.cancel_asked.connect(self.cancel_asked)
        self._conversation.item_activated.connect(self.item_activated)
        self._in_flight: dict[str, RunReading] = {}
        self._held: list[_Entry] = []
        self._started_on: str | None = None
        self._showing: str | None = None
        self._thumbnail_of: Callable[[str], str | None] | None = None
        self._generate_offered: Callable[[int], bool] = lambda _index: True
        self._remade_by: Callable[[int], str | None] = lambda _index: None
        column.addWidget(self._conversation)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit()
        line.setPlaceholderText(_ASK)
        line.returnPressed.connect(self._ask)
        self._line = line
        self._request = GenerateButton()
        self._request.set_caption(_REQUEST)
        self._request.clicked.connect(self._ask)
        self._working = ProgressBar()
        self._working.hide()
        self._status = QLabel()
        self._status.hide()
        self._auto_generate = ToggleSwitch(_AUTO_GENERATE)
        self._auto_generate.setToolTip(_AUTO_GENERATE_TIP)
        self._auto_generate.clicked.connect(self.auto_generate_chosen)
        row.addWidget(line, 1)
        for widget in (self._request, self._working, self._status, self._auto_generate):
            row.addWidget(widget)
        column.addLayout(row)

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

    def set_generate_offered(self, offered: Callable[[int], bool]) -> None:
        self._generate_offered = offered

    def set_remade_by(self, remade_by: Callable[[int], str | None]) -> None:
        self._remade_by = remade_by

    def _offers_generate(self, index: int) -> bool:
        entry = self._held[index]
        return not entry.made and entry.changed_anything() and self._generate_offered(index)

    def _draw(self) -> None:
        before = self._started_on or ""
        for entry in self._held:
            entry.compare(before, self._thumbnail_of)
            before = entry.made
        self._conversation.show_entries(
            self._held, [self._made_of(index) for index in range(len(self._held))],
            self._showing)

    def _made_of(self, index: int) -> _Made:
        entry = self._held[index]
        item = entry.made or (self._remade_by(index) if entry.changed_anything() else None)
        if not item:
            return _Made(generate=self._offers_generate(index))
        return _Made(item=item, thumbnail=self._thumbnail_of(item) if self._thumbnail_of else None,
                     reading=self._in_flight.get(item))

    def mark_made(self, index: int, prompt_id: str) -> None:
        self._held[index].made = prompt_id
        if prompt_id:
            self._in_flight[prompt_id] = RunReading(JobState.QUEUED)
        self._draw()

    def note_in_flight(self, readings: dict[str, RunReading]) -> None:
        made = {entry.made for entry in self._held if entry.made}
        if any(self._in_flight.get(key) != readings.get(key) for key in made):
            self._in_flight = {key: reading for key, reading in readings.items() if key in made}
            self._draw()

    def _settle(self, status: str = "") -> None:
        waiting = bool(self._held) and self._held[-1].waiting
        _say(self._status, status)
        self._line.setEnabled(not waiting)
        if waiting:
            self._working.setFixedSize(self._request.size())
            self._working.show_progress(_REQUEST, None)
        self._request.setHidden(waiting)
        self._working.setVisible(waiting)

    def show_exchange(self, turns, *, started_on: str | None = None,
                      asking: str | None = None, showing: str | None = None) -> None:
        self._held = [_Entry(turn) for turn in turns]
        if asking:
            self._held.append(_Entry((asking, ""), waiting=True))
        self._started_on = started_on
        self._showing = showing
        self._draw()
        self._settle()

    def add_turn(self, said: str) -> None:
        self._held.append(_Entry((said, ""), waiting=True))
        self._draw()
        self._settle()

    def answered(self, turn) -> None:
        self._held[-1].take(turn)
        self._draw()
        self._settle()
        if self._auto_generate.isChecked() and self._offers_generate(len(self._held) - 1):
            self.generate_asked.emit(len(self._held) - 1)

    def refuse_generate(self, index: int, why: str) -> None:
        self._conversation.refuse_generate(index, why)

    def set_auto_generate(self, on: bool) -> None:
        self._auto_generate.setChecked(on)

    def failed(self) -> None:
        self._held.pop()
        self._draw()
        self._settle(_FAILED)
