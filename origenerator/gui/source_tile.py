from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import BUTTON_RADIUS, GAP_SMALL

from origenerator.gui import tile_shape
from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.link_heading import link_heading
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box
from origenerator.media import MediaType

_DEFAULT_HEADING = "From source image"
_DEFAULT_MEDIA_TYPE = MediaType.IMAGE


class SourceTile(QWidget):
    activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt_id: str | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        self._heading = link_heading(_DEFAULT_HEADING)
        column.addWidget(self._heading, 0, Qt.AlignmentFlag.AlignHCenter)

        self._thumb = QLabel()
        self._thumb.setFixedSize(THUMBNAIL_BOX)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(
            f"border: 1px solid {BORDER_SUBTLE.name()}; border-radius: {BUTTON_RADIUS}px;"
        )
        column.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        self._item_type_icon = ItemTypeIcon(_DEFAULT_MEDIA_TYPE, self._thumb)

        self._name = QLabel()
        self._name.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        tile_shape.style_caption(self._name)
        column.addWidget(self._name, 0, Qt.AlignmentFlag.AlignHCenter)

        self.hide()

    def show_source(self, prompt_id: str, thumbnail_path, name: str,
                    heading: str | None = None, media_type: str | None = None,
                    gray: bool = False):
        self._prompt_id = prompt_id
        self._heading.setText(heading or _DEFAULT_HEADING)
        self._item_type_icon.set_media_type(media_type or _DEFAULT_MEDIA_TYPE)
        self._name.setText(name)
        thumb = self._scaled_thumb(thumbnail_path)
        self._thumb.setPixmap(grayscale_pixmap(thumb) if gray else thumb)
        self.show()

    def clear(self):
        self._prompt_id = None
        self.hide()

    def _scaled_thumb(self, thumbnail_path) -> QPixmap:
        pixmap = QPixmap(str(thumbnail_path)) if thumbnail_path else QPixmap()
        if pixmap.isNull():
            return QPixmap()
        return fitted_in_the_box(pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._prompt_id:
            self.activated.emit(self._prompt_id)
