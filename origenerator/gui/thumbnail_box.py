from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter, QPixmap

THUMBNAIL_BOX = QSize(96, 96)


def fitted_in_the_box(picture: QPixmap) -> QPixmap:
    return fitted_in(picture, THUMBNAIL_BOX)


def fitted_in(picture: QPixmap, box: QSize) -> QPixmap:
    return picture.scaled(box, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


def centered_in_square(picture: QPixmap, side: int) -> QPixmap:
    square = QPixmap(side, side)
    square.fill(Qt.GlobalColor.transparent)
    painter = QPainter(square)
    painter.drawPixmap((side - picture.width()) // 2, (side - picture.height()) // 2, picture)
    painter.end()
    return square
