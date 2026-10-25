from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter, QPixmap

THUMBNAIL_BOX = QSize(96, 96)


def fitted_in_the_box(pixmap: QPixmap) -> QPixmap:
    return fitted_in(pixmap, THUMBNAIL_BOX)


def fitted_in(pixmap: QPixmap, box: QSize) -> QPixmap:
    return pixmap.scaled(box, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def centered_in_square(pixmap: QPixmap, side: int) -> QPixmap:
    square = QPixmap(side, side)
    square.fill(Qt.GlobalColor.transparent)
    painter = QPainter(square)
    painter.drawPixmap((side - pixmap.width()) // 2, (side - pixmap.height()) // 2, pixmap)
    painter.end()
    return square
