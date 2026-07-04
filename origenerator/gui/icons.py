"""Small vector icons the gallery draws with QPainter.

The toolbar-button icons each return a QIcon carrying a normal and a muted
"disabled" rendering (Qt swaps to the latter when a button is disabled), the same
two-mode approach the metadata panel's copy icon uses. The recipe-level badges
(:func:`level_badge_icon`) are lettered chips marking which of workflow/model/LoRA
a folder is; the media-type badges (:func:`media_type_badge`) are corner chips
marking a Recents tile as an image or a video. All are drawn rather than glyphs so
they render identically in any font and read clearly at a small size.
"""

import math
from functools import lru_cache

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QRectF, QPointF

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import TEXT_PRIMARY, TEXT_MUTED, BG_PRIMARY, BLUE, PINK, AMBER, GREEN

_SIZE = 48  # drawn large, then scaled down on the button, so edges stay crisp

# Hierarchy level badges. A gallery folder below the media roots sits at one of
# these levels; a small lettered chip names which, so a tree row or a browser
# tile is self-describing without the reader counting indentation. The media
# roots (Images/Videos) and the settings leaves carry none.
LEVEL_LABELS = {
    "workflow": "Workflow", "model": "Model", "lora": "LoRA",
    "source_image": "Source Image",
}
_LEVEL_BADGES = {
    "workflow": ("W", BLUE), "model": ("M", PINK), "lora": ("L", AMBER),
    "source_image": ("I", GREEN),
}

# The Recents shelf mixes images and videos in one flow, so each tile wears a
# small corner badge naming its kind. A white glyph on a translucent dark chip,
# so it reads over a thumbnail of any color.
_BADGE_CHIP = QColor(0, 0, 0, 160)
_BADGE_GLYPH = QColor(255, 255, 255)
_BADGE_DISPLAY = 22  # the badge's on-screen size, in px


def back_icon() -> QIcon:
    return _two_mode(lambda p, _color: _chevron(p, pointing_left=True))


def forward_icon() -> QIcon:
    return _two_mode(lambda p, _color: _chevron(p, pointing_left=False))


def undo_icon() -> QIcon:
    return _two_mode(_draw_undo)


def autoloop_icon() -> QIcon:
    """A clockwise circular arrow — auto-generate: keep re-rolling this folder."""
    return _two_mode(_draw_autoloop)


def delete_icon() -> QIcon:
    return _two_mode(lambda p, _color: _draw_trash(p))


def star_icon(*, filled: bool) -> QIcon:
    """A five-pointed star — solid when the folder is starred, an outline when
    not, so the hover control shows the state it will toggle."""
    return _two_mode(lambda p, color: _draw_star(p, color, filled))


def clock_icon() -> QIcon:
    """A clock face — the Recents shelf's caret marker, drawn to match the star."""
    return _two_mode(_draw_clock)


@lru_cache(maxsize=None)
def media_type_badge(media_type: str) -> QPixmap:
    """A small corner badge marking a Recents tile as an image or a video.

    A white glyph — a play triangle for a video, a framed photo for an image — on
    a translucent dark chip, so it reads over a thumbnail of any color. Cached and
    pre-scaled to its on-screen size; the same two badges decorate every tile.
    """
    draw = _draw_play if media_type == "video" else _draw_photo
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_CHIP)
    painter.drawRoundedRect(QRectF(4, 4, _SIZE - 8, _SIZE - 8), 11, 11)
    draw(painter)
    painter.end()
    return pixmap.scaled(
        _BADGE_DISPLAY, _BADGE_DISPLAY,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


_REROLL_GLYPH = QColor(255, 255, 255)


@lru_cache(maxsize=None)
def reroll_seed_icon(media_type: str) -> QIcon:
    """A thumbnail hover-button glyph: a regenerate ring around a small play/photo
    mark — "re-roll this video" (its motion) or "this image" (its start frame).

    White line art; the button paints its own translucent chip behind it, so the
    glyph reads over a thumbnail of any color. The two differ by their inner mark,
    so a video seed control is never mistaken for an image seed one.
    """
    return QIcon(_render(lambda p, _c: _draw_reroll_seed(p, media_type), _REROLL_GLYPH))


def _draw_reroll_seed(painter: QPainter, media_type: str):
    # The media identity, drawn large so video vs image reads at a glance...
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_REROLL_GLYPH)
    if media_type == "video":
        painter.drawPolygon(QPointF(11, 9), QPointF(11, 31), QPointF(29, 20))  # play triangle
    else:
        pen = QPen(_REROLL_GLYPH)
        pen.setWidthF(3.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(8, 11, 24, 19), 3, 3)                   # photo frame
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_REROLL_GLYPH)
        painter.drawEllipse(QPointF(15, 18), 2.6, 2.6)                         # the sun
        painter.drawPolygon(QPointF(10, 28), QPointF(18, 20), QPointF(31, 28))  # a mountain peak
    _draw_regen_badge(painter)


