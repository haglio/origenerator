"""The generation queue, as one strip along the foot of the gallery's own panes.

Two halves, each answering one question. On the left, *what is being made*: the
live frame of the job ComfyUI is rendering, filling the strip's height out of its
bottom-left corner, and beside it a column no wider than a bar needs to be — the
job's clock, "1:30 elapsed · ~10:34 left", reading directly above the fat
progress bar it measures. With nothing of ours in flight the same half says what
the shared server is busy with instead, and offers a Clear for it.
On the right, taking the rest of the strip, *what is queued*: every in-flight job
as a row of its own — the one being made at the top — each led by a Cancel, each
opening its folder on a click, and each draggable to a new place in the line. Only
the top row is fixed: nothing can be moved in front of what is already rendering.
With nothing queued at all, that side says so in dim letters in the middle of its
own space, rather than sitting blank.

It opens one progress bar tall — about two rows, the rest a scroll away — and its
top edge is a splitter handle, so a long queue can be dragged open to as many rows
as it's worth giving up. The extra height all goes to the line: the thumbnail
never grows past the strip's opening height, so a queue dragged tall is a queue
you can read rather than one enormous frame.

It's fed the in-flight view-models the Recents shelf uses
(:class:`origenerator.gui.inflight.InFlightItem`), leading job first, refreshed on
every poll so the frame and progress stay live; a refresh updates rows in place,
so a drag is never yanked out from under the user. Reordering is asked for, not
done here: :attr:`reorder_requested` carries the order the rows were dropped into,
and whoever owns the jobs re-lines the queue.

A row the queue is deliberately holding — a video, while a slideshow plays — says
so in place of its caption, and with nothing of ours running the left half says it
for the whole line. A queue that has stopped moving with the GPU idle is exactly
the thing a user goes hunting for an explanation of.
"""

import time

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QApplication, QFrame, QSizePolicy,
)
from PyQt6.QtGui import QPixmap, QDrag, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QMimeData, QTimer, pyqtSignal

from origenerator.gui.inflight import (
    InFlightItem, discard_run_text, discard_run_tooltip, foreign_queue_text,
    held_row_text, queue_held_text, queue_wait_text,
)
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.timing import progress_time_label

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE, BLUE

# The strip's opening height, its floor, and so the widest the live thumbnail
# ever gets: it takes the bottom-left corner whole, being the one thing here worth
# looking at (the full-size preview is still one click away). The strip never
# opens taller than this however long the line gets, so the panes above it don't
# move on their own — only on a drag of the handle at its top edge.
_STRIP_HEIGHT = 88
# The clock and the bar beneath it share one column, wide enough to read a line
# of the clock and for the bar to read as a bar. The queue's names are long, so
# the rest of the strip goes to the line.
_BAR_WIDTH = 200
# How often the running half re-reads the clock. Its own timer rather than the
# gallery's 1.5s poll, which would make a seconds count skip every other tick.
_TICK_MS = 1000
# Marks a drag as one of our own rows, so a thumbnail dragged from the gallery
# (which carries its own type) can't be dropped into the queue as a reorder.
QUEUE_ROW_MIME = "application/x-origenerator-queue-row"


