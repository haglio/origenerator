from __future__ import annotations

from PySide6.QtGui import QColor, QPen

DASH_PIXELS = 10


def dashed_pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setDashPattern([DASH_PIXELS / width, DASH_PIXELS / width])
    return pen
