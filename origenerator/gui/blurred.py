from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from shared_ui.hard_to_miss import blurred_and_dimmed

_CACHE: dict[tuple, QPixmap | None] = {}


def blurred_backdrop(path, size: QSize) -> QPixmap | None:
    if not path:
        return None
    key = (str(path), size.width(), size.height())
    if key not in _CACHE:
        _CACHE[key] = _render(path, size)
    return _CACHE[key]


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
