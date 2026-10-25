from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from shared_ui.palette import BLACK

_BLUR_DIVISOR = 16
_DIM = 0.55

_CACHE: dict[tuple, QPixmap | None] = {}


def blurred_backdrop(path, size: QSize) -> QPixmap | None:
    if not path:
        return None
    key = (str(path), size.width(), size.height())
    if key not in _CACHE:
        _CACHE[key] = _render(path, size)
    return _CACHE[key]


def blurred_and_dimmed(pixmap: QPixmap, size: QSize) -> QPixmap:
    small = pixmap.scaled(max(1, size.width() // _BLUR_DIVISOR),
                          max(1, size.height() // _BLUR_DIVISOR),
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    blurred = small.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(blurred)
    painter.fillRect(blurred.rect(), QColor(*BLACK, int(255 * _DIM)))
    painter.end()
    return blurred


def _render(path, size: QSize) -> QPixmap | None:
    if not Path(path).is_file() or size.width() <= 0 or size.height() <= 0:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    covering = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
    plate = covering.copy((covering.width() - size.width()) // 2,
                          (covering.height() - size.height()) // 2,
                          size.width(), size.height())
    return blurred_and_dimmed(plate, size)
