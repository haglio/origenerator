"""A slim, always-visible bar for the one generation currently in flight.

ComfyUI runs a single job at a time, so at most one generation is ever executing
(plus any queued behind it). This bar sits at the bottom of the gallery and shows
that job from anywhere in the app — a small live preview, its caption, a progress
bar, a "+N queued" count, and a cancel — so you can watch or stop it without
leaving whatever folder or config tab you're on. Clicking the bar reveals the job
(its config tab or re-roll folder); the ✕ cancels it.

It also speaks for the *shared* ComfyUI, which is what makes it worth watching
when none of the work is ours. The server outlives whatever queued on it, so its
queue can hold a batch no window here can account for; the bar names that backlog
and offers a Clear for it, so a queue full of somebody else's jobs is something
you see before pressing Generate rather than something Generate discovers. With
neither a job nor a foreign backlog it keeps its slot but blanks — reserving the
space so a job appearing never shifts the panes above it.

It's fed the same in-flight view-models the Recents shelf uses
(:class:`InFlightItem`), running-first, refreshed on every poll so its preview and
progress stay live.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QToolButton,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.inflight_card import foreign_queue_text, queue_wait_text
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE

_PREVIEW = 40  # a small live thumbnail; the full-size preview is one click away


class RunningJobBar(QWidget):
    """Renders the active in-flight job (running first, else the head of the queue)."""

    clear_queue_requested = pyqtSignal()  # wipe another app's work off ComfyUI

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("runningJobBar")
        # A raw QWidget paints no stylesheet border without this (see the QWidget
        # stylesheet-border gotcha); a top rule sets the bar off from the panes.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#runningJobBar {{ border-top: 1px solid {BORDER_SUBTLE.name()}; }}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._item: object | None = None
        self._foreign = 0  # jobs another app has on ComfyUI, as of the last feed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
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

        self._queued = QLabel()
        self._queued.setObjectName("estimateLabel")  # muted secondary text
        layout.addWidget(self._queued)

        # Only ever offered for another app's work — the user's own queue is
        # what they asked for, and each of those has its own ✕ already.
        self._clear = QToolButton()
        self._clear.setText("Clear")
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.clicked.connect(self.clear_queue_requested)
        layout.addWidget(self._clear)

        self._cancel = QToolButton()
        self._cancel.setText("✕")
        self._cancel.setToolTip("Cancel this generation")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)

        # Let clicks on the labels/preview/progress fall through to the bar (which
        # reveals the job); only the cancel button handles its own click.
        for child in (self._preview, self._caption, self._progress, self._queued):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._show_idle()  # nothing in flight yet — hold the slot, but blank

    def set_items(self, items: list, foreign_queued: int = 0):
        """Show the active job, or what else is on ComfyUI, or blank the bar.

        ``items`` is every in-flight generation, running-first; the first is the
        one to display and any others become a "+N queued" count.
        ``foreign_queued`` is how much of ComfyUI's queue belongs to another app:
        it puts the Clear button up whenever there's any, and when nothing of
        ours is in flight it's the one thing the bar has to say — the whole point
        being to see that backlog before a Generate goes in behind it.
        """
        self._foreign = foreign_queued
        self._item = items[0] if items else None
        if self._item is not None:
            self._render(self._item, queued=len(items) - 1)
        elif foreign_queued:
            self._show_foreign(foreign_queued)
        else:
            self._show_idle()

    def _show_idle(self):
        """Blank the bar but keep its slot, so a job appearing doesn't shift the
        panes. The fixed-size preview holds the height; everything else clears."""
        self._caption.clear()
        self._preview.clear()
        self._queued.clear()
        self._progress.hide()
        self._cancel.hide()
        self._clear.hide()
        self.setCursor(Qt.CursorShape.ArrowCursor)  # nothing to reveal on click

    def _show_foreign(self, total: int):
        """Nothing of ours in flight, but ComfyUI isn't free: say whose work is on
        it and offer to clear it, rather than look idle right up until a submit
        lands behind the pile."""
        self._caption.setText(foreign_queue_text(total) or "")
        self._preview.clear()
        self._queued.clear()
        self._progress.hide()
        self._cancel.hide()
        self._sync_clear()
        self.setCursor(Qt.CursorShape.ArrowCursor)  # no job of ours to reveal

    def _render(self, item, queued: int):
        self._caption.setText(item.caption)
        self._render_preview(item.frame)
        self._progress.show()
        self._render_progress(item)
        self._queued.setText(self._waiting_text(item, queued))
        self._cancel.setVisible(item.cancel is not None)
        self._sync_clear()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _sync_clear(self):
        """Show the Clear button only while there's another app's work to clear,
        and let its tooltip carry the count — beside a running job the caption is
        that job's own title, so the button needs to say what it acts on."""
        self._clear.setVisible(bool(self._foreign))
        self._clear.setToolTip(
            f"Drop the {self._foreign} job{'' if self._foreign == 1 else 's'}"
            " another app has queued on ComfyUI (your own are left alone)"
        )

    def _waiting_text(self, item, queued: int) -> str:
        """What else is in the way. Another app's hold on ComfyUI wins when there is
        one — that's the wait nothing else here can explain. Otherwise this app's own
        count of what it has queued behind the shown job, which needs no explaining:
        the user asked for those, and the first of them is the one on screen."""
        return queue_wait_text(item.foreign_ahead) or (
            f"+{queued} queued" if queued > 0 else ""
        )

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
        if event.button() == Qt.MouseButton.LeftButton and self._item is not None:
            self._item.reveal()
