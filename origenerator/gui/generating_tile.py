from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout
from shared_ui.palette import TEXT_MUTED, as_hex
from shared_ui.spacing import BUTTON_RADIUS

from origenerator.gui import palette, tile_shape
from origenerator.gui.combination import Combination
from origenerator.gui.combination_view import combination_pixmap
from origenerator.gui.generation_job import display_status
from origenerator.gui.inflight import CANCEL_TEXT, TICK_MS, RunReading, cancel_tooltip
from origenerator.gui.progress_bar import BAR_HEIGHT, ProgressBar
from origenerator.gui.tile_status_scrim import TileStatusScrim

_RESTING_FRAME_CSS = tile_shape.idle_css("generatingTile")
_SELECTED_FRAME_CSS = tile_shape.selected_css("generatingTile")

_IMAGE_SIZE = tile_shape.THUMBNAIL_SIZE
_MADE_FROM_NOTHING = Combination()


class GeneratingTile(QFrame):
    cancel_requested = pyqtSignal()
    selected = pyqtSignal()
    context_requested = pyqtSignal(QPoint)

    def __init__(self, job, parent=None, *, populating=False,
                 typical_seconds=None, made_from=_MADE_FROM_NOTHING):
        super().__init__(parent)
        self._job = job
        self._selected = False
        self._typical_seconds = typical_seconds
        self.setObjectName("generatingTile")
        self.setFixedSize(*tile_shape.tile_size())
        self.set_selected(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.mapToGlobal(pos)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tile_shape.TILE_MARGIN,) * 4)
        layout.setSpacing(tile_shape.TILE_SPACING)

        self._image = QLabel()
        self._image.setFixedSize(*_IMAGE_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setStyleSheet(
            f"background: {palette.EMPTY_PLATE}; border-radius: {BUTTON_RADIUS}px; color: {as_hex(TEXT_MUTED)};"
        )
        layout.addWidget(self._image)

        self._cancel = QPushButton(CANCEL_TEXT)
        self._cancel.setToolTip(cancel_tooltip(populating))
        self._cancel.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self._cancel)

        self._status_scrim = TileStatusScrim(self)
        self._bar = ProgressBar(self)
        self._bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._place_bar()

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

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setStyleSheet(_SELECTED_FRAME_CSS if selected else _RESTING_FRAME_CSS)

    def _reading(self) -> RunReading:
        return RunReading(
            status=display_status(self._job.state), frame=self._job.last_preview,
            progress=self._job.last_progress,
            pass_progress=self._job.last_pass_progress,
            stage=self._job.last_stage, started_at=self._job.started_at,
            typical_seconds=self._typical_seconds,
        )

    def _render_state(self, *_):
        self._status_scrim.cover(
            self._image,
            "Generating…" if self._reading().rendering else "Waiting…",
        )
        self._bar.raise_()
        self._render_timing()

    def _render_timing(self):
        self._bar.show_progress(self._reading().caption(compact=True),
                                *self._reading().bars())

    def _place_bar(self):
        # Qt: the thumbnail is positioned only once the layout has run, so force it; a bar placed before sits in the top-left corner
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
