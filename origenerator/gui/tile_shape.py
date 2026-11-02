from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QLabel
from shared_ui.fonts import FONT_UI, SIZE_TINY, make_font
from shared_ui.spacing import BUTTON_RADIUS, GAP_SMALL

TILE_WIDTH = 180
THUMBNAIL_SIZE = (172, 160)
TILE_MARGIN = GAP_SMALL
TILE_SPACING = GAP_SMALL

def caption_font() -> QFont:
    return QFont(make_font(FONT_UI, SIZE_TINY))


def line_height() -> int:
    return QFontMetrics(caption_font()).height()


def caption_height() -> int:
    return 2 * line_height()


def tile_size() -> tuple:
    height = (2 * TILE_MARGIN + THUMBNAIL_SIZE[1] + TILE_SPACING + caption_height())
    return TILE_WIDTH, height


def thumbnail_size() -> QSize:
    return QSize(*THUMBNAIL_SIZE)


def folder_tile_size(folder_path: bool = False) -> tuple:
    width, height = tile_size()
    height += TILE_SPACING + line_height()
    if folder_path:
        height += TILE_SPACING + line_height()
    return width, height


def style_caption(label) -> None:
    label.setFont(caption_font())
    label.setMaximumHeight(caption_height())


from shared_ui import colors
from shared_ui.icons import draw_icon
from shared_ui.palette import BORDER_SUBTLE, TEXT_MUTED, as_hex

from origenerator.gui.palette import (
    EMPTY_PLATE,
    SELECTED_BORDER,
    SELECTED_FILL,
    TILE_HOVER_BORDER,
)

_CORNER = f"border-radius: {BUTTON_RADIUS}px;"

IDLE_FRAME_CSS = (
    "#{name} {{ border: 1px dashed " + as_hex(BORDER_SUBTLE) + "; " + _CORNER + " }}"
    "#{name}:hover {{ border-color: " + TILE_HOVER_BORDER + "; }}"
    "#{name}:disabled {{ border-color: " + as_hex(BORDER_SUBTLE) + "; }}"
    "#{name} QLabel:disabled {{ color: " + as_hex(TEXT_MUTED) + "; }}"
)
SELECTED_FRAME_CSS = ("#{name} {{ border: 2px solid " + SELECTED_BORDER
                      + "; background-color: " + SELECTED_FILL + "; " + _CORNER + " }}")

_PLATE_CSS = f"QLabel {{ background: {EMPTY_PLATE}; {_CORNER} }}"


def idle_css(name: str) -> str:
    return IDLE_FRAME_CSS.format(name=name)


def selected_css(name: str) -> str:
    return SELECTED_FRAME_CSS.format(name=name)


class MarkPlate(QLabel):
    def __init__(self, mark: str, *, side: int):
        super().__init__()
        self.mark = mark
        self._side = side
        self.setFixedSize(*THUMBNAIL_SIZE)
        self.setStyleSheet(_PLATE_CSS)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        draw_icon(painter, self.mark, colors.TEXT_MUTED if self.isEnabled() else colors.BORDER_SUBTLE,
                  size=self._side, x=(self.width() - self._side) / 2,
                  y=(self.height() - self._side) / 2)