class RunningPreview(QWidget):
    """What is being made: its live frame, and beside it a clock over a fat bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None
        self._item = None

        layout = QHBoxLayout(self)
        # No margins: the frame is meant to reach the strip's edges, and the
        # column beside it centers itself in the same height.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._frame = QLabel()
        self._frame.setFixedSize(_STRIP_HEIGHT, _STRIP_HEIGHT)  # kept square: resizeEvent
        self._frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Pinned to the bottom, so it still sits in the strip's corner once the
        # strip is dragged taller than the square it stops growing at.
        layout.addWidget(self._frame, 0, Qt.AlignmentFlag.AlignBottom)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addStretch(1)
        # Above the bar: how long this run has been going and how much longer it
        # has, so a bar creeping along has something to be measured against. It
        # reads over the bar rather than beside it — two readings of the one run,
        # neither made to give up width to the other. With nothing of ours being
        # made the same line is free to say what the shared server is busy with.
        self._caption = QLabel()
        self._caption.setObjectName("estimateLabel")  # muted secondary text
        self._caption.setWordWrap(True)
        self._caption.setFixedWidth(_BAR_WIDTH)  # a long line wraps, not widens
        column.addWidget(self._caption)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(16)  # the fat, important one
        self._progress.setFixedWidth(_BAR_WIDTH)
        column.addWidget(self._progress)
        column.addStretch(1)
        layout.addLayout(column)

        # Its own clock rather than the gallery's poll, so the count advances a
        # second at a time whether or not a refresh has landed.
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        self.show_item(None)

    def show_foreign(self, text: str):
        """Say what another app has on ComfyUI — only while this half is free."""
        self._caption.setText(text)

    def show_item(self, item):
        """Render ``item``, or blank the half (keeping its space) when nothing runs."""
        self.key = item.key if item is not None else None
        self._item = item
        if item is None:
            self._frame.clear()
            self._progress.hide()
            self._tick.stop()
            return
        self._progress.show()
        self._render_frame(item.frame)
        self._render_timing()  # a job of ours takes the caption back for its clock
        self._tick.start()
        if item.status == "running" and item.progress and item.progress[1] > 0:
            cumulative, total = item.progress
            self._progress.setRange(0, total)
            self._progress.setValue(cumulative)
        else:
            self._progress.setRange(0, 0)  # queued, or no step counts yet: indeterminate

    def _render_timing(self):
        """How long the running job has been going, and how much longer it has.

        Read off the clock rather than off the feed. A job ComfyUI hasn't started
        has no elapsed time to report and the line stays empty — its wait is the
        queue beside it to explain, not a zero counting up under a bar that has
        not moved.
        """
        if self._item is None:
            self._caption.clear()
            return
        started = self._item.started_at
        elapsed = None if started is None else max(0.0, time.time() - started)
        self._caption.setText(progress_time_label(
            elapsed, self._item.progress, self._item.typical_seconds
        ))

    def _render_frame(self, frame):
        side = self._frame.width()
        pixmap = QPixmap()
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            self._frame.setPixmap(pixmap.scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._frame.clear()  # no frame yet — a blank square, not a stale one

    def resizeEvent(self, event):
        """Keep the frame the largest square the strip's height leaves room for.

        Taken off the height rather than a size of its own, so the thumbnail is
        always as big as the corner it sits in: a strip laid out any other height
        grows it to match instead of stranding it in an empty square. Only up to
        the strip's opening height, though — a queue dragged open is being opened
        to read the line, and every pixel past that goes to the rows.
        """
        super().resizeEvent(event)
        side = min(self.height(), _STRIP_HEIGHT)
        if side != self._frame.width():
            self._frame.setFixedSize(side, side)
            self._render_frame(None if self._item is None else self._item.frame)


class QueueRow(QWidget):
    """One job in the line: its caption and the button that throws it away.

    That button reads "Cancel", or "Next seed" for a job whose folder is
    auto-generating — where the press discards the seed and the loop starts
    another (:func:`inflight.discard_run_text`).

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
        # It leads the row: the names run long and elide, and a button behind one
        # of those was pushed out of sight at the right-hand end.
        self._cancel = QPushButton()
        self._cancel.setObjectName("queueCancelBtn")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
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
        """Re-render this row in place — a queued→running flip, a fresh caption,
        or an Auto toggle that changed what the button gets you."""
        self._item = item
        # Two waits are worth naming over the job's own name: one this queue is
        # imposing (a video, while a slideshow plays), and another app's hold.
        # The user's own place in the line is the line itself.
        self._caption.setText(
            held_row_text(item.held) or queue_wait_text(item.foreign_ahead) or item.caption
        )
        self._caption.setToolTip(item.caption)
        self._cancel.setText(discard_run_text(item.auto_generating))
        self._cancel.setToolTip(discard_run_tooltip(item.auto_generating))
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
    clear_queue_requested = pyqtSignal()  # wipe another app's work off ComfyUI

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("generationQueue")
        self.setAcceptDrops(True)  # a row dropped anywhere on the strip reorders it
        # A floor, not a fixed height: the strip opens one bar tall and grows only
        # when its splitter handle is dragged, so the panes above never move on
        # their own however long the line gets.
        self.setMinimumHeight(_STRIP_HEIGHT)
        self._items: list = []
        self._drop_at: int | None = None  # where a drag in progress would land

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # An explicit hairline rather than a stylesheet border: the app paints
        # every plain widget one flat color, and a border drawn under a child's
        # own background disappears into it. This one is a widget of its own, so
        # it is there whatever is laid out beneath it.
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {BORDER_SUBTLE.name()};")
        outer.addWidget(rule)

        layout = QHBoxLayout()
        # Flush at the left and both ends, so the live frame fills the strip's
        # bottom-left corner; only the far right is held off the window edge.
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(8)
        outer.addLayout(layout, 1)
        self._running = RunningPreview()
        layout.addWidget(self._running)
        # Only ever offered for another app's work — the user's own queue is what
        # he asked for, and every row of it carries its own Cancel already.
        self._clear = QPushButton("Clear")
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.clicked.connect(self.clear_queue_requested)
        self._clear.hide()
        layout.addWidget(self._clear)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Takes whatever height the strip has and asks for none of its own: a
        # twelve-job line must not make the strip open twelve rows tall, and a
        # strip dragged open must hand every extra pixel to these rows.
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self._host = QWidget()
        self._rows_box = QVBoxLayout(self._host)
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        self._rows_box.addStretch(1)  # rows stack from the top
        # What the empty line is for. The strip holds its space whether or not
        # anything is queued, so this side spends most of its life with nothing
        # in it, and a blank half of a laid-out strip reads as something that
        # failed to draw. It sits between two stretches, so it centers in the
        # space it is explaining while nothing is listed, and the rows still
        # stack from the top once it has given way to them.
        self._hint = QLabel("(queued jobs show up here)")
        self._hint.setObjectName("estimateLabel")  # muted secondary text
        self._rows_box.addWidget(self._hint, 0, Qt.AlignmentFlag.AlignHCenter)
        self._rows_box.addStretch(1)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)  # the line takes the rest of the strip

        self.set_items([])

    # --- what the strip is showing -----------------------------------------

    def running_preview(self) -> RunningPreview:
        """The live half. Its ``key`` is ``None`` when nothing is being made."""
        return self._running

    def rows(self) -> list[QueueRow]:
        """Every job in the line, top to bottom — the one being made first.

        Jobs only: the hint that fills an empty line shares the same box, and it
        is no row — nothing may be dropped in front of it, reordered against it,
        or throw it away with the others on a rebuild.
        """
        return [self._rows_box.itemAt(i).widget()
                for i in range(self._rows_box.count())
                if isinstance(self._rows_box.itemAt(i).widget(), QueueRow)]

    def keys(self) -> list[str]:
        return [row.key for row in self.rows()]

    def set_items(self, items: list, foreign_queued: int = 0):
        """Show ``items`` — every in-flight generation, the one being made first.

        The first drives the live half unless the queue is holding it back: a job
        that cannot start has no frame and no clock, so the half stays free to say
        why instead of showing an empty square over an unmoving bar. Rows already
        listed are refreshed in place; only a change to the *set* of jobs (or
        their order) rebuilds the list, so a poll landing mid-drag doesn't yank the
        row out from under the gesture.

        ``foreign_queued`` is how much of ComfyUI's queue belongs to another app.
        It puts Clear up whenever there is any, and with nothing of ours running
        it is what the free half says — the point being to see that backlog before
        a Generate goes in behind it — after the queue's own hold, which is nearer
        to hand and is ended by closing the show.
        """
        leader = items[0] if items and not items[0].held else None
        self._running.show_item(leader)
        # Nothing of ours in flight at all: the line has no rows to show, so it
        # says what it is for instead.
        self._hint.setVisible(not items)
        self._clear.setVisible(bool(foreign_queued))
        self._clear.setToolTip(
            f"Drop the {foreign_queued} job{'' if foreign_queued == 1 else 's'}"
            " another app has queued on ComfyUI"
        )
        if leader is None:
            self._running.show_foreign(
                queue_held_text(sum(1 for item in items if item.held))
                or foreign_queue_text(foreign_queued) or ""
            )
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
            # What ComfyUI is already rendering cannot be moved, and nothing can
            # be dropped in front of it. Everything else is only waiting — held
            # or not — and its place is the user's to change.
            self._rows_box.insertWidget(
                index, QueueRow(item, movable=item.status != "running")
            )
        # The scroll area would otherwise squeeze the whole line into its own
        # height, stacking the rows on top of each other instead of scrolling.
        self._host.setMinimumHeight(len(items) * QueueRow.HEIGHT)

    # --- moving a job up or down the line -----------------------------------

    def move_row(self, source: int, target: int):
        """Lift the row at ``source`` out and drop it back in at ``target``.

        Re-lists them there and then — the queue's agreement only shows up on a
        later poll, and a row that springs back reads as a failure — then asks for
        that order through :attr:`reorder_requested`. Neither end may be a job
        already being rendered: those keep the front of the line. A move that
        changes nothing asks for nothing.
        """
        order = [item.key for item in self._items]
        first = self._first_movable()
        if not first <= source < len(order) or not first <= target < len(order):
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

    def _first_movable(self) -> int:
        """The first slot a row may be moved to or from — past whatever is already
        being rendered, which nothing can be put in front of."""
        for index, item in enumerate(self._items):
            if item.status != "running":
                return index
        return len(self._items)

    def _drop_index(self, point) -> int:
        """Which slot a drop at ``point`` (in this widget's coordinates) lands in:
        above the row whose top half it fell on, else at the end of the line. Never
        in front of a row already being rendered."""
        for index, row in enumerate(self.rows()):
            middle = row.mapTo(self, row.rect().center())
            if point.y() < middle.y():
                return max(self._first_movable(), index)
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
