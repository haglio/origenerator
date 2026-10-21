from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap

THUMBNAIL_BOX = QSize(96, 96)


def fitted_in_the_box(picture: QPixmap) -> QPixmap:
    return picture.scaled(THUMBNAIL_BOX, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
