"""The shape every card in a folder's grid shares — pictures and offers alike.

A settings folder's grid holds finished thumbnails, live in-flight cards, and the
two cards that aren't generations at all: the re-roll "+" and the request card
beside it. They stand shoulder to shoulder in one flow, so they are one size and
their captions are set one way. Kept here rather than in any one of them so the
family cannot drift apart the next time one is touched.

The caption is set in the family's tiny type, and the band is two lines of it
tall, so a caption long enough to wrap -- a run in flight is captioned with its
model and its prompt -- wraps rather than being clipped. The card's height
follows from the band, so a caption never quietly costs a line.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QLabel
from shared_ui.fonts import FONT_UI, SIZE_TINY, make_font
from shared_ui.spacing import BUTTON_RADIUS

# The picture a card gives to its content, and the frame around it. The picture
# is what the grid is for, so the card's height is what gives when the caption
# needs more room, never this.
CARD_WIDTH = 180
PICTURE_SIZE = (172, 160)
CARD_MARGIN = 4
CARD_SPACING = 2

def caption_font() -> QFont:
    """The family's tiny type, which a card's caption, count and breadcrumb are
    set in: a copy, since a caller may set it on a widget that then changes it."""
    return QFont(make_font(FONT_UI, SIZE_TINY))


def line_height() -> int:
    return QFontMetrics(caption_font()).height()


def caption_height() -> int:
    """The caption band: two lines of :func:`caption_font`, so a caption long
    enough to wrap is read rather than cut in half."""
    return 2 * line_height()


def card_size() -> tuple:
    """Every card's outside — the picture, the caption band under it, and the
    frame around both."""
    height = (2 * CARD_MARGIN + PICTURE_SIZE[1] + CARD_SPACING + caption_height())
    return CARD_WIDTH, height


def picture_size() -> QSize:
    return QSize(*PICTURE_SIZE)


def folder_card_size(breadcrumb: bool = False) -> tuple:
    """A folder's outside: the same card as a generation's, plus a line of the
    caption's type saying how many items are in it, and another saying where it
    lives in the Favorites collection, where a folder is out of its parent's
    context."""
    width, height = card_size()
    height += CARD_SPACING + line_height()
    if breadcrumb:
        height += CARD_SPACING + line_height()
    return width, height


def style_caption(label) -> None:
    """Set one card's caption label to the family's font and band height."""
    label.setFont(caption_font())
    label.setMaximumHeight(caption_height())


from shared_ui import colors
from shared_ui.icons import draw_glyph
from shared_ui.palette import BORDER_SUBTLE, TEXT_MUTED, as_hex

from origenerator.gui.palette import (
    CARD_HOVER_BORDER,
    EMPTY_PLATE,
    SELECTED_BORDER,
    SELECTED_FILL,
)

_CORNER = f"border-radius: {BUTTON_RADIUS}px;"

# The resting dashed outline, versus the blue and white marking the card as the item
# driving the info pane — the same marks a selected thumbnail wears.
IDLE_FRAME_CSS = (
    "#{name} {{ border: 1px dashed " + as_hex(BORDER_SUBTLE) + "; " + _CORNER + " }}"
    "#{name}:hover {{ border-color: " + CARD_HOVER_BORDER + "; }}"
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
    """One of the family's marks, large and muted, on the plate a thumbnail's
    picture would occupy."""

    def __init__(self, mark: str, *, side: int):
        super().__init__()
        self.mark = mark
        self._side = side
        self.setFixedSize(*PICTURE_SIZE)
        self.setStyleSheet(_PLATE_CSS)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        draw_glyph(painter, self.mark, colors.TEXT_MUTED if self.isEnabled() else colors.BORDER_SUBTLE,
                   size=self._side, x=(self.width() - self._side) / 2,
                   y=(self.height() - self._side) / 2)