def _draw_regen_badge(painter: QPainter):
    """A small circular arrow in the bottom-right — the 're-roll' modifier over
    the media glyph, so the control reads as 'regenerate this' not 'play this'."""
    pen = QPen(_REROLL_GLYPH)
    pen.setWidthF(3.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(29, 29, 15, 15), 35 * 16, 250 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_REROLL_GLYPH)
    painter.drawPolygon(QPointF(45, 33), QPointF(39, 31), QPointF(41, 38))  # arrowhead


@lru_cache(maxsize=None)
def level_badge_icon(level: str) -> QIcon:
    """A filled, lettered chip marking a folder's recipe level (see LEVEL_LABELS).

    Cached: the same three chips decorate many tree rows and tiles, so they're
    rendered once and shared rather than re-drawn per folder.
    """
    letter, color = _LEVEL_BADGES[level]
    icon = QIcon()
    icon.addPixmap(_render_badge(letter, color))
    return icon


def _render_badge(letter: str, color) -> QPixmap:
    """A rounded chip filled with ``color``, its ``letter`` centred in readable
    contrast — dark on a light chip, light on a saturated one."""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(3, 3, _SIZE - 6, _SIZE - 6), 12, 12)
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(30)
    painter.setFont(font)
    painter.setPen(_readable_on(color))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return pixmap


def _readable_on(color):
    """Near-black or the primary text color, whichever reads on ``color``."""
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return BG_PRIMARY if luminance > 150 else TEXT_PRIMARY


def _two_mode(draw) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_render(draw, TEXT_PRIMARY), QIcon.Mode.Normal)
    icon.addPixmap(_render(draw, TEXT_MUTED), QIcon.Mode.Disabled)
    return icon


def _render(draw, color) -> QPixmap:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter, color)
    painter.end()
    return pixmap


def _chevron(painter: QPainter, *, pointing_left: bool):
    """A ``‹`` or ``›`` chevron centred in the canvas."""
    near, far, top, bottom = 18, 30, 13, 35
    if pointing_left:
        painter.drawPolyline(QPointF(far, top), QPointF(near, 24), QPointF(far, bottom))
    else:
        painter.drawPolyline(QPointF(near, top), QPointF(far, 24), QPointF(near, bottom))


def _draw_undo(painter: QPainter, color):
    """A counter-clockwise circular arrow — the conventional undo glyph."""
    # Most of a circle, with the gap (and the arrowhead) at the top.
    painter.drawArc(QRectF(13, 15, 22, 22), 100 * 16, 300 * 16)
    # A filled left-pointing head at the arc's top end, showing the direction.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPointF(19, 15), QPointF(28, 10), QPointF(28, 20))


def _draw_autoloop(painter: QPainter, color):
    """A clockwise circular arrow — the horizontal mirror of the undo glyph, so
    "keep going" and "go back" read as opposites."""
    painter.drawArc(QRectF(13, 15, 22, 22), 80 * 16, -300 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPointF(29, 15), QPointF(20, 10), QPointF(20, 20))


def _draw_trash(painter: QPainter):
    """A trash can: lid with a small handle over a lightly tapered body."""
    painter.drawLine(QPointF(13, 16), QPointF(35, 16))                       # lid
    painter.drawPolyline(QPointF(20, 16), QPointF(20, 12),
                         QPointF(28, 12), QPointF(28, 16))                    # handle
    painter.drawPolyline(QPointF(16, 16), QPointF(18, 37),
                         QPointF(30, 37), QPointF(32, 16))                    # body
    painter.drawLine(QPointF(21, 20), QPointF(22, 33))                       # ridges
    painter.drawLine(QPointF(27, 20), QPointF(26, 33))


def _draw_star(painter: QPainter, color, filled: bool):
    cx, cy, outer, inner = 24, 25, 15, 6.2
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = outer if i % 2 == 0 else inner
        points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    if filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
    else:
        pen = QPen(color)
        pen.setWidthF(3)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)  # a thinner outline than the default stroke
    painter.drawPolygon(*points)


def _draw_play(painter: QPainter):
    """A filled play triangle — the universal 'this is a video' mark."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_GLYPH)
    painter.drawPolygon(QPointF(20, 16), QPointF(20, 32), QPointF(34, 24))


def _draw_photo(painter: QPainter):
    """A framed photo — a sun over a mountain — the 'this is an image' mark."""
    pen = QPen(_BADGE_GLYPH)
    pen.setWidthF(2.6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(14, 16, 20, 16), 3, 3)   # the picture frame
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_GLYPH)
    painter.drawEllipse(QPointF(20, 21), 2.3, 2.3)          # the sun, upper-left
    painter.drawPolygon(QPointF(16, 31), QPointF(24, 23),   # a single mountain peak
                        QPointF(33, 31))


def _draw_clock(painter: QPainter, _color):
    """A round clock face with two hands (at 12 and 3) — the "recent" marker."""
    painter.drawEllipse(QRectF(13, 13, 22, 22))
    painter.drawLine(QPointF(24, 24), QPointF(24, 15))   # hour hand, pointing up
    painter.drawLine(QPointF(24, 24), QPointF(31, 24))   # minute hand, to the right
