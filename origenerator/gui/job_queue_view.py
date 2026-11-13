from __future__ import annotations

import shiboken6
from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import BLUE, BORDER_SUBTLE
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.spacing import BUTTON_ICON_INSET, GAP_MEDIUM, GAP_SMALL

from origenerator.gui import icons
from origenerator.gui.combination import Combination
from origenerator.gui.combination_view import combination_pixmap
from origenerator.gui.drag_thumbnail import DragOut
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.inflight import (
    CANCEL_ALL_TEXT,
    CANCEL_ALL_TIP,
    CANCEL_TEXT,
    CLEAR_TEXT,
    EMPTY_QUEUE_TEXT,
    MOVE_DOWN_TIP,
    MOVE_UP_TIP,
    SHIELD_ALL_TEXT,
    SHIELD_ALL_TIP,
    SHIELD_TIP,
    START_NOW_TEXT,
    START_NOW_TOOLTIP,
    TICK_MS,
    cancel_tooltip,
    clear_queue_tooltip,
    first_movable,
    foreign_queue_text,
    jobs_to_cancel,
    jobs_to_shield,
    movable,
    queue_lead_text,
    queue_lead_tooltip,
    queue_wait_text,
    seconds_until_start,
    shield_every_job,
    starting_row_text,
)
from origenerator.gui.progress_bar import BAR_HEIGHT, ProgressBar
from origenerator.gui.queue_thumbs import QueueThumbs
from origenerator.gui.stylesheet import CHOSEN
from origenerator.gui.widget_size import QWIDGETSIZE_MAX
from origenerator.workflows.derived_size import resolve_input_image_path

_ROW_HEIGHT = 88
_RULE_WIDTH = 1
_BAR_WIDTH = 290
_HALVES_GAP = GAP_MEDIUM
QUEUE_ROW_MIME = "application/x-origenerator-queue-row"


def _made_from(item) -> Combination:
    frame = resolve_input_image_path(item.source_image)
    return Combination(str(frame) if frame is not None else None, item.source_video_thumbnail,
                       item.prompt_edited)


def _offer(button: QPushButton, enabled: bool) -> None:
    button.setEnabled(enabled)
    button.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)


class OpensAFolder:
    _press_at = None

    def folder_of(self, position):
        raise NotImplementedError

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.position().toPoint()

    def mouseReleaseEvent(self, event):
        if self._press_at is not None:
            self._open_folder(self._press_at)
        self._press_at = None

    def mouseDoubleClickEvent(self, event):
        # Qt delivers the second press of a double-click as this event, not as a press.
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = None
            self._open_folder(event.position().toPoint())

    def _open_folder(self, position):
        reveal = self.folder_of(position)
        if reveal is not None:
            reveal()


