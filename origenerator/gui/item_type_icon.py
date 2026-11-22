from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QWidget
from shared_ui.spacing import BUTTON_RADIUS, GAP_SMALL, MARGIN_STANDARD
from shared_ui.type_scale import SIZE_TINY, in_pixels

from origenerator.gui import icons, square_buttons
from origenerator.timing import clock_duration

_LENGTH_PADDING = GAP_SMALL
_LENGTH_CSS = (
    f"background: {icons.ITEM_TYPE_ICON_GROUND.name(QColor.NameFormat.HexArgb)}; "
    f"color: {icons.ITEM_TYPE_ICON_INK.name()}; border-radius: {BUTTON_RADIUS}px; "
    f"font-size: {in_pixels(SIZE_TINY)}px; font-weight: bold; "
    f"padding: 0 {_LENGTH_PADDING}px;"
)


class ItemTypeIcon(QLabel):
    def __init__(self, media_type: str, tile: QWidget):
        super().__init__(tile)
        self.media_type = media_type
        self.draw_at_the_huds_scale_again()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()

    def set_media_type(self, media_type: str):
        if media_type != self.media_type:
            self.media_type = media_type
            self._wear(media_type)

    def draw_at_the_huds_scale_again(self) -> None:
        inset = square_buttons.landing(MARGIN_STANDARD)
        self._wear(self.media_type)
        self.move(inset, inset)

    def _wear(self, media_type: str):
        pixmap = icons.item_type_icon(media_type, square_buttons.landing(icons.ITEM_TYPE_ICON_SIZE))
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())


class VideoLength(QLabel):
    def __init__(self, seconds: float, beside: ItemTypeIcon):
        super().__init__(clock_duration(round(seconds)), beside.parentWidget())
        self.setStyleSheet(_LENGTH_CSS)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._beside = beside
        self.draw_at_the_huds_scale_again()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()

    def draw_at_the_huds_scale_again(self) -> None:
        beside = self._beside
        self.setFixedHeight(beside.height())
        self.adjustSize()
        self.move(beside.geometry().right() + 1 + square_buttons.landing(GAP_SMALL), beside.y())
