"""A slim, always-visible bar for the one generation currently in flight.

ComfyUI runs a single job at a time, so at most one generation is ever executing
(plus any queued behind it). This bar sits at the bottom of the gallery and shows
that job from anywhere in the app — a small live preview, its caption, a progress
bar, a "+N queued" count, and a cancel — so you can watch or stop it without
leaving whatever folder or config tab you're on. Clicking the bar reveals the job
(its config tab or re-roll folder); the ✕ cancels it. It hides when nothing runs.

It's fed the same in-flight view-models the Recents shelf uses
(:class:`InFlightItem`), running-first, refreshed on every poll so its preview and
progress stay live.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QToolButton,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE

_PREVIEW = 40  # a small live thumbnail; the full-size preview is one click away


class RunningJobBar(QWidget):
    """Renders the active in-flight job (running first, else the head of the queue)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("runningJobBar")
        # A raw QWidget paints no stylesheet border without this (see the QWidget
        # stylesheet-border gotcha); a top rule sets the bar off from the panes.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#runningJobBar {{ border-top: 1px solid {BORDER_SUBTLE.name()}; }}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._item: object | None = None

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

        self.hide()  # nothing in flight yet

    def set_items(self, items: list):
        """Show the active job and hide when there's nothing in flight.

        ``items`` is every in-flight generation, running-first; the first is the
        one to display and any others become a "+N queued" count.
        """
        self._item = items[0] if items else None
        if self._item is None:
            self.hide()
            return
        self._render(self._item, queued=len(items) - 1)
        self.show()

    def _render(self, item, queued: int):
        self._caption.setText(item.caption)
        self._render_preview(item.frame)
        self._render_progress(item)
        self._queued.setText(f"+{queued} queued" if queued > 0 else "")
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
        if self._item is not None and self._item.cancel is not None:
            self._item.cancel()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._item is not None:
            self._item.reveal()