class RunningPreview(OpensAFolder, QWidget):
    start_now_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None
        self._item = None
        self._press_at = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP_MEDIUM)
        self._frame = QLabel()
        self._frame.setFixedSize(_ROW_HEIGHT, _ROW_HEIGHT)
        self._frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._frame, 0, Qt.AlignmentFlag.AlignBottom)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        column.addStretch(1)
        self._progress = ProgressBar()
        self._progress.setFixedHeight(BAR_HEIGHT)
        self._progress.setFixedWidth(_BAR_WIDTH)
        column.addWidget(self._progress)
        self._under_the_bar = QWidget()
        self._under_the_bar.setMinimumWidth(_BAR_WIDTH)
        under_the_bar = QHBoxLayout(self._under_the_bar)
        under_the_bar.setContentsMargins(0, 0, 0, 0)
        under_the_bar.setSpacing(_HALVES_GAP)
        self._caption = QLabel()
        self._caption.setObjectName("mutedLabel")
        self._caption.setWordWrap(True)
        under_the_bar.addWidget(self._caption, 1)
        self._start_now = QPushButton(START_NOW_TEXT)
        self._start_now.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_now.setToolTip(START_NOW_TOOLTIP)
        self._start_now.clicked.connect(self.start_now_requested)
        under_the_bar.addWidget(self._start_now)
        under_the_bar.addStretch(0)
        column.addWidget(self._under_the_bar)
        column.addStretch(1)
        layout.addLayout(column)

        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        self.show_item(None)

    def show_foreign(self, text: str):
        self._caption.setText(text)
        self._under_the_bar.setVisible(bool(text) or self._item is None)

    def status_text(self) -> str:
        return self._caption.text() or (
            self._progress.caption() if self._item is not None else ""
        )

    def folder_of(self, position):
        if self._item is None or not self._frame.geometry().contains(position):
            return None
        return self._item.reveal

    def show_item(self, item):
        self.key = item.key if item is not None else None
        self._item = item
        if item is None:
            self._frame.unsetCursor()
            self._render_frame(None)
            self._progress.hide()
            self._under_the_bar.show()
            self._offer_start_now(False)
            self._tick.stop()
            return
        self._frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._progress.show()
        self._render_frame(item)
        self._render_timing()
        self._tick.start()

    def _render_timing(self):
        if self._item is None:
            return
        self.show_foreign(queue_wait_text(self._item.foreign_ahead, self._item.starts_at) or "")
        self._offer_start_now(seconds_until_start(self._item.starts_at) is not None)
        self._progress.show_progress(
            self._item.reading.caption(),
            *self._item.reading.bars(),
        )

    def _offer_start_now(self, offered: bool) -> None:
        line = self._under_the_bar.layout()
        line.setStretchFactor(self._caption, 0 if offered else 1)
        line.setStretch(line.count() - 1, 1 if offered else 0)
        self._caption.setWordWrap(not offered)
        self._under_the_bar.setMaximumWidth(QWIDGETSIZE_MAX if offered else _BAR_WIDTH)
        self._start_now.setVisible(offered)

    def _render_frame(self, item):
        side = min(self.height(), _ROW_HEIGHT)
        pixmap = QPixmap()
        frame = None if item is None else item.reading.frame
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            pixmap = pixmap.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = None if item is None else combination_pixmap(
                _made_from(item), QSize(2 * side, side))
        if pixmap is None:
            self._frame.setFixedSize(side, side)
            self._frame.clear()
            return
        self._frame.setFixedSize(max(side, pixmap.width()), side)
        self._frame.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if min(self.height(), _ROW_HEIGHT) != self._frame.height():
            self._render_frame(self._item)


