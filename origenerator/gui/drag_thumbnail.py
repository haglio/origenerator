from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import QApplication

from origenerator.gui.drags import carry

THUMBNAIL_MAX = 128


def fit_thumbnail(pixmap: QPixmap | None) -> QPixmap:
    if pixmap is None or pixmap.isNull():
        return QPixmap()
    if pixmap.width() <= THUMBNAIL_MAX and pixmap.height() <= THUMBNAIL_MAX:
        return pixmap
    return pixmap.scaled(
        THUMBNAIL_MAX, THUMBNAIL_MAX,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


def label_thumbnail(label) -> QPixmap:
    movie = label.movie()
    return fit_thumbnail(movie.currentPixmap() if movie is not None else label.pixmap())


def set_drag_thumbnail(drag, pixmap: QPixmap) -> None:
    if pixmap is not None and not pixmap.isNull():
        drag.setPixmap(pixmap)


class DragOut(QObject):
    def __init__(self):
        super().__init__()
        self._origin: QPoint | None = None

    @property
    def pressed(self) -> bool:
        return self._origin is not None

    def forget(self) -> None:
        self._origin = None

    def note_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()

    def should_start(self, event) -> bool:
        if self._origin is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return False
        moved = (event.position().toPoint() - self._origin).manhattanLength()
        if moved < QApplication.startDragDistance():
            return False
        self._origin = None
        return True

    def start(self, mime, pixmap: QPixmap, *,
              action: Qt.DropAction = Qt.DropAction.CopyAction) -> None:
        drag = QDrag(self)
        drag.setMimeData(mime)
        set_drag_thumbnail(drag, pixmap)
        carry(drag, mime, self, action)
