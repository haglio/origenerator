from __future__ import annotations

from functools import cache

from PySide6.QtCore import Qt, QUrl
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


class VideoSurface(QQuickWidget):
    def __init__(self, parent=None):
        super().__init__(_one_engine_for_every_surface(), parent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor(BLACK)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.loadFromModule("QtMultimedia", "VideoOutput")
        self._sink: QVideoSink = self.rootObject().property("videoSink")

    def video_sink(self) -> QVideoSink:
        return self._sink

    def current_frame(self) -> QImage:
        frame = self._sink.videoFrame()
        return frame.toImage() if frame.isValid() else QImage()
