"""A settings folder's generating tile: the run in front of its line, beside the
folder's ``+`` rather than in its place.

It shows the run the way every other in-flight surface does: ComfyUI's preview —
or, until there is one, what the run is made from
(:func:`~origenerator.gui.combination_view.combination_pixmap`) — under a scrim
naming the stage, a bar along the picture's foot reading
:func:`origenerator.timing.progress_status_label`, and a button that throws the
run away (:func:`inflight.discard_run_text`).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from origenerator.gui import grid_card, palette
from origenerator.gui.combination import Combination
from origenerator.gui.combination_view import combination_pixmap
from origenerator.gui.inflight import TICK_MS, RunReading, discard_run_text, discard_run_tooltip
from origenerator.gui.progress_caption import BAR_HEIGHT, ProgressCaption
from origenerator.gui.stage_scrim import StageScrim

_RESTING_FRAME_CSS = grid_card.idle_css("generatingTile")
_SELECTED_FRAME_CSS = grid_card.selected_css("generatingTile")

_IMAGE_SIZE = grid_card.PICTURE_SIZE


class GeneratingTile(QFrame):
    cancel_requested = pyqtSignal()
    selected = pyqtSignal()  # clicked, to drive the info pane
    context_requested = pyqtSignal(QPoint)  # global position

    def __init__(self, job, parent=None, *, auto_generating=False,
                 typical_seconds=None, made_from=Combination()):
        """``typical_seconds`` is what this folder's workflow usually takes, so the
        bar can say how much of the run is left; ``None`` where there is no
        history to say it from. ``made_from`` stands in the plate until the run
        streams a frame of its own."""
        super().__init__(parent)
        self._job = job
        self._selected = False
        self._typical_seconds = typical_seconds
        self.setObjectName("generatingTile")
        self.setFixedSize(*grid_card.card_size())
        self.set_selected(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.mapToGlobal(pos)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(grid_card.CARD_MARGIN,) * 4)
        layout.setSpacing(grid_card.CARD_SPACING)

        self._image = QLabel()
        self._image.setFixedSize(*_IMAGE_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setStyleSheet(
            f"background: {palette.EMPTY_PLATE}; border-radius: 3px; color: #8a8a8a;"
        )
        layout.addWidget(self._image)

        self._cancel = QPushButton(discard_run_text(auto_generating))
        self._cancel.setToolTip(discard_run_tooltip(auto_generating))
        self._cancel.clicked.connect(lambda: self.cancel_requested.emit())
        layout.addWidget(self._cancel)

        # Both ride over the picture rather than taking a row of their own, so the
        # tile is the same size and shape as every card beside it.
        self._scrim = StageScrim(self)
        self._bar = ProgressCaption(self)
        self._bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._place_bar()

        # Its own clock rather than the gallery's poll, so the count advances a
        # second at a time whether or not a refresh has landed.
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        job.started.connect(self._render_state)
        job.progress.connect(self._render_state)
        job.preview.connect(self._on_preview)
        if job.last_preview:
            self._on_preview(job.last_preview)
        else:
            pair = combination_pixmap(made_from, QSize(*_IMAGE_SIZE))
            if pair is not None:
                self._image.setPixmap(pair)
        self._render_state()
        self._tick.start()

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Fill the tile with the selected blue when it drives the info pane."""
        self._selected = selected
        self.setStyleSheet(_SELECTED_FRAME_CSS if selected else _RESTING_FRAME_CSS)

    def _reading(self) -> RunReading:
        return RunReading(
            status=self._job.state, frame=self._job.last_preview,
            progress=self._job.last_progress,
            pass_progress=self._job.last_pass_progress,
            stage=self._job.last_stage, started_at=self._job.started_at,
            typical_seconds=self._typical_seconds,
        )

    def _render_state(self, *_):
        # The numbers are read back off the job rather than taken from a signal:
        # the tile's own clock re-renders on a tick that carries none, and both
        # paths must draw the same line.
        self._scrim.cover(
            self._image,
            "Generating…" if self._reading().rendering else "Waiting…",
        )
        self._bar.raise_()  # the scrim it sits on was just raised over everything
        self._render_timing()

    def _render_timing(self):
        """A job ComfyUI hasn't started has no elapsed time and no steps to
        report, so the bar stays indeterminate with nothing written on it: its
        wait is the strip's queue to explain."""
        self._bar.show_progress(self._reading().caption(compact=True),
                                *self._reading().bars())

    def _place_bar(self):
        """The picture is only positioned once the tile's layout has run, so that
        is forced here — a bar placed before it sits in the tile's top-left
        corner."""
        self.layout().activate()
        frame = self._image.geometry()
        self._bar.setGeometry(QRect(
            frame.x(), frame.y() + frame.height() - BAR_HEIGHT,
            frame.width(), BAR_HEIGHT,
        ))

    def _on_preview(self, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data) and not pixmap.isNull():
            self._image.setPixmap(pixmap.scaled(
                self._image.width(), self._image.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit()
