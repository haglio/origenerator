"""The gallery handed to a session whose room is in the headset."""
from __future__ import annotations

import struct
from unittest.mock import MagicMock

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtMultimedia import QVideoFrame
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.fun_time_mode import parse_app_args
from origenerator.gui.headset_window import (
    CAP_PX,
    HeadsetWindow,
    within_the_cap,
)
from origenerator.gui.preview_widget import PreviewWidget
from tests.hosted_launch import hosted_launch


def _hosted(tmp_path):
    return parse_app_args(hosted_launch(headset=True, **{
        "--frames-file": str(tmp_path / "frame.bin"),
        "--input-file": str(tmp_path / "input.txt"),
        "--width": "200",
        "--height": "100",
    })).fun_time


def _published_color(tmp_path, at: QPoint) -> QColor:
    published = (tmp_path / "frame.bin").read_bytes()
    _sequence, _token, width, _height = struct.unpack("<QIII", published[:20])
    pixel = 20 + (at.y() * width + at.x()) * 4
    red, green, blue = published[pixel:pixel + 3]
    return QColor(red, green, blue)


def test_the_frame_a_preview_is_playing_is_in_the_picture_the_room_gets(tmp_path, qtbot):
    preview = PreviewWidget(player=MagicMock())
    qtbot.addWidget(preview)
    preview.resize(200, 100)
    preview.show()
    preview.show_video(tmp_path / "clip.mp4")
    red = QImage(64, 36, QImage.Format.Format_RGB32)
    red.fill(QColor("red"))
    preview._video.video_sink().setVideoFrame(QVideoFrame(red))

    headset = HeadsetWindow(preview, _hosted(tmp_path))
    try:
        headset.publish(now=1.0)
    finally:
        headset.close()

    middle = preview._video.mapTo(preview, preview._video.rect().center())
    assert _published_color(tmp_path, middle) == QColor("red")


class TestHowBigAPublishedPictureMayBe:
    """The rect a session names is not a promise about the window: Qt gives it
    the size its own minimums allow, and it can be resized after.  So the
    channel is sized to a cap and anything bigger is scaled into it, rather
    than refused with a frame nobody gets."""

    def test_a_window_within_the_cap_is_published_at_its_own_size(self):
        picture = QImage(200, 100, QImage.Format.Format_RGBA8888)

        assert within_the_cap(picture).size() == picture.size()

    def test_a_window_past_the_cap_is_scaled_until_it_fits(self):
        within = within_the_cap(QImage(CAP_PX * 2, CAP_PX, QImage.Format.Format_RGBA8888))

        assert within.width() == CAP_PX
        assert within.height() == CAP_PX // 2
        assert within.format() == QImage.Format.Format_RGBA8888


class TestTheRoomsPressesReachTheWindow:
    """The room's pointer lands on a pixel of the published picture, and this
    window has to feel it where a mouse on that pixel would have landed."""

    def _window(self, qtbot) -> QWidget:
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(200, 100)
        label = QLabel("x", window)
        label.setObjectName("target")
        label.setGeometry(20, 30, 60, 20)
        return window

    def test_a_press_lands_on_the_widget_under_that_pixel(self, tmp_path, qtbot):
        window = self._window(qtbot)
        pressed: list[str] = []
        window.findChild(QLabel, "target").mousePressEvent = (
            lambda event: pressed.append(
                f"{event.position().x():.0f},{event.position().y():.0f}"))
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset._heard("press 25 35")
        finally:
            headset.close()

        assert pressed == ["5,5"], "the press did not arrive where it was aimed"

    def test_a_press_with_no_pixel_is_dropped_rather_than_guessed(self, tmp_path, qtbot):
        """The room writes the pixel with the word; a line short of one is a
        line to say something about, not to aim at the last place it knew."""
        window = self._window(qtbot)
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset._heard("press")
            headset._heard("press 4")
        finally:
            headset.close()

    def test_the_window_is_published_once_for_each_way_it_looks(self, tmp_path, qtbot):
        """A window nobody is touching looks the same every frame, and a frame
        the room already has is a frame not worth the write."""
        def published() -> tuple[int, int, int]:
            """(sequence, width, height) off the channel's header -- read here
            rather than through a reader of our own, the reader being the
            session's (``app_support.frame_channel``)."""
            header = (tmp_path / "frame.bin").read_bytes()[:20]
            sequence, _token, width, height = struct.unpack("<QIII", header)
            return sequence, width, height

        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            first = published()
            headset.publish(now=2.0)
            again = published()
        finally:
            headset.close()

        assert first[1] == window.width(), "the window was not published at its own width"
        assert first[0] % 2 == 0, "the frame was left mid-write"
        assert again == first, "the same picture was published twice"
