"""The shape every card in a folder's grid shares — pictures and offers alike.

A settings folder's grid holds finished thumbnails, live in-flight cards, and the
two cards that aren't generations at all: the re-roll "+" and the request card
beside it. They stand shoulder to shoulder in one flow, so they are one size and
their captions are set one way. Kept here rather than in any one of them so the
family cannot drift apart the next time one is touched.

The caption is where the sizing has to be thought about, because what it usually
carries is a seed, and a video's seed is twenty digits. At the app's own font
that runs past the width of a card, wraps, and was then cut off by a band one
line tall — so the number every video tile is identified by was unreadable. Two
things fix that together: the caption is set a step below the app's font
(:data:`CAPTION_SCALE`), and the band is two lines of *that* tall, so a caption
long enough to wrap wraps rather than being clipped. The card's height follows
from the band, so choosing a bigger caption never quietly costs a line again.
"""

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication

# The picture a card gives to its content, and the frame around it. The picture
# is what the grid is for, so the card's height is what gives when the caption
# needs more room, never this.
CARD_WIDTH = 180
PICTURE_SIZE = (172, 160)
CARD_MARGIN = 4
CARD_SPACING = 2

# How far below the app's own font a caption is set. Small enough that a long
# seed doesn't take over the tile, large enough to still read as text rather than
# as fine print — the first pass at this went much further down (far enough to
# fit a whole seed on one line) and came out too small to read comfortably.
CAPTION_SCALE = 0.8
# Point sizes are picked on a half-point grid, and never below what is legible.
_STEP_PT = 0.5
_FLOOR_PT = 7.0

_CAPTION_FONT: QFont | None = None


def scaled_point_size(base_pt: float) -> float:
    """The caption's size for an app font of ``base_pt`` — scaled down, rounded
    to the half point, and never below what can still be read."""
    return max(_FLOOR_PT, round(base_pt * CAPTION_SCALE / _STEP_PT) * _STEP_PT)


def caption_font() -> QFont:
    """The font every card's caption is set in.

    Cached — the app's font is fixed for the session, and this is asked for once
    per tile in a grid that rebuilds on every poll.
    """
    global _CAPTION_FONT
    if _CAPTION_FONT is None:
        app = QApplication.instance()
        base = app.font() if app is not None else QFont()
        font = QFont(base)
        font.setPointSizeF(scaled_point_size(base.pointSizeF()))
        _CAPTION_FONT = font
    return QFont(_CAPTION_FONT)


def caption_height() -> int:
    """The caption band: two lines of :func:`caption_font`, so a caption long
    enough to wrap is read rather than cut in half."""
    return 2 * QFontMetrics(caption_font()).height()


def card_size() -> tuple:
    """Every card's outside — the picture, the caption band under it, and the
    frame around both."""
    height = (2 * CARD_MARGIN + PICTURE_SIZE[1] + CARD_SPACING + caption_height())
    return CARD_WIDTH, height


def picture_size() -> QSize:
    return QSize(*PICTURE_SIZE)


def style_caption(label) -> None:
    """Set one card's caption label to the family's font and band height."""
    label.setFont(caption_font())
    label.setMaximumHeight(caption_height())


# The resting dashed box, versus the solid border marking the card as the item
# driving the info pane — the same mark a selected thumbnail wears.
IDLE_FRAME_CSS = (
    "#{name} {{ border: 1px dashed #4a4a4a; border-radius: 4px; }}"
    "#{name}:hover {{ border-color: #6f6f6f; }}"
)
SELECTED_FRAME_CSS = "#{name} {{ border: 2px solid #8a8a8a; border-radius: 4px; }}"

# How a glyph itself is drawn: a large muted character on the same plate a
# thumbnail's picture would occupy.
GLYPH_CSS = "color: #6f6f6f; font-size: {size}px; background: #2a2a2a; border-radius: 3px;"


def idle_css(name: str) -> str:
    return IDLE_FRAME_CSS.format(name=name)


def selected_css(name: str) -> str:
    return SELECTED_FRAME_CSS.format(name=name)


def glyph_css(size: int = 56) -> str:
    return GLYPH_CSS.format(size=size)
