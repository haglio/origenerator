"""Small vector icons for the gallery's toolbar buttons, drawn with QPainter.

Each returns a QIcon carrying a normal and a muted "disabled" rendering (Qt swaps
to the latter when a button is disabled), the same two-mode approach the metadata
panel's copy icon uses. Drawn rather than glyphs so they render identically in any
font and read clearly at a small size.
"""

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen
from PyQt6.QtCore import Qt, QRectF, QPointF

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import TEXT_PRIMARY, TEXT_MUTED

_SIZE = 48  # drawn large, then scaled down on the button, so edges stay crisp


def back_icon() -> QIcon:
    return _two_mode(lambda p, _color: _chevron(p, pointing_left=True))


def forward_icon() -> QIcon:
    return _two_mode(lambda p, _color: _chevron(p, pointing_left=False))


def undo_icon() -> QIcon:
    return _two_mode(_draw_undo)


def delete_icon() -> QIcon:
    return _two_mode(lambda p, _color: _draw_trash(p))


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


def _draw_trash(painter: QPainter):
    """A trash can: lid with a small handle over a lightly tapered body."""
    painter.drawLine(QPointF(13, 16), QPointF(35, 16))                       # lid
    painter.drawPolyline(QPointF(20, 16), QPointF(20, 12),
                         QPointF(28, 12), QPointF(28, 16))                    # handle
    painter.drawPolyline(QPointF(16, 16), QPointF(18, 37),
                         QPointF(30, 37), QPointF(32, 16))                    # body
    painter.drawLine(QPointF(21, 20), QPointF(22, 33))                       # ridges
    painter.drawLine(QPointF(27, 20), QPointF(26, 33))
