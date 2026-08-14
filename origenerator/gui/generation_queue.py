"""The generation queue, as one strip along the bottom of the gallery.

ComfyUI renders one thing at a time, so the strip is shaped like that: a single
fat progress row for the job actually being made — its live frame, its caption,
its bar, its Cancel — and, to the right of it, the line waiting behind it as a
compact scrollable list. The whole strip is one progress row tall, so a queue of
any length costs the panes above it nothing; about two waiting entries show at a
time and the rest are a scroll away.

Every waiting entry carries a Cancel of its own (the word, because a config tab's
Cancel stops the same job and they should read the same), opens that job's
settings as a tab in the generate pane when clicked, and can be dragged to a new
place in the line.

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
from PyQt6.QtGui import QPixmap, QDrag
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal

from origenerator.gui.inflight import InFlightItem, queue_wait_text
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE

_PREVIEW = 40   # a small live thumbnail; the full-size preview is one click away
_WAITING_WIDTH = 300  # how much of the strip the line behind takes
# Marks a drag as one of our own rows, so a thumbnail dragged from the gallery
# (which carries its own type) can't be dropped into the queue as a reorder.
QUEUE_ROW_MIME = "application/x-origenerator-queue-row"
# A job that never runs, whose row is measured once to fix the strip's height —
# so an empty strip reserves exactly the space a real one takes.
_BLANK_ITEM = InFlightItem(key="", caption="", status="queued", frame=None,
                           reveal=lambda: None)


def _cancel_button(text_height: int) -> QPushButton:
    """A compact Cancel, sized to ride inside a row of ``text_height`` pixels."""
    button = QPushButton("Cancel")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip("Cancel this generation")
    button.setStyleSheet(f"padding: 0px 6px; font-size: {max(9, text_height - 10)}px;")
    button.setFixedHeight(text_height)
    return button


class RunningRow(QWidget):
    """The job being made right now: live frame, caption, fat progress bar, Cancel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None
        self._item = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self._preview = QLabel()
        self._preview.setFixedSize(_PREVIEW, _PREVIEW)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._preview)

        middle = QVBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(2)
        self._caption = QLabel()
        middle.addWidget(self._caption)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(14)  # the fat, important one
        middle.addWidget(self._progress)
        layout.addLayout(middle, 1)

        self._wait = QLabel()
        self._wait.setObjectName("estimateLabel")  # muted secondary text
        layout.addWidget(self._wait)

        self._cancel = _cancel_button(24)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)

        # A click anywhere but the button belongs to the row, which opens the
        # job's tab; the labels and the bar are decoration, not targets.
        for child in (self._preview, self._caption, self._progress, self._wait):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.show_item(None)

    def caption(self) -> str:
        return self._caption.text()

    def show_item(self, item):
        """Render ``item``, or blank the row (keeping its space) when nothing runs."""
        self._item = item
        self.key = item.key if item is not None else None
        if item is None:
            self._caption.clear()
            self._preview.clear()
            self._wait.clear()
            self._progress.hide()
            self._cancel.hide()
            self.setCursor(Qt.CursorShape.ArrowCursor)  # nothing to open on a click
            return
        self._caption.setText(item.caption)
        self._render_preview(item.frame)
        self._progress.show()
        self._render_progress(item)
        # Only another app's hold needs saying: the user's own wait is the list
        # beside this row, which is right there to read.
        self._wait.setText(queue_wait_text(item.foreign_ahead) or "")
        self._cancel.setVisible(item.cancel is not None)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _render_preview(self, frame):
        pixmap = QPixmap()
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            self._preview.setPixmap(pixmap.scaled(
                _PREVIEW, _PREVIEW, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._preview.clear()  # no frame yet — a blank square, not a stale one

    def _render_progress(self, item):
        if item.status == "running" and item.progress and item.progress[1] > 0:
            cumulative, total = item.progress
            self._progress.setRange(0, total)
            self._progress.setValue(cumulative)
        else:
            self._progress.setRange(0, 0)  # queued, or no step counts yet: indeterminate

    def _on_cancel(self):
        if self._item is not None and self._item.cancel is not None:
            self._item.cancel()

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._item is not None and self._item.open_config is not None):
            self._item.open_config()


class QueuedRow(QWidget):
    """One job waiting its turn: a line of caption and Cancel, draggable.

    A press-and-release opens the job's config tab; a press that travels starts a
    drag, which the strip turns into a reorder.
    """

    HEIGHT = 26  # about two of these fit beside the progress row

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.key = item.key
        self._press_at = None  # where a left press landed, until it clicks or drags
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(6)
        self._caption = QLabel()
        self._caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._caption, 1)
        self._cancel = _cancel_button(self.HEIGHT - 6)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)

        self.update_item(item)

    def caption(self) -> str:
        return self._caption.text()

    def update_item(self, item):
        """Re-render this entry in place — a queued→running flip, a fresh caption."""
        self._item = item
        # Another app's hold is the one wait worth naming; the user's own place in
        # the line is the line itself.
        self._caption.setText(queue_wait_text(item.foreign_ahead) or item.caption)
        self._cancel.setVisible(item.cancel is not None)

    def _on_cancel(self):
        if self._item.cancel is not None:
            self._item.cancel()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.position().toPoint()

    def mouseMoveEvent(self, event):
        """A press that travels far enough becomes a drag, carrying this row's id."""
        if self._press_at is None:
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
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        if self._press_at is not None and self._item.open_config is not None:
            self._item.open_config()
        self._press_at = None


