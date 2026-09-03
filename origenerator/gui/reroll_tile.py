"""The trailing tile in a gallery settings folder: re-roll a new variation.

Idle, it is a ``+`` box that asks for a fresh generation of the folder's
settings with a new seed. Bound to a running :class:`GenerationJob`, it shows
that job's live state the way every other in-flight surface does: ComfyUI's
in-progress preview with a dimming scrim over it naming the stage
("Waiting…", then "Generating…"), and a bar along the picture's foot carrying
how far along the run is and how long that has taken
(:func:`origenerator.timing.progress_status_label`) — the same reading, in the
same words, as the bottom strip's queue and the Recents shelf's cards. Beside
them a button throws that run away, reading "Cancel" or, while the folder is
auto-generating, "Next seed" (see :func:`inflight.discard_run_text`).

The tile is rebuilt whenever the gallery re-renders, so it reads the job's
cached state on construction rather than relying solely on future signals.
"""

import time

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QRect, QSize, QTimer, pyqtSignal

from origenerator.gui import grid_card
from origenerator.gui.blurred import blurred_backdrop
from origenerator.gui.inflight import discard_run_text, discard_run_tooltip
from origenerator.gui.progress_caption import ProgressCaption
from origenerator.gui.stage_scrim import StageScrim
from origenerator.timing import progress_status_label

# The dashed resting box and the solid selected border are the family look every
# non-picture card in the grid wears (see :mod:`origenerator.gui.grid_card`).
_IDLE_FRAME_CSS = grid_card.idle_css("rerollTile")
_SELECTED_FRAME_CSS = grid_card.selected_css("rerollTile")

_IMAGE_SIZE = grid_card.PICTURE_SIZE
_BAR_HEIGHT = 26  # the bar laid along the frame's foot, the way a player's is
# How often the tile re-reads the clock. Its own timer rather than the gallery's
# poll, which would make a seconds count skip every other tick.
_TICK_MS = 1000


class RerollTile(QFrame):
    add_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    selected = pyqtSignal()  # a running tile was clicked to drive the info pane

    def __init__(self, job=None, parent=None, *, auto_generating=False,
                 typical_seconds=None, source_picture=None):
        """``typical_seconds`` is what this folder's workflow usually takes, so a
        bound job's bar can say how much of its run is left; ``None`` where there
        is no history to say it from. ``source_picture`` is a file showing what
        the bound run came from, stood blurred behind the wait until the run
        streams a frame of its own."""
        super().__init__(parent)
        self._job = job
        self._source_picture = source_picture
        self._selected = False
        self._typical_seconds = typical_seconds
        self.setObjectName("rerollTile")
        self.setFixedSize(*grid_card.card_size())
        self.set_selected(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(grid_card.CARD_MARGIN,) * 4)
        layout.setSpacing(grid_card.CARD_SPACING)

        self._image = QLabel()
        self._image.setFixedSize(*_IMAGE_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._image)

        # What the idle tile offers. A bound job says its stage on the scrim over
        # the picture instead, so this stands down rather than repeating it in
        # smaller letters underneath.
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        grid_card.style_caption(self._status)  # the grid's shared caption size
        layout.addWidget(self._status)

        self._cancel = QPushButton(discard_run_text(auto_generating))
        self._cancel.setToolTip(discard_run_tooltip(auto_generating))
        self._cancel.clicked.connect(lambda: self.cancel_requested.emit())
        layout.addWidget(self._cancel)

        # Both ride over the picture rather than taking a row of their own, so a
        # running tile is the same size and shape as the idle one it replaced.
        self._scrim = StageScrim(self)
        self._bar = ProgressCaption(self)
        self._bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._bar.hide()

        # Its own clock rather than the gallery's poll, so the count advances a
        # second at a time whether or not a refresh has landed.
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        if job is None:
            self._show_idle()
        else:
            self._bind(job)

    def _show_idle(self):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._image.setStyleSheet(grid_card.glyph_css())
        self._image.setText("+")
        self._status.setText("New (random seed)")
        self._cancel.hide()

    def _bind(self, job):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._image.setStyleSheet(
            "background: #2a2a2a; border-radius: 3px; color: #8a8a8a;"
        )
        self._status.hide()  # the scrim over the picture says the stage now
        self._cancel.show()
        self._bar.show()
        self._place_overlays()
        job.started.connect(self._on_started)
        job.progress.connect(self._on_progress)
        job.preview.connect(self._on_preview)

        if job.last_preview:
            self._on_preview(job.last_preview)
        else:
            backdrop = blurred_backdrop(self._source_picture, QSize(*_IMAGE_SIZE))
            if backdrop is not None:
                self._image.setPixmap(backdrop)
        self._render_state()
        self._tick.start()

    # --- selection ---------------------------------------------------------

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Give the tile a solid selection border when it drives the info pane,
        else restore the dashed resting look."""
        self._selected = selected
        self.setStyleSheet(_SELECTED_FRAME_CSS if selected else _IDLE_FRAME_CSS)

    # --- state rendering ---------------------------------------------------

    def _render_state(self):
        """Name the stage on the scrim and write the run's reading on the bar."""
        self._scrim.cover(
            self._image,
            "Generating…" if self._job.state == "running" else "Waiting…",
        )
        self._bar.raise_()  # the scrim it sits on was just raised over everything
        self._render_timing()

    def _render_timing(self):
        """How far along the bound run is, how long it has been going and how much
        longer it has — written across the bar at the picture's foot.

        A job ComfyUI hasn't started has no elapsed time and no steps to report, so
        the bar stays indeterminate with nothing written on it: its wait is the
        strip's queue to explain, not a zero counting up over a bar that hasn't
        moved.
        """
        started = self._job.started_at
        elapsed = None if started is None else max(0.0, time.time() - started)
        progress = self._job.last_progress
        self._bar.show_progress(
            # A tile's width takes the compact reading: how far along, and how
            # much longer. The strip's queue has the room for the elapsed count.
            progress_status_label(elapsed, progress, self._typical_seconds,
                                  compact=True),
            progress if self._job.state == "running" else None,
            (self._job.last_pass_progress
             if self._job.state == "running" else None),
        )

    def _place_overlays(self):
        """Lay the bar along the picture's foot. The picture is only positioned
        once the tile's layout has run, so that is forced here rather than waited
        for — an overlay placed before it sits in the tile's top-left corner."""
        self.layout().activate()
        frame = self._image.geometry()
        self._bar.setGeometry(QRect(
            frame.x(), frame.y() + frame.height() - _BAR_HEIGHT,
            frame.width(), _BAR_HEIGHT,
        ))

    def _on_started(self):
        self._render_state()

    def _on_progress(self, *_):
        # The numbers are read back off the job rather than taken from the signal:
        # the tile's own clock re-renders on a tick that carries none, and both
        # paths must draw the same line.
        self._render_state()

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
