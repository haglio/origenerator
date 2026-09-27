from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtMultimedia import QVideoFrame, QVideoSink
from PyQt6.QtWidgets import QWidget


class VideoSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sink = QVideoSink(self)
        self._frame = QVideoFrame()
        self._sink.videoFrameChanged.connect(self._take)

    def video_sink(self) -> QVideoSink:
        return self._sink

    def picture(self) -> QImage:
        return self._frame.toImage() if self._frame.isValid() else QImage()

    def _take(self, frame: QVideoFrame) -> None:
        self._frame = QVideoFrame(frame)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        picture = self.picture()
        if picture.isNull():
            return
        shown = QRect(0, 0, 0, 0)
        shown.setSize(picture.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio))
        shown.moveCenter(self.rect().center())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(shown, picture)
