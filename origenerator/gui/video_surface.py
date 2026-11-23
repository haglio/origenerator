from __future__ import annotations

from functools import cache

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication
from shared_ui.colors import BLACK


def stop_and_let_go_of_the_file(player: QMediaPlayer) -> None:
    player.stop()
    player.setSource(QUrl())


def release_media_player(player: QMediaPlayer) -> None:
    # Qt Multimedia: a stop alone leaves the backend winding down into a surface a closing widget takes down.
    stop_and_let_go_of_the_file(player)
    player.setVideoOutput(None)


@cache
def _one_engine_for_every_surface() -> QQmlEngine:
    return QQmlEngine(QApplication.instance())


class _RedrawsFromTheTopLeft(QObject):
    # A Qt Quick child makes its window reach the screen through the graphics card, and Qt 6.12 uploads only the bounding box of what was redrawn, in logical coordinates unscaled when the ratio is below 1 (scaledDirtyRegion in qbackingstoredefaultcompositor.cpp), so in Fun Time it lands short of what changed; a redrawn pixel at the top left stretches that box over all of it.
    _TOP_LEFT = QRect(0, 0, 1, 1)

    def eventFilter(self, window, event) -> bool:
        if event.type() == QEvent.Type.UpdateRequest and window.devicePixelRatioF() < 1:
            window.update(self._TOP_LEFT)
        return False


class VideoSurface(QQuickWidget):
    def __init__(self, parent=None):
        super().__init__(_one_engine_for_every_surface(), parent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor(BLACK)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.loadFromModule("QtMultimedia", "VideoOutput")
        self._sink: QVideoSink = self.rootObject().property("videoSink")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        window = self.window()
        if window.findChild(_RedrawsFromTheTopLeft, options=Qt.FindChildOption.FindDirectChildrenOnly) is None:
            window.installEventFilter(_RedrawsFromTheTopLeft(window))

    def video_sink(self) -> QVideoSink:
        return self._sink

    def current_frame(self) -> QImage:
        frame = self._sink.videoFrame()
        return frame.toImage() if frame.isValid() else QImage()
