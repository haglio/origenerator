from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage

_FORMATS = {"RGB": (QImage.Format.Format_RGB888, 3), "RGBA": (QImage.Format.Format_RGBA8888, 4)}


def as_qimage(image: Image.Image) -> QImage:
    drawn = image if image.mode in _FORMATS else image.convert("RGB")
    qt_format, bytes_a_pixel = _FORMATS[drawn.mode]
    return QImage(drawn.tobytes(), drawn.width, drawn.height, bytes_a_pixel * drawn.width,
                  qt_format).copy()
