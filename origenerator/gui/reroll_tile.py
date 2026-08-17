"""The trailing tile in a gallery settings folder: re-roll a new variation.

Idle, it is a ``+`` box that asks for a fresh generation of the folder's
settings with a new seed. Bound to a running :class:`GenerationJob`, it shows
that job's live state — waiting in the queue, then a progress percentage and
ComfyUI's in-progress preview — with a button that throws that run away, reading
"Cancel" or, while the folder is auto-generating, "Next seed" (see
:func:`inflight.discard_run_text`). The tile is rebuilt whenever the gallery
re-renders, so it reads the job's cached state on construction rather than
relying solely on future signals.
"""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.inflight import discard_run_text, discard_run_tooltip

# Idle/active resting look (a dashed "+" box) versus the solid border that marks
# the tile as the selected item driving the info pane, mirroring a thumbnail.
_IDLE_FRAME_CSS = (
    "#rerollTile { border: 1px dashed #4a4a4a; border-radius: 4px; }"
    "#rerollTile:hover { border-color: #6f6f6f; }"
)
_SELECTED_FRAME_CSS = "#rerollTile { border: 2px solid #8a8a8a; border-radius: 4px; }"


class RerollTile(QFrame):
    add_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    selected = pyqtSignal()  # a running tile was clicked to drive the info pane

    def __init__(self, job=None, parent=None, *, auto_generating=False):
        super().__init__(parent)
        self._job = job
        self._selected = False
        self.setObjectName("rerollTile")
        self.setFixedSize(180, 200)
        self.set_selected(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._image = QLabel()
        self._image.setFixedSize(166, 150)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._image)

        self._status = QLabel()
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setMaximumHeight(28)
        layout.addWidget(self._status)

        self._cancel = QPushButton(discard_run_text(auto_generating))
        self._cancel.setToolTip(discard_run_tooltip(auto_generating))
        self._cancel.clicked.connect(lambda: self.cancel_requested.emit())
        layout.addWidget(self._cancel)

        if job is None:
            self._show_idle()
        else:
            self._bind(job)

    def _show_idle(self):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._image.setStyleSheet(
            "color: #6f6f6f; font-size: 56px; background: #2a2a2a; border-radius: 3px;"
        )
        self._image.setText("+")
        self._status.setText("New (random seed)")
        self._cancel.hide()

    def _bind(self, job):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._image.setStyleSheet(
            "background: #2a2a2a; border-radius: 3px; color: #8a8a8a;"
        )
        self._cancel.show()
        job.started.connect(self._on_started)
        job.progress.connect(self._on_progress)
        job.preview.connect(self._on_preview)

        if job.last_preview:
            self._on_preview(job.last_preview)
        if job.state == "running":
            self._render_running(*job.last_progress)
        else:
            self._render_waiting()

    # --- selection ---------------------------------------------------------

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Give the tile a solid selection border when it drives the info pane,
        else restore the dashed resting look."""
        self._selected = selected
        self.setStyleSheet(_SELECTED_FRAME_CSS if selected else _IDLE_FRAME_CSS)

    # --- state rendering ---------------------------------------------------

    def _has_image(self) -> bool:
        return not self._image.pixmap().isNull()

    def _render_waiting(self):
        self._status.setText("Waiting…")
        if not self._has_image():
            self._image.setText("Queued")

    def _render_running(self, value: int = 0, max_val: int = 0):
        pct = f" {int(value * 100 / max_val)}%" if max_val else ""
        self._status.setText(f"Generating…{pct}")
        if not self._has_image():
            self._image.setText("Generating…")

    def _on_started(self):
        self._render_running(*self._job.last_progress)

    def _on_progress(self, value: int, max_val: int):
        self._render_running(value, max_val)

    def _on_preview(self, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data) and not pixmap.isNull():
            self._image.setPixmap(pixmap.scaled(
                self._image.width(), self._image.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # An idle "+" tile starts a re-roll; a running tile selects itself so the
        # info pane can show its live preview at full size.
        if self._job is None:
            self.add_requested.emit()
        else:
            self.selected.emit()
