"""The style a drop zone wears while a drag it would take is under way: edged in
blue and lit, and one step lighter still while the drag is over it."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter, QPen
from shared_ui.colors import BG_TERTIARY, BLUE, hovered

LIT = "dragActive"
AIMED = "dropTarget"
GROUNDS = {LIT: BG_TERTIARY, AIMED: hovered(BG_TERTIARY)}
EDGE = BLUE
RADIUS = 4


def ground_rules() -> str:
    return "".join(f"""
    QWidget[{state}="true"] {{
        background-color: {GROUNDS[state].name()};
    }}""" for state in (LIT, AIMED))


def paint(painter: QPainter, rect, ground=None) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(EDGE, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush if ground is None else ground)
    painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
    painter.restore()
