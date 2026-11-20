from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
from shared_ui.palette import TEXT_MUTED, as_hex
from shared_ui.spacing import BUTTON_RADIUS

from origenerator.gui import palette, tile_shape
from origenerator.gui.cancel_bar import CancelBar
from origenerator.gui.combination import Combination
from origenerator.gui.combination_view import combination_pixmap
from origenerator.gui.corner_buttons import CornerButtons, bar_between_the_bottom_corners
from origenerator.gui.generation_job import display_status
from origenerator.gui.inflight import TICK_MS, RunReading, cancel_tooltip
from origenerator.gui.live_frames import pixmap_of
from origenerator.gui.tile_status_scrim import TileStatusScrim

_RESTING_FRAME_CSS = tile_shape.idle_css("generatingTile")
_SELECTED_FRAME_CSS = tile_shape.selected_css("generatingTile")

_IMAGE_SIZE = tile_shape.THUMBNAIL_SIZE
_MADE_FROM_NOTHING = Combination()


class GeneratingTile(QFrame):
    cancel_requested = Signal()
    selected = Signal()
    context_requested = Signal(QPoint)
    control_triggered = Signal(str)

    def __init__(self, job, parent=None, *, name="", populating=False,
                 typical_seconds=None, made_from=_MADE_FROM_NOTHING,
                 favorite=False, enhance=None, kind=None):
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
        self._name = QLabel(name)
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setWordWrap(True)
        tile_shape.style_caption(self._name)
        self._name.setStyleSheet("background-color: transparent;")
        self._name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._image)
        layout.addWidget(self._name)

        self._status_scrim = TileStatusScrim(self)
        self.layout().activate()  # Qt positions the thumbnail only once the layout has run, and the scrim and the bar are laid over where it is
        self._bar = CancelBar(cancel_tooltip(populating), self)
        self._bar.setGeometry(bar_between_the_bottom_corners(self._image.geometry()))
        self._bar.clicked.connect(self.cancel_requested.emit)
        self._controls = CornerButtons(self)
        self._controls.place(self._image.geometry())
        self._controls.triggered.connect(self.control_triggered.emit)
        self._favorite, self._enhance, self._kind = favorite, enhance, kind
        self._controls.show_for(favorite=favorite, enhance=enhance, kind=kind)

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

    @property
    def prompt_id(self) -> str:
        return self._job.prompt_id

    def set_favorite(self, favorite: bool):
        self._favorite = favorite
        self._controls.show_for(favorite=favorite, enhance=self._enhance, kind=self._kind)

    def set_enhance(self, enhance: str | None):
        self._enhance = enhance
        self._controls.show_for(favorite=self._favorite, enhance=enhance, kind=self._kind)

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
        self._controls.place(self._image.geometry())
        self._render_timing()

    def _render_timing(self):
        self._bar.show_progress(self._reading().caption(compact=True),
                                *self._reading().bars())

    def _on_preview(self, data: bytes):
        if (pixmap := pixmap_of(data)) is not None:
            self._image.setPixmap(pixmap.scaled(
                self._image.width(), self._image.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit()
