from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.spacing import BUTTON_RADIUS

from origenerator.gui import icons, palette, tile_shape
from origenerator.gui.blurred import blurred_backdrop
from origenerator.gui.cancel_bar import CancelBar
from origenerator.gui.corner_buttons import CornerButtons, bar_between_the_bottom_corners
from origenerator.gui.inflight import TICK_MS, InFlightItem, cancel_tooltip, queue_wait_text
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.tile_status_scrim import TileStatusScrim

_IMAGE_SIZE = tile_shape.THUMBNAIL_SIZE
_BORDER_PX = 2
_BORDER = f"{_BORDER_PX}px solid {palette.IN_FLIGHT_BORDER}"


class InFlightTile(QWidget):
    clicked = Signal(str)
    context_requested = Signal(str, QPoint)
    control_triggered = Signal(str, str)

    def __init__(self, item: InFlightItem, parent=None):
        super().__init__(parent)
        self._key = item.key
        self._item = item
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self._key, self.mapToGlobal(pos))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tile_shape.TILE_MARGIN,) * 4)
        layout.setSpacing(tile_shape.TILE_SPACING)

        self._image = QLabel()
        self._image.setFixedSize(*_IMAGE_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setStyleSheet(
            f"background-color: transparent; border: {_BORDER}; border-radius: {BUTTON_RADIUS}px;"
        )
        self._caption = QLabel()
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        tile_shape.style_caption(self._caption)
        self._caption.setStyleSheet("background-color: transparent;")

        self._image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image)
        layout.addWidget(self._caption)

        self._status_scrim = TileStatusScrim(self)
        self._bar = CancelBar(cancel_tooltip(item.populating), self)
        self._bar.clicked.connect(self._cancel)
        self._controls = CornerButtons(self)
        self._controls.triggered.connect(
            lambda action: self.control_triggered.emit(self._key, action))

        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        self.setFixedSize(*tile_shape.tile_size())
        self._place_overlays()
        self.update_item(item)

        if item.media_type:
            ItemTypeIcon(item.media_type, self)

    @property
    def key(self) -> str:
        return self._key

    def update_item(self, item: InFlightItem):
        self._item = item
        self._caption.setText(item.caption)
        self._bar.set_cancelable(item.cancel is not None)
        self._bar.setToolTip(cancel_tooltip(item.populating) if item.cancel is not None else "")
        if item.is_an_item:
            self._controls.show_for(favorite=item.favorite,
                                    enhance=icons.ENHANCE_OPEN if item.enhanceable else None)
        else:
            self._controls.hide_all()
        pixmap = QPixmap()
        if (item.reading.frame and pixmap.loadFromData(item.reading.frame)
                and not pixmap.isNull()):
            self._image.setPixmap(pixmap.scaled(
                *_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._show_backdrop(item)
        self._render_timing()
        if item.reading.started_at is None and item.starts_at is None:
            self._tick.stop()
        else:
            self._tick.start()

    def _show_backdrop(self, item: InFlightItem):
        backdrop = blurred_backdrop(item.source_file, QSize(*_IMAGE_SIZE))
        if backdrop is not None:
            self._image.setPixmap(backdrop)

    @staticmethod
    def _stage_message(item: InFlightItem) -> str:
        return (queue_wait_text(item.foreign_ahead, item.starts_at)
                or {"running": "Generating…", "speaking": "Speaking her lines…"}.get(
                    item.reading.status, "Queued…"))

    def _render_timing(self):
        self._status_scrim.cover(self._image, self._stage_message(self._item), inset=_BORDER_PX)
        self._bar.raise_()
        self._controls.place(self._image.geometry())
        self._bar.show_progress(
            self._item.reading.caption(compact=True),
            *self._item.reading.bars(),
        )

    def _place_overlays(self):
        """Qt positions the frame only once the tile's layout has run, so it is forced here before the overlays are placed."""
        self.layout().activate()
        self._bar.setGeometry(bar_between_the_bottom_corners(self._image.geometry(), _BORDER_PX))
        self._controls.place(self._image.geometry())

    def _cancel(self):
        if self._item.cancel is not None:
            self._item.cancel()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
