from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QUrl
from PyQt6.QtGui import QImage
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickImageProvider, QQuickWindow
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator.ken_burns import ZOOM_SPAN, PushClock, zoom_at

# Drawn by Qt Quick's render thread rather than by the window's own thread, so
# nothing else the window does can hold the push still: a ScaleAnimator runs on
# that thread for as long as it is running.
_SCENE = b"""
import QtQuick

Rectangle {
    id: root
    anchors.fill: parent
    color: "black"
    property real span: 1.0
    property size pictureSize: Qt.size(0, 0)
    property string pictureSource: ""

    Item {
        clip: true
        anchors.centerIn: parent
        readonly property real fit: (root.pictureSize.width > 0 && root.pictureSize.height > 0)
            ? Math.min(root.width / root.pictureSize.width,
                       root.height / root.pictureSize.height)
            : 0
        width: root.pictureSize.width * fit
        height: root.pictureSize.height * fit

        Image {
            id: picture
            objectName: "picture"
            anchors.fill: parent
            source: root.pictureSource
            cache: false
            smooth: true
            transformOrigin: Item.Center
        }
    }

    SequentialAnimation {
        id: push
        objectName: "push"
        property real startScale: 1.0
        property int remaining: 1
        property int dwell: 1
        ScaleAnimator {
            objectName: "restOfTheMove"
            target: picture
            from: push.startScale
            to: root.span
            duration: push.remaining
        }
        ScaleAnimator {
            objectName: "wholeMoves"
            target: picture
            from: 1.0
            to: root.span
            duration: push.dwell
            loops: Animation.Infinite
        }
    }
}
"""


def _now_ms() -> float:
    return time.monotonic() * 1000.0


class _Pictures(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.current = QImage()

    def requestImage(self, _id, _requested_size):
        return self.current, self.current.size()


class KenBurnsStill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pictures = _Pictures()
        self._engine = QQmlEngine(self)
        self._engine.addImageProvider("still", self._pictures)
        self._view = QQuickWindow()
        # A native window keeps the mouse for itself on Windows, and presses over
        # the picture belong to the pane under it: a double-click closes a show.
        self._view.setFlag(Qt.WindowType.WindowTransparentForInput)
        component = QQmlComponent(self._engine)
        component.setData(_SCENE, QUrl())
        self._scene = component.create()
        self._scene.setParentItem(self._view.contentItem())
        self._scene.setProperty("span", ZOOM_SPAN)
        self._push = self._scene.findChild(QObject, "push")
        self._picture = self._scene.findChild(QObject, "picture")
        self._clock = PushClock()
        self._dwell_ms = 0
        self._pictures_shown = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QWidget.createWindowContainer(self._view, self)
        container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(container)

    def show_picture(self, image: QImage) -> None:
        self._pictures.current = image
        self._pictures_shown += 1
        self._scene.setProperty("pictureSize", image.size())
        self._scene.setProperty("pictureSource", f"image://still/{self._pictures_shown}")

    def start(self, dwell_ms: int, progress: float) -> None:
        self._dwell_ms = dwell_ms
        self._clock.start(_now_ms(), dwell_ms, progress)
        self._run_from(progress)

    def pause(self) -> None:
        # The render thread never reports where it had got to, so the hold is
        # placed from the clock rather than read back off the picture.
        now = _now_ms()
        self._clock.pause(now)
        self._push.setProperty("running", False)
        self._picture.setProperty("scale", zoom_at(self._clock.progress(now)))

    def resume(self) -> None:
        now = _now_ms()
        self._clock.resume(now)
        self._run_from(self._clock.progress(now))

    def retime(self, dwell_ms: int) -> None:
        now = _now_ms()
        self._clock.retime(now, dwell_ms)
        self._dwell_ms = dwell_ms
        self._run_from(self._clock.progress(now))

    def stop(self) -> None:
        self._push.setProperty("running", False)
        self._picture.setProperty("scale", 1.0)

    def release(self) -> None:
        """Put the render thread down here, where its requests can still be
        answered.

        Hiding a shown scene waits for that thread, and a destructor cannot
        answer what it asks for on the way: stopping first means no further
        frame is asked for, and the pumps deliver what it has already posted.
        Left to the widget's death instead, the two wait on each other for good.
        """
        self.stop()
        QCoreApplication.processEvents()
        self._view.hide()
        QCoreApplication.processEvents()

    def _run_from(self, progress: float) -> None:
        self._push.setProperty("running", False)
        self._push.setProperty("startScale", zoom_at(progress))
        self._push.setProperty("remaining",
                               max(1, round((1.0 - progress) * self._dwell_ms)))
        self._push.setProperty("dwell", self._dwell_ms)
        self._push.setProperty("running", True)
