"""A checkbox that paints its own ticked-box indicator.

The native Windows dark style renders a checked QCheckBox as a bare chevron
with no box outline, which reads as a down-caret rather than a ticked box.
We draw the indicator ourselves -- a rounded square that fills with the accent
colour and shows a real check mark when checked -- so it always looks like
checking a box, independent of the OS theme.
"""

from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtGui import QPainter, QPen, QColor, QPolygonF
from PyQt6.QtCore import Qt, QSize, QRectF, QPointF

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BLUE, BG_SECONDARY, BORDER_SUBTLE, TEXT_PRIMARY, TEXT_MUTED

_BOX = 16        # indicator side length (px)
_GAP = 7         # space between the box and the label
_RADIUS = 3.0    # indicator corner rounding
_TICK = QColor(255, 255, 255)

# The check mark as a fraction of the box, drawn as a short down-stroke into a
# long up-stroke -- the classic tick, not a symmetric "v".
_TICK_POINTS = ((0.24, 0.52), (0.42, 0.70), (0.78, 0.30))


class CheckBox(QCheckBox):
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = self._indicator_rect()
        enabled = self.isEnabled()

        if self.isChecked():
            fill = BLUE if enabled else BORDER_SUBTLE
            painter.setPen(QPen(fill, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(box, _RADIUS, _RADIUS)
            self._draw_tick(painter, box, enabled)
        else:
            painter.setPen(QPen(BORDER_SUBTLE, 1.4))
            painter.setBrush(BG_SECONDARY)
            painter.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), _RADIUS, _RADIUS)

        text = self.text()
        if text:
            painter.setPen(TEXT_PRIMARY if enabled else TEXT_MUTED)
            left = box.right() + _GAP
            painter.drawText(
                QRectF(left, 0, self.width() - left, self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )
        painter.end()

    def _indicator_rect(self) -> QRectF:
        top = (self.height() - _BOX) / 2.0
        return QRectF(1.0, top, float(_BOX), float(_BOX))

    def _draw_tick(self, painter: QPainter, box: QRectF, enabled: bool):
        side = box.width()
        points = QPolygonF([
            QPointF(box.left() + fx * side, box.top() + fy * side)
            for fx, fy in _TICK_POINTS
        ])
        pen = QPen(_TICK if enabled else QColor(220, 220, 220))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(points)

    def sizeHint(self) -> QSize:
        width = _BOX + _GAP + self.fontMetrics().horizontalAdvance(self.text())
        height = max(_BOX + 4, self.fontMetrics().height() + 4)
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()
