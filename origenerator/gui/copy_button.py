"""A small copy-to-clipboard icon button, shared wherever a value is worth
lifting to the clipboard in one click — a metadata filename, a prompt, a seed.

The value can be fixed (a string) or live (a zero-arg callable read at click
time), so the same button serves a read-only label and an editable form field.
"""

from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import TEXT_SECONDARY


class CopyButton(QPushButton):
    """Copies ``source`` to the clipboard. ``source`` is the text itself, or a
    zero-arg callable returning it — read at click time so an editable field's
    current value is copied, not whatever it held when the button was built."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.setObjectName("copyButton")
        self.setIcon(_copy_icon())
        self.setIconSize(QSize(14, 14))
        self.setToolTip("Copy to clipboard")
        self.setStyleSheet("padding: 2px 6px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._source = source
        self.clicked.connect(self._copy)

    def _copy(self):
        text = self._source() if callable(self._source) else self._source
        QApplication.clipboard().setText(text)


def _copy_icon() -> QIcon:
    """The familiar two-overlapping-sheets copy glyph."""
    icon = QIcon()
    icon.addPixmap(_draw_copy_sheets(TEXT_SECONDARY), QIcon.Mode.Normal)
    return icon


def _draw_copy_sheets(color) -> QPixmap:
    """Stroke the two sheets in ``color``. Both are outlines; a gap is cleared
    around the front sheet so it reads as sitting in front of the back one where
    they overlap."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    back = QRectF(24, 8, 28, 32)    # peeks out up and to the right
    front = QRectF(12, 24, 28, 32)  # sits in front, down and to the left
    radius = 6

    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(back, radius, radius)

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.black)
    painter.drawRoundedRect(front.adjusted(-4, -4, 4, 4), radius + 3, radius + 3)

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(front, radius, radius)
    painter.end()
    return pixmap
