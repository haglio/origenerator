"""The whole generation queue, on screen wherever the user is.

ComfyUI executes one prompt at a time, so a batch of Generates becomes a line —
one running, the rest waiting their turn. This strip sits at the bottom of the
gallery and lists every one of them, in the order ComfyUI will work through them,
reachable from any folder or config tab. Each row shows that job's live preview
frame, its caption and its progress, and carries a Cancel of its own — the word,
because a config tab's Cancel stops the same job and they should read the same.
Clicking a row opens that job's settings as a tab in the generate pane; dragging
one moves it in the queue.

When nothing runs the strip keeps its slot but empties — reserving the space so a
job appearing never shifts the panes above it — and past ``_MAX_VISIBLE_ROWS`` it
scrolls rather than growing into them.

It's fed the same in-flight view-models the Recents shelf uses
(:class:`origenerator.gui.inflight.InFlightItem`), refreshed on every poll so
previews and progress stay live; a refresh updates rows in place, so a drag is never yanked
out from under the user. Reordering is asked for, not done here:
:attr:`reorder_requested` carries the order the rows were dropped into, and
whoever owns the jobs makes ComfyUI agree.
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
_MAX_VISIBLE_ROWS = 3  # past this the strip scrolls instead of eating the panes
# Marks a drag as one of our own rows, so a thumbnail dragged from the gallery
# (which carries its own type) can't be dropped into the queue as a reorder.
QUEUE_ROW_MIME = "application/x-origenerator-queue-row"
# A job that never runs, whose row is measured once to fix the height of every
# row — so an empty strip reserves exactly the space a real one takes.
_BLANK_ITEM = InFlightItem(key="", caption="", status="queued", frame=None,
                           reveal=lambda: None)


class QueueRow(QWidget):
    """One queued or running generation: preview, caption, progress, Cancel.

    A press-and-release opens the job's config tab; a press that travels starts a
    drag, which the strip turns into a reorder.
    """

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.key = item.key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._press_at = None  # where a left press landed, until it clicks or drags

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
        self._progress.setFixedHeight(8)
        middle.addWidget(self._progress)
        layout.addLayout(middle, 1)

        self._wait = QLabel()
        self._wait.setObjectName("estimateLabel")  # muted secondary text
        layout.addWidget(self._wait)

        self._cancel = QPushButton("Cancel")
        self._cancel.setStyleSheet("padding: 2px 8px;")  # compact: it rides in a row
        self._cancel.setToolTip("Cancel this generation")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)

        # Let a press anywhere but the button reach the row; the labels and the bar
        # are decoration, not targets of their own.
        for child in (self._preview, self._caption, self._progress, self._wait):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.update_item(item)

    def caption(self) -> str:
        return self._caption.text()

    def update_item(self, item):
        """Re-render this row from a fresh descriptor — a new live frame, a
        queued→running flip — without rebuilding the widget."""
        self._item = item
        self._caption.setText(item.caption)
        self._render_preview(item.frame)
        self._render_progress(item)
        # Only another app's hold needs saying. The user's own wait is the rest of
        # this list, which is right there to read.
        self._wait.setText(queue_wait_text(item.foreign_ahead) or "")
        self._cancel.setVisible(item.cancel is not None)

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
        if self._item.cancel is not None:
            self._item.cancel()

    # --- click to open the job's tab, drag to move it -----------------------

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
    """Every in-flight generation as a draggable row, in the order they will run."""

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._rows_box = QVBoxLayout(self._host)
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        self._rows_box.addStretch(1)  # rows stack from the top
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll)

        self._row_height = QueueRow(_BLANK_ITEM).sizeHint().height()
        self._rebuild([])

    # --- what the strip is showing -----------------------------------------

    def rows(self) -> list[QueueRow]:
        """The row widgets, top to bottom."""
        return [self._rows_box.itemAt(i).widget()
                for i in range(self._rows_box.count())
                if self._rows_box.itemAt(i).widget() is not None]

    def set_items(self, items: list):
        """Show ``items`` — every in-flight generation, in the order they will run.

        Rows for jobs already listed are refreshed in place; only a change to the
        *set* of jobs (or their order) rebuilds the strip, so a poll landing
        mid-drag doesn't yank the row out from under the gesture.
        """
        if [row.key for row in self.rows()] != [item.key for item in items]:
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
            self._rows_box.insertWidget(index, QueueRow(item))
        self._scroll.setFixedHeight(
            self._row_height * max(1, min(len(items), _MAX_VISIBLE_ROWS))
        )

    # --- moving a row to a new place in the queue ---------------------------

    def move_row(self, source: int, target: int):
        """Lift the row at ``source`` out and drop it back in at ``target``.

        Re-lists the rows there and then — ComfyUI's agreement only shows up on a
        later poll, and a row that springs back reads as a failure — then asks for
        that order through :attr:`reorder_requested`. A move that changes nothing
        asks for nothing.
        """
        order = [item.key for item in self._items]
        if not 0 <= source < len(order) or not 0 <= target < len(order):
            return
        moved = list(self._items)
        moved.insert(target, moved.pop(source))
        if [item.key for item in moved] == order:
            return
        self._rebuild(moved)
        self.reorder_requested.emit([item.key for item in moved])

    # --- accepting a dragged row --------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(QUEUE_ROW_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(QUEUE_ROW_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Land a dragged row wherever it was let go."""
        if not event.mimeData().hasFormat(QUEUE_ROW_MIME):
            return
        key = bytes(event.mimeData().data(QUEUE_ROW_MIME)).decode()
        keys = [item.key for item in self._items]
        if key not in keys:
            return
        source = keys.index(key)
        target = self._drop_index(event.position().toPoint())
        # The insertion point was read with the dragged row still in place, so a
        # drop below it names a slot one further along than it will end up in.
        self.move_row(source, target - 1 if target > source else target)
        event.acceptProposedAction()

    def _drop_index(self, point) -> int:
        """Which slot a drop at ``point`` (in this widget's coordinates) lands in:
        above the row whose top half it fell on, else at the very end."""
        for index, row in enumerate(self.rows()):
            middle = row.mapTo(self, row.rect().center())
            if point.y() < middle.y():
                return index
        return len(self.rows())