class QueueRow(OpensAFolder, QWidget):
    HEIGHT = 34
    THUMB = HEIGHT - 2 * GAP_SMALL
    INSET = GAP_SMALL

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.key = item.key
        self._press_at = None
        self._drag_out = DragOut()
        self.setObjectName("queueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("dragging", False)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self.INSET, GAP_SMALL, GAP_MEDIUM, GAP_SMALL)
        layout.setSpacing(GAP_MEDIUM)
        self._up = self._arrow(icons.move_up_icon(), MOVE_UP_TIP, self._on_up)
        layout.addWidget(self._up)
        self._down = self._arrow(icons.move_down_icon(), MOVE_DOWN_TIP, self._on_down)
        layout.addWidget(self._down)
        self._shield = fill_square_with_icon(QPushButton(), size=self.HEIGHT - 12)
        self._shield.setProperty(CHOSEN, True)
        self._shield.setCheckable(True)
        self._shield.setIcon(icons.shield_icon())
        self._shield.setToolTip(SHIELD_TIP)
        self._shield.clicked.connect(self._on_shield)
        layout.addWidget(self._shield)
        self._cancel = QPushButton(CANCEL_TEXT)
        self._cancel.setObjectName("queueCancelBtn")
        self._cancel.setFixedHeight(self.HEIGHT - 12)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)
        self._thumbs = QueueThumbs(self.THUMB)
        layout.addWidget(self._thumbs)
        self._lead = ElidingLabel()
        self._lead.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._lead)
        self._note = QLabel()
        self._note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._note.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        layout.addWidget(self._note, 1)

        self.update_item(item)

    def _arrow(self, icon, tooltip: str, pressed) -> QPushButton:
        arrow = fill_square_with_icon(QPushButton(), size=self.HEIGHT - 12)
        arrow.setIcon(icon)
        arrow.setToolTip(tooltip)
        arrow.clicked.connect(pressed)
        return arrow

    def update_item(self, item):
        self._item = item
        self.movable = movable(item)
        for arrow, move in ((self._up, item.move_up), (self._down, item.move_down)):
            _offer(arrow, move is not None)
        self._lead.setText(queue_lead_text(item))
        self._lead.setToolTip(f"{item.caption}\n\n{queue_lead_tooltip(item)}")
        self._note_text = starting_row_text(item.starting) or ""
        self._render_note()
        self._cancel.setToolTip(cancel_tooltip(item.populating))
        _offer(self._cancel, item.cancel is not None)
        _offer(self._shield, item.shield is not None)
        self._shield.setChecked(item.shielded)
        self._render_thumbs(item)

    def _render_note(self):
        self._note.setText(self._note.fontMetrics().elidedText(
            self._note_text, Qt.TextElideMode.ElideRight, self._note.width()
        ))
        self._note.setToolTip(self._note_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_note()

    def _render_thumbs(self, item):
        if self._thumbs.show_source(_made_from(item)):
            return
        if item.folder_thumbnails:
            self._thumbs.show_folder(item.folder_thumbnails)
            return
        self._thumbs.clear_block()

    def set_dragging(self, dragging: bool):
        self.setProperty("dragging", dragging)
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_up(self):
        if self._item.move_up is not None:
            self._item.move_up()

    def _on_down(self):
        if self._item.move_down is not None:
            self._item.move_down()

    def _on_cancel(self):
        if self._item.cancel is not None:
            self._item.cancel()

    def _on_shield(self, shielded: bool):
        if self._item.shield is not None:
            self._item.shield(shielded)

    def folder_of(self, position):
        return self._item.reveal

    def mouseMoveEvent(self, event):
        if self._press_at is None or not self.movable:
            return
        travelled = (event.position().toPoint() - self._press_at).manhattanLength()
        if travelled < QApplication.startDragDistance():
            return
        self._press_at = None
        mime = QMimeData()
        mime.setData(QUEUE_ROW_MIME, self.key.encode())
        self.set_dragging(True)
        try:
            self._drag_out.start(mime, self.grab(), action=Qt.DropAction.MoveAction)
        finally:
            if shiboken6.isValid(self):
                self.set_dragging(False)


class _Rules(QWidget):
    def __init__(self, lines, parent):
        super().__init__(parent)
        self._lines = lines
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        for pen, points in self._lines():
            painter.setPen(pen)
            painter.drawPolyline(QPolygon(points))
        painter.end()


class JobQueueView(QWidget):
    move_requested = Signal(str, object)
    clear_queue_requested = Signal()
    start_now_requested = Signal()
    cancel_all_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("generationQueue")
        self.setAcceptDrops(True)
        self.setMinimumHeight(_ROW_HEIGHT)
        self._items: list = []
        self._drop_at: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, GAP_SMALL, 0)
        layout.setSpacing(_HALVES_GAP)
        outer.addLayout(layout, 1)
        self._running = RunningPreview()
        self._running.start_now_requested.connect(self.start_now_requested)
        layout.addWidget(self._running)
        self._clear = QPushButton(CLEAR_TEXT)
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.clicked.connect(self.clear_queue_requested)
        self._clear.hide()
        layout.addWidget(self._clear)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self._host = QWidget()
        self._rows_column = QVBoxLayout(self._host)
        self._rows_column.setContentsMargins(0, 0, 0, 0)
        self._rows_column.setSpacing(0)
        self._rows_column.addStretch(1)
        self._hint = QLabel(EMPTY_QUEUE_TEXT)
        self._hint.setObjectName("mutedLabel")
        self._rows_column.addWidget(self._hint, 0, Qt.AlignmentFlag.AlignHCenter)
        self._rows_column.addStretch(1)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)
        self._for_all = self._for_every_job()
        layout.addWidget(self._for_all)
        self._rules = _Rules(self._drawn_rules, self)
        self._scroll.verticalScrollBar().valueChanged.connect(self._rules.update)

        self.set_items([])

    def _for_every_job(self) -> QWidget:
        column = QWidget()
        stack = QVBoxLayout(column)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.addStretch(1)
        self._shield_all = QPushButton(SHIELD_ALL_TEXT)
        self._shield_all.setIcon(icons.shield_icon())
        mark = QueueRow.HEIGHT - 12 - 2 * BUTTON_ICON_INSET
        self._shield_all.setIconSize(QSize(mark, mark))
        self._shield_all.setToolTip(SHIELD_ALL_TIP)
        self._shield_all.clicked.connect(self._shield_every_job)
        self._cancel_all = QPushButton(CANCEL_ALL_TEXT)
        self._cancel_all.setToolTip(CANCEL_ALL_TIP)
        self._cancel_all.clicked.connect(self.cancel_all_requested)
        for button in (self._shield_all, self._cancel_all):
            button.setFixedHeight(QueueRow.HEIGHT - 12)
            stack.addWidget(button)
        stack.addStretch(1)
        return column

    def _shield_every_job(self):
        shield_every_job(self._items)
        self._line_up(self._items)

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), _ROW_HEIGHT + _RULE_WIDTH)

    def rows(self) -> list[QueueRow]:
        return [self._rows_column.itemAt(i).widget()
                for i in range(self._rows_column.count())
                if isinstance(self._rows_column.itemAt(i).widget(), QueueRow)]

    def keys(self) -> list[str]:
        return [row.key for row in self.rows()]

    def set_items(self, items: list, foreign_queued: int = 0):
        leader = items[0] if items else None
        self._running.show_item(leader)
        self._clear.setVisible(bool(foreign_queued))
        self._clear.setToolTip(clear_queue_tooltip(foreign_queued))
        free_half = ""
        if leader is None:
            free_half = foreign_queue_text(foreign_queued) or ""
            self._running.show_foreign(free_half)
        self._hint.setVisible(not items)
        self._for_all.setVisible(bool(items))
        self._running.setVisible(bool(items) or bool(free_half))
        self._line_up(items)

    def _line_up(self, items: list):
        self._items = list(items)
        standing = {row.key: row for row in self.rows()}
        for key in standing.keys() - {item.key for item in items}:
            gone = standing.pop(key)
            self._rows_column.removeWidget(gone)
            gone.deleteLater()
        for index, item in enumerate(items):
            row = standing.get(item.key)
            if row is None:
                row = QueueRow(item)
            else:
                row.update_item(item)
            if self._rows_column.indexOf(row) != index:
                self._rows_column.removeWidget(row)
                self._rows_column.insertWidget(index, row)
        # Qt's QScrollArea would otherwise squeeze every row into its own height, stacking them on top of each other instead of scrolling.
        self._host.setMinimumHeight(len(items) * QueueRow.HEIGHT)
        _offer(self._shield_all, bool(jobs_to_shield(items)))
        _offer(self._cancel_all, bool(jobs_to_cancel(items)))
        self._rules.update()

    def head_rule(self) -> list[QPoint]:
        rows = self.rows()
        if not rows:
            return []
        head = rows[0]
        left_half_ends = self._scroll.x() - _HALVES_GAP - 1
        rows_start = self._scroll.x() + QueueRow.INSET
        x = (left_half_ends + rows_start) // 2
        up = QPoint(x, self.height() - 1)
        foot = head.mapTo(self, head.rect().bottomRight())
        if foot.y() < self._scroll.y():
            return [up, QPoint(x, self._scroll.y())]
        return [up, QPoint(x, foot.y()), foot]

    def _drop_rule(self) -> list[QPoint]:
        rows = self.rows()
        if self._drop_at is None or not rows:
            return []
        row = rows[min(self._drop_at, len(rows) - 1)]
        top_left = row.mapTo(self, row.rect().topLeft())
        y = top_left.y() if self._drop_at < len(rows) else top_left.y() + row.height()
        return [QPoint(top_left.x(), y), QPoint(top_left.x() + row.width(), y)]

    def _drawn_rules(self):
        return [(QPen(BORDER_SUBTLE, 1), self.head_rule()), (QPen(BLUE, 2), self._drop_rule())]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rules.resize(event.size())

    def _carried_key(self, event) -> str | None:
        if not event.mimeData().hasFormat(QUEUE_ROW_MIME):
            return None
        key = bytes(event.mimeData().data(QUEUE_ROW_MIME)).decode()
        return key if key in [item.key for item in self._items] else None

    def dragEnterEvent(self, event):
        if self._carried_key(event) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self._carried_key(event) is None:
            return
        self._show_drop_mark(self._drop_index(event.position().toPoint()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._show_drop_mark(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        key = self._carried_key(event)
        self._show_drop_mark(None)
        if key is None:
            return
        keys = [item.key for item in self._items]
        place = self._drop_index(event.position().toPoint())
        rest = [other for other in keys if other != key]
        landing = place - 1 if place > keys.index(key) else place
        if [*rest[:landing], key, *rest[landing:]] != keys:
            self.move_requested.emit(key, rest[landing] if landing < len(rest) else None)
        event.acceptProposedAction()

    def _show_drop_mark(self, index: int | None):
        if index != self._drop_at:
            self._drop_at = index
            self._rules.update()

    def _drop_index(self, point) -> int:
        for index, row in enumerate(self.rows()):
            middle = row.mapTo(self, row.rect().center())
            if point.y() < middle.y():
                return max(first_movable(self._items), index)
        return len(self.rows())
