from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QImage, QPixmap

_FRAMES_KEPT = 4


@lru_cache(maxsize=_FRAMES_KEPT)
def decoded(frame: bytes) -> QImage | None:
    image = QImage.fromData(frame)
    return None if image.isNull() else image


def pixmap_of(frame: bytes) -> QPixmap | None:
    image = decoded(frame)
    return None if image is None else QPixmap.fromImage(image)