class GenerationQueue(QWidget):
    """One progress row for what is being made, and the line waiting beside it."""

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
        self._waiting: list = []   # the items behind the one being made, in order

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        self._running = RunningRow()
        layout.addWidget(self._running, 1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedWidth(_WAITING_WIDTH)
        self._scroll.setFixedHeight(self._running.sizeHint().height())
        self._host = QWidget()
        self._rows_box = QVBoxLayout(self._host)
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        self._rows_box.addStretch(1)  # entries stack from the top
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll)

        self.set_items([])

    # --- what the strip is showing -----------------------------------------

    def running_row(self) -> RunningRow:
        """The progress row. Its ``key`` is ``None`` when nothing is being made."""
        return self._running

    def queued_rows(self) -> list[QueuedRow]:
        """The waiting entries, top to bottom."""
        return [self._rows_box.itemAt(i).widget()
                for i in range(self._rows_box.count())
                if self._rows_box.itemAt(i).widget() is not None]

    def keys(self) -> list[str]:
        """Every job on the strip, the one being made first."""
        leading = [self._running.key] if self._running.key is not None else []
        return leading + [row.key for row in self.queued_rows()]

    def set_items(self, items: list):
        """Show ``items`` — every in-flight generation, leading job first.

        The first goes in the progress row and the rest form the line beside it.
        Entries already listed are refreshed in place; only a change to the *set*
        of waiting jobs (or their order) rebuilds the list, so a poll landing
        mid-drag doesn't yank the row out from under the gesture.
        """
        self._running.show_item(items[0] if items else None)
        waiting = list(items[1:])
        if [row.key for row in self.queued_rows()] != [item.key for item in waiting]:
            self._rebuild(waiting)
            return
        self._waiting = waiting
        for row, item in zip(self.queued_rows(), waiting):
            row.update_item(item)

    def _rebuild(self, waiting: list):
        self._waiting = list(waiting)
        for row in self.queued_rows():
            self._rows_box.removeWidget(row)
            row.deleteLater()
        for index, item in enumerate(waiting):
            self._rows_box.insertWidget(index, QueuedRow(item))
        # The scroll area would otherwise squeeze the whole line into its own
        # height, stacking the entries on top of each other instead of scrolling.
        self._host.setMinimumHeight(len(waiting) * QueuedRow.HEIGHT)

    # --- moving a waiting job up or down the line ---------------------------

    def move_queued(self, source: int, target: int):
        """Lift the waiting entry at ``source`` out and drop it back in at ``target``.

        Re-lists them there and then — ComfyUI's agreement only shows up on a later
        poll, and a row that springs back reads as a failure — then asks for that
        order through :attr:`reorder_requested`, the job being made still first
        (nothing can be moved in front of what is already rendering). A move that
        changes nothing asks for nothing.
        """
        order = [item.key for item in self._waiting]
        if not 0 <= source < len(order) or not 0 <= target < len(order):
            return
        moved = list(self._waiting)
        moved.insert(target, moved.pop(source))
        if [item.key for item in moved] == order:
            return
        self._rebuild(moved)
        self.reorder_requested.emit(self.keys())

    # --- accepting a dragged row --------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(QUEUE_ROW_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(QUEUE_ROW_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Land a dragged entry wherever in the line it was let go."""
        if not event.mimeData().hasFormat(QUEUE_ROW_MIME):
            return
        key = bytes(event.mimeData().data(QUEUE_ROW_MIME)).decode()
        keys = [item.key for item in self._waiting]
        if key not in keys:
            return
        source = keys.index(key)
        target = self._drop_index(event.position().toPoint())
        # The insertion point was read with the dragged entry still in place, so a
        # drop below it names a slot one further along than it will end up in.
        self.move_queued(source, target - 1 if target > source else target)
        event.acceptProposedAction()

    def _drop_index(self, point) -> int:
        """Which slot a drop at ``point`` (in this widget's coordinates) lands in:
        above the entry whose top half it fell on, else at the end of the line."""
        for index, row in enumerate(self.queued_rows()):
            middle = row.mapTo(self, row.rect().center())
            if point.y() < middle.y():
                return index
        return len(self.queued_rows())
