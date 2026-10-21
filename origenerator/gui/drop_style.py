"""The style a drop zone wears while a drag it would take is under way: edged in
blue and lit, and one step lighter still while the drag is over it."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, Qt
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QWidget
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


def light(widget: QWidget, state: str, on: bool) -> None:
    if widget.property(state) == on:
        return
    widget.setProperty(state, on)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class DropEdge(QWidget):
    """The style's edge, drawn over everything ``zone`` holds, which would hide it."""

    def __init__(self, zone: QWidget):
        super().__init__(zone)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(zone.rect())
        self.hide()
        zone.installEventFilter(self)

    def eventFilter(self, zone, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(zone.rect())
        elif event.type() == QEvent.Type.ChildAdded:
            self.raise_()
        return False

    def paintEvent(self, _event):
        paint(QPainter(self), self.rect())
