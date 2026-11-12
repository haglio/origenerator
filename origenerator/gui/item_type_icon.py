from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget
from shared_ui.spacing import MARGIN_STANDARD

from origenerator.gui import icons

_INSET = MARGIN_STANDARD


class ItemTypeIcon(QLabel):
    def __init__(self, media_type: str, tile: QWidget):
        super().__init__(tile)
        self.media_type = media_type
        self._wear(media_type)
        self.move(_INSET, _INSET)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()

    def set_media_type(self, media_type: str):
        if media_type != self.media_type:
            self.media_type = media_type
            self._wear(media_type)

    def _wear(self, media_type: str):
        pixmap = icons.item_type_icon(media_type)
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
