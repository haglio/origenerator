from __future__ import annotations

import os
import struct
import sys
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QApplication
from shared_ui.gui_thread_collection import the_application

from origenerator.gui.headset_window import HeadsetWindow
from origenerator.gui.viewport import Viewport
from tests.children import run_python
from tests.hosted_launch import a_headset_session_publishing_into

# Qt Quick draws a video frame only through a graphics card, and the suite's offscreen platform has none
GRAPHICS_CARD_PLATFORM = {"QT_QPA_PLATFORM": "windows"}


def drawn_on_the_graphics_card(check: str, folder: Path) -> QColor:
    ran = run_python(["-m", __name__, check, str(folder)], env=os.environ | GRAPHICS_CARD_PLATFORM)
    assert ran.returncode == 0, ran.stderr
    return QColor(ran.stdout.strip())


def _a_red_video_in_a_preview(folder: Path) -> Viewport:
    preview = Viewport(player=MagicMock())
    preview.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    preview.resize(320, 240)
    preview.show()
    preview.show_video(folder / "clip.mp4")
    red = QImage(64, 36, QImage.Format.Format_RGB32)
    red.fill(QColor("red"))
    preview._video.video_sink().setVideoFrame(QVideoFrame(red))
    return preview


def _middle_of_the_media(preview: Viewport) -> QColor:
    shot = preview._media_host.grab().toImage()
    return shot.pixelColor(shot.width() // 2, shot.height() // 2)


def the_middle_of_a_playing_video(folder: Path) -> QColor:
    return _middle_of_the_media(_a_red_video_in_a_preview(folder))


def the_middle_of_a_video_under_a_message(folder: Path) -> QColor:
    preview = _a_red_video_in_a_preview(folder)
    preview.set_message("(not yet generated with modifications)")
    return _middle_of_the_media(preview)


def the_middle_of_the_frame_the_room_gets(folder: Path) -> QColor:
    preview = _a_red_video_in_a_preview(folder)
    headset = HeadsetWindow(preview, a_headset_session_publishing_into(folder))
    try:
        headset.publish(now=1.0)
    finally:
        headset.close()
    middle = preview._video.mapTo(preview, preview._video.rect().center())
    return _published_color(folder / "frame.bin", middle)


def _published_color(frames: Path, at: QPoint) -> QColor:
    published = frames.read_bytes()
    _sequence, _token, width, _height = struct.unpack("<QIII", published[:20])
    pixel = 20 + (at.y() * width + at.x()) * 4
    red, green, blue = published[pixel:pixel + 3]
    return QColor(red, green, blue)


CHECKS = {check.__name__: check for check in (
    the_middle_of_a_playing_video,
    the_middle_of_a_video_under_a_message,
    the_middle_of_the_frame_the_room_gets,
)}


if __name__ == "__main__":
    app = the_application(QApplication, [])
    print(CHECKS[sys.argv[1]](Path(sys.argv[2])).name())
