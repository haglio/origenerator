"""The gallery handed to a session whose room is in the headset."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.fun_time_mode import parse_app_args
from origenerator.gui.headset_window import (
    CAP_PX,
    HeadsetWindow,
    pictures_the_grab_missed,
    within_the_cap,
)
from tests.hosted_launch import hosted_launch


class _Frame:
    def __init__(self, *, valid: bool = True) -> None:
        self._valid = valid

    def isValid(self) -> bool:  # noqa: N802 -- Qt's own spelling
        return self._valid

    def toImage(self) -> QImage:  # noqa: N802 -- Qt's own spelling
        return QImage(2, 2, QImage.Format.Format_RGBA8888)


class _Sink:
    def __init__(self, frame: _Frame | None) -> None:
        self._frame = frame

    def videoFrame(self) -> _Frame | None:  # noqa: N802 -- Qt's own spelling
        return self._frame


class _Video:
    """A video surface, shaped the way the publisher asks one about itself.

    A fake rather than a real ``QVideoWidget``: what is being tested is which
    surfaces are asked for their last frame and where it is placed, and a real
    one would need a window, a media player and a decode to answer.
    """

    def __init__(self, *, sink: _Sink | None, visible: bool = True,
                 at: QPoint | None = None, size: QSize | None = None) -> None:
        self._sink = sink
        self._visible = visible
        self._at = at if at is not None else QPoint(10, 20)
        self._size = size if size is not None else QSize(40, 30)

    def isVisible(self) -> bool:  # noqa: N802 -- Qt's own spelling
        return self._visible

    def videoSink(self) -> _Sink | None:  # noqa: N802 -- Qt's own spelling
        return self._sink

    def mapTo(self, _window, _origin) -> QPoint:  # noqa: N802 -- Qt's own spelling
        return self._at

    def size(self) -> QSize:
        return self._size


class TestThePictureAGrabCannotReach:
    """A video plays on the media player's own surface, so the paint pass a grab
    leaves it blank.  The last frame that surface handed its sink
    is the only picture of it there is, which is how one is dragged too."""

    def test_a_playing_surface_is_placed_where_it_sits_in_the_window(self):
        playing = _Video(sink=_Sink(_Frame()), at=QPoint(7, 9), size=QSize(50, 40))

        (patch,) = pictures_the_grab_missed(None, [playing])

        assert (patch.at, patch.width, patch.height) == (QPoint(7, 9), 50, 40)

    def test_a_surface_nobody_can_see_is_left_out(self):
        hidden = _Video(sink=_Sink(_Frame()), visible=False)

        assert pictures_the_grab_missed(None, [hidden]) == []

    def test_a_surface_with_no_frame_yet_is_left_out(self):
        """A pane whose video has decoded nothing has no picture to hand over,
        and blank is a truer answer than the frame before it."""
        assert pictures_the_grab_missed(None, [_Video(sink=_Sink(None))]) == []
        assert pictures_the_grab_missed(
            None, [_Video(sink=_Sink(_Frame(valid=False)))]) == []

    def test_a_pane_with_no_sink_at_all_is_left_out(self):
        assert pictures_the_grab_missed(None, [_Video(sink=None)]) == []


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

    def _hosted(self, tmp_path):
        return parse_app_args(hosted_launch(headset=True, **{
            "--frames-file": str(tmp_path / "frame.bin"),
            "--input-file": str(tmp_path / "input.txt"),
            "--width": "200",
            "--height": "100",
        })).fun_time

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
        headset = HeadsetWindow(window, self._hosted(tmp_path))
        try:
            headset._heard("press 25 35")
        finally:
            headset.close()

        assert pressed == ["5,5"], "the press did not arrive where it was aimed"

    def test_a_press_with_no_pixel_is_dropped_rather_than_guessed(self, tmp_path, qtbot):
        """The room writes the pixel with the word; a line short of one is a
        line to say something about, not to aim at the last place it knew."""
        window = self._window(qtbot)
        headset = HeadsetWindow(window, self._hosted(tmp_path))
        try:
            headset._heard("press")
            headset._heard("press 4")
        finally:
            headset.close()

    def test_the_window_is_published_once_for_each_way_it_looks(self, tmp_path, qtbot):
        """A window nobody is touching looks the same every frame, and a frame
        the room already has is a frame not worth the write."""
        import struct

        def published() -> tuple[int, int, int]:
            """(sequence, width, height) off the channel's header -- read here
            rather than through a reader of our own, the reader being the
            session's (``app_support.frame_channel``)."""
            header = (tmp_path / "frame.bin").read_bytes()[:20]
            sequence, _token, width, height = struct.unpack("<QIII", header)
            return sequence, width, height

        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, self._hosted(tmp_path))
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
