"""The generation queue, as one strip along the bottom of the gallery.

Two halves, each answering one question. On the left, *what is being made*: the
live frame of the job ComfyUI is rendering and a fat progress bar beside it,
nothing else, and no wider than a bar needs to be. On the right, taking the rest
of the strip, *what is queued*: every in-flight job as a row of its own — the one
being made at the top — each led by a Cancel, each opening its folder on a click,
and each draggable to a new place in the line. Only the top row is fixed: nothing
can be moved in front of what is already rendering.

The whole strip is one progress bar tall whatever the queue's length, so the panes
above it never move; about two rows show at a time and the rest are a scroll away.

It's fed the in-flight view-models the Recents shelf uses
(:class:`origenerator.gui.inflight.InFlightItem`), leading job first, refreshed on
every poll so the frame and progress stay live; a refresh updates rows in place,
so a drag is never yanked out from under the user. Reordering is asked for, not
done here: :attr:`reorder_requested` carries the order the rows were dropped into,
and whoever owns the jobs makes ComfyUI agree.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QApplication, QFrame,
)
from PyQt6.QtGui import QPixmap, QDrag, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal

from origenerator.gui.inflight import InFlightItem, queue_wait_text
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE, BLUE

_PREVIEW = 80   # the live thumbnail; the full-size preview is one click away
# The bar needs only enough width to read as a bar; the queue's names are long,
# so the rest of the strip goes to the line.
_BAR_WIDTH = 150
# Marks a drag as one of our own rows, so a thumbnail dragged from the gallery
# (which carries its own type) can't be dropped into the queue as a reorder.
QUEUE_ROW_MIME = "application/x-origenerator-queue-row"


class RunningPreview(QWidget):
    """What is being made: its live frame, and a fat bar under it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        self._frame = QLabel()
        self._frame.setFixedSize(_PREVIEW, _PREVIEW)
        self._frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._frame)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(16)  # the fat, important one
        self._progress.setFixedWidth(_BAR_WIDTH)
        layout.addWidget(self._progress)

        self.show_item(None)

    def show_item(self, item):
        """Render ``item``, or blank the half (keeping its space) when nothing runs."""
        self.key = item.key if item is not None else None
        if item is None:
            self._frame.clear()
            self._progress.hide()
            return
        self._progress.show()
        self._render_frame(item.frame)
        if item.status == "running" and item.progress and item.progress[1] > 0:
            cumulative, total = item.progress
            self._progress.setRange(0, total)
            self._progress.setValue(cumulative)
        else:
            self._progress.setRange(0, 0)  # queued, or no step counts yet: indeterminate

    def _render_frame(self, frame):
        pixmap = QPixmap()
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            self._frame.setPixmap(pixmap.scaled(
                _PREVIEW, _PREVIEW, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._frame.clear()  # no frame yet — a blank square, not a stale one


class QueueRow(QWidget):
    """One job in the line: its caption and a Cancel.

    A press-and-release opens the job's folder; a press that travels starts a
    drag, which the strip turns into a reorder. The row being made is the head of
    the line and does not move.
    """

    HEIGHT = 26  # about two of these fit beside the progress bar

    def __init__(self, item, *, movable=True, parent=None):
        super().__init__(parent)
        self.key = item.key
        self.movable = movable
        self._press_at = None  # where a left press landed, until it clicks or drags
        self.setObjectName("queueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("dragging", False)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 6, 1)
        layout.setSpacing(6)
        # Cancel leads the row: the names run long and elide, and a button behind
        # one of those was pushed out of sight at the right-hand end.
        self._cancel = QPushButton("Cancel")
        self._cancel.setObjectName("queueCancelBtn")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.setToolTip("Cancel this generation")
        self._cancel.setFixedHeight(self.HEIGHT - 6)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)
        self._caption = QLabel()
        self._caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._caption, 1)

        self.update_item(item)

    def caption(self) -> str:
        return self._caption.text()

    def update_item(self, item):
        """Re-render this row in place — a queued→running flip, a fresh caption."""
        self._item = item
        # Another app's hold is the one wait worth naming; the user's own place in
        # the line is the line itself.
        self._caption.setText(queue_wait_text(item.foreign_ahead) or item.caption)
        self._caption.setToolTip(item.caption)
        self._cancel.setVisible(item.cancel is not None)

    def set_dragging(self, dragging: bool):
        """Dim this row while it is the one being dragged, so the gesture reads."""
        self.setProperty("dragging", dragging)
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_cancel(self):
        if self._item.cancel is not None:
            self._item.cancel()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.position().toPoint()

    def mouseMoveEvent(self, event):
        """A press that travels far enough becomes a drag, carrying this row's id."""
        if self._press_at is None or not self.movable:
            return
        travelled = (event.position().toPoint() - self._press_at).manhattanLength()
        if travelled < QApplication.startDragDistance():
            return
        self._press_at = None  # this gesture is a drag now, not a pending click
        mime = QMimeData()
        mime.setData(QUEUE_ROW_MIME, self.key.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        self.set_dragging(True)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.set_dragging(False)

    def mouseReleaseEvent(self, event):
        if self._press_at is not None and self._item.reveal is not None:
            self._item.reveal()
        self._press_at = None


class GenerationQueue(QWidget):
    """The live preview and its bar on the left, the whole line on the right."""

    reorder_requested = pyqtSignal(list)  # prompt ids, in the order they were dropped into

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("generationQueue")
        # A raw QWidget paints no stylesheet border without this (see the QWidget
        # stylesheet-border gotcha); a top rule sets the strip off from the panes.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#generationQueue {{ border-top: 1px solid {BORDER_SUBTLE.name()}; }}"
        )
        self.setAcceptDrops(True)  # a row dropped anywhere on the strip reorders it
        self._items: list = []
        self._drop_at: int | None = None  # where a drag in progress would land

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        self._running = RunningPreview()
        layout.addWidget(self._running)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(self._running.sizeHint().height())
        self._host = QWidget()
        self._rows_box = QVBoxLayout(self._host)
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        self._rows_box.addStretch(1)  # rows stack from the top
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)  # the line takes the rest of the strip

        self.set_items([])

    # --- what the strip is showing -----------------------------------------

    def running_preview(self) -> RunningPreview:
        """The live half. Its ``key`` is ``None`` when nothing is being made."""
        return self._running

    def rows(self) -> list[QueueRow]:
        """Every job in the line, top to bottom — the one being made first."""
        return [self._rows_box.itemAt(i).widget()
                for i in range(self._rows_box.count())
                if self._rows_box.itemAt(i).widget() is not None]

    def keys(self) -> list[str]:
        return [row.key for row in self.rows()]

    def set_items(self, items: list):
        """Show ``items`` — every in-flight generation, the one being made first.

        The first also drives the live half. Rows already listed are refreshed in
        place; only a change to the *set* of jobs (or their order) rebuilds the
        list, so a poll landing mid-drag doesn't yank the row out from under the
        gesture.
        """
        self._running.show_item(items[0] if items else None)
        if self.keys() != [item.key for item in items]:
            self._rebuild(items)
            return
        self._items = list(items)
        for row, item in zip(self.rows(), items):
            row.update_item(item)

    def _rebuild(self, items: list):
        self._items = list(items)
        for row in self.rows():
            self._rows_box.removeWidget(row)
            row.deleteLater()
        for index, item in enumerate(items):
            # The head is what ComfyUI is already rendering: it cannot be moved,
            # and nothing can be dropped in front of it.
            self._rows_box.insertWidget(index, QueueRow(item, movable=index > 0))
        # The scroll area would otherwise squeeze the whole line into its own
        # height, stacking the rows on top of each other instead of scrolling.
        self._host.setMinimumHeight(len(items) * QueueRow.HEIGHT)

    # --- moving a job up or down the line -----------------------------------

    def move_row(self, source: int, target: int):
        """Lift the row at ``source`` out and drop it back in at ``target``.

        Re-lists them there and then — ComfyUI's agreement only shows up on a later
        poll, and a row that springs back reads as a failure — then asks for that
        order through :attr:`reorder_requested`. Neither end may be the head: what
        is already rendering keeps the front of the line. A move that changes
        nothing asks for nothing.
        """
        order = [item.key for item in self._items]
        if not 1 <= source < len(order) or not 1 <= target < len(order):
            return
        moved = list(self._items)
        moved.insert(target, moved.pop(source))
        if [item.key for item in moved] == order:
            return
        self._rebuild(moved)
        self.reorder_requested.emit(self.keys())

    # --- accepting a dragged row --------------------------------------------

    def _carried_key(self, event) -> str | None:
        """The row id a drag carries, if it is one of ours and still in the line."""
        if not event.mimeData().hasFormat(QUEUE_ROW_MIME):
            return None
        key = bytes(event.mimeData().data(QUEUE_ROW_MIME)).decode()
        return key if key in [item.key for item in self._items] else None

    def dragEnterEvent(self, event):
        if self._carried_key(event) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """Track where the dragged row would land, and mark it."""
        if self._carried_key(event) is None:
            return
        self._show_drop_mark(self._drop_index(event.position().toPoint()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._show_drop_mark(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """Land a dragged row wherever in the line it was let go."""
        key = self._carried_key(event)
        self._show_drop_mark(None)
        if key is None:
            return
        source = [item.key for item in self._items].index(key)
        target = self._drop_index(event.position().toPoint())
        # The insertion point was read with the dragged row still in place, so a
        # drop below it names a slot one further along than it will end up in.
        self.move_row(source, target - 1 if target > source else target)
        event.acceptProposedAction()

    def _show_drop_mark(self, index: int | None):
        """Draw (or clear) the line showing where a drop would insert."""
        if index != self._drop_at:
            self._drop_at = index
            self.update()

    def _drop_index(self, point) -> int:
        """Which slot a drop at ``point`` (in this widget's coordinates) lands in:
        above the row whose top half it fell on, else at the end of the line. Never
        in front of the head, which is already being rendered."""
        for index, row in enumerate(self.rows()):
            middle = row.mapTo(self, row.rect().center())
            if point.y() < middle.y():
                return max(1, index)
        return len(self.rows())

    def paintEvent(self, event):
        """Paint the insertion mark over the line while a row is being dragged."""
        super().paintEvent(event)
        if self._drop_at is None:
            return
        rows = self.rows()
        if not rows:
            return
        row = rows[min(self._drop_at, len(rows) - 1)]
        top_left = row.mapTo(self, row.rect().topLeft())
        y = top_left.y() if self._drop_at < len(rows) else top_left.y() + row.height()
        painter = QPainter(self)
        painter.setPen(QPen(QColor(BLUE), 2))
        painter.drawLine(top_left.x(), y, top_left.x() + row.width(), y)
        painter.end()
