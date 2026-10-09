"""The gallery handed to a session whose room is in the headset."""
from __future__ import annotations

import logging
import struct
from unittest.mock import MagicMock

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtMultimedia import QVideoFrame
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QMenu, QWidget

from origenerator.fun_time_mode import parse_app_args
from origenerator.gui.drag_thumbnail import DragOut
from origenerator.gui.headset_window import (
    _IDLE_LOOK_S,
    CAP_PX,
    HeadsetWindow,
    windows_opened_over,
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


def test_presses_the_channel_cannot_read_name_themselves(tmp_path, qtbot, caplog):
    """The channel drops a press file it cannot read and says nothing unless it
    is given a logger, and a room whose presses go nowhere looks to him exactly
    like one whose screen is dead -- which is what his 2026-10-08 session was."""
    window = QWidget()
    window.resize(200, 100)
    qtbot.addWidget(window)
    window.show()
    headset = HeadsetWindow(window, _hosted(tmp_path))
    (tmp_path / "input.txt").write_bytes(b"\xff\xfe press 1 1")
    try:
        with caplog.at_level(logging.WARNING):
            headset._tick()
    finally:
        headset.close()

    assert "input.txt" in caplog.text


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

    def test_a_right_click_asks_the_widget_under_it_for_its_menu(self, tmp_path, qtbot):
        window = self._window(qtbot)
        target = window.findChild(QLabel, "target")
        target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        asked: list[str] = []
        target.customContextMenuRequested.connect(
            lambda at: asked.append(f"{at.x()},{at.y()}"))
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset._heard("rightclick 25 35")
        finally:
            headset.close()

        assert asked == ["5,5"], "the menu was not asked for where it was aimed"

    def test_a_press_lands_where_it_was_aimed_on_a_picture_drawn_smaller(
            self, tmp_path, qtbot):
        """A picture the room presses is not always the window's own size: past
        the cap it is published scaled, and hosted this app draws at a scale of
        its own, so a pixel of it is that many Qt coordinates of the window."""
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(CAP_PX * 2, CAP_PX)  # published at half of that
        label = QLabel("x", window)
        label.setObjectName("target")
        label.setGeometry(CAP_PX, 200, 400, 200)
        window.show()
        pressed: list[str] = []
        label.mousePressEvent = (
            lambda event: pressed.append(
                f"{event.position().x():.0f},{event.position().y():.0f}"))
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard(f"press {CAP_PX // 2 + 50} 150")
        finally:
            headset.close()

        assert pressed == ["100,100"], "the press did not arrive where it was aimed"

    def test_a_hand_that_shakes_on_the_trigger_starts_no_drag(self, tmp_path, qtbot):
        """The room sends a pull of the trigger as a press, a few moves as the
        hand shakes, and a release.  A move carried far enough starts a drag,
        and Windows runs a drag off the real mouse -- the one nobody holds in a
        headset -- so the app waits on it and stops: its picture, the room's
        presses, the session's own verbs, all of it until the session kills it."""
        window = self._window(qtbot)
        label = window.findChild(QLabel, "target")
        gesture = DragOut()
        dragged: list[bool] = []
        label.mousePressEvent = gesture.note_press
        label.mouseMoveEvent = lambda event: dragged.append(gesture.should_start(event))
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset._heard("press 25 35")
            headset._heard("drag 75 45")
            headset._heard("release")
        finally:
            headset.close()

        assert dragged == [False], "a shake of the laser started a drag"

    def test_the_rest_of_the_app_drags_as_it_did_before(self, tmp_path, qtbot):
        """How far a move must go to become a drag is the whole app's setting;
        it is held out of reach only while the room's own event is delivered."""
        before = QApplication.startDragDistance()
        headset = HeadsetWindow(self._window(qtbot), _hosted(tmp_path))
        try:
            headset._heard("press 25 35")
            headset._heard("drag 75 45")
            headset._heard("release")
        finally:
            headset.close()

        assert QApplication.startDragDistance() == before

    def test_a_release_whose_press_took_its_widget_away_is_dropped(self, tmp_path, qtbot):
        """A press on a folder square opens the folder, and the grid it opens
        is built new: the square the press landed on is gone by the time the
        trigger lets go.  The release goes nowhere, rather than to a widget
        that no longer exists -- which raised, and took the app down."""
        window = self._window(qtbot)
        label = window.findChild(QLabel, "target")
        label.mousePressEvent = lambda event: label.deleteLater()
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset._heard("press 25 35")
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            headset._heard("drag 26 35")
            headset._heard("release")
        finally:
            headset.close()

        assert sip.isdeleted(label)

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


    def _counting_grabs(self, window) -> list[int]:
        grabbed: list[int] = []
        grab = window.grab

        def counted(*args, **kwargs):
            grabbed.append(1)
            return grab(*args, **kwargs)

        window.grab = counted
        return grabbed

    def test_a_hover_alone_does_not_grab_the_window_again(self, tmp_path, qtbot):
        """Pointing at the window is not a change to it, and the room sends a
        hover every time the laser moves a pixel: taken as a reason to look, each
        one costs a grab of the whole window at the poll's rate.  In the headset
        that halved the room's frame rate, and the players stopped showing new
        frames while he pointed at the gallery."""
        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            grabbed = self._counting_grabs(window)

            headset._heard("hover 30 40")
            headset.publish(now=1.0 + _IDLE_LOOK_S / 2)

            assert grabbed == []
        finally:
            headset.close()

    def test_a_press_has_it_looked_at_once(self, tmp_path, qtbot):
        """What a press does to the window is what the room is waiting to see,
        so that one is worth the grab it costs."""
        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            grabbed = self._counting_grabs(window)

            headset._heard("press 30 40")
            headset.publish(now=1.0 + _IDLE_LOOK_S / 2)

            assert grabbed == [1]
        finally:
            headset.close()


class TestWhatOpensOverTheWindow:
    """A menu, a dropped-down list or a dialog is a window of its own, opened
    over this one: a grab of this one alone leaves it out, and a press aimed at
    it lands on whatever of this window is underneath."""

    def _window(self, qtbot) -> QWidget:
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(300, 300)
        window.show()
        return window

    def test_a_list_dropped_from_the_room_is_chosen_from_in_the_room(self, tmp_path, qtbot):
        window = self._window(qtbot)
        combo = QComboBox(window)
        combo.addItems(["alpha", "beta", "gamma"])
        combo.setGeometry(20, 20, 120, 24)
        combo.show()
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("press 30 30")
            headset._heard("release")
            qtbot.waitUntil(combo.view().isVisible)
            # A list ignores a release as soon after it opens as a double-click:
            # it takes it for the release of the press that opened it.
            qtbot.wait(QApplication.doubleClickInterval() + 100)
            view = combo.view()
            item = view.visualRect(combo.model().index(2, 0)).center()
            at = window.mapFromGlobal(view.viewport().mapToGlobal(item))
            headset._heard(f"hover {at.x()} {at.y()}")
            headset._heard(f"press {at.x()} {at.y()}")
            headset._heard("release")
        finally:
            headset.close()

        assert combo.currentText() == "gamma"

    def test_a_menu_open_over_the_window_is_in_its_picture(self, tmp_path, qtbot):
        window = self._window(qtbot)
        menu = QMenu(window)
        menu.addAction("one")
        menu.popup(window.mapToGlobal(QPoint(40, 60)))
        qtbot.waitUntil(menu.isVisible)
        at = window.mapFromGlobal(menu.mapToGlobal(QPoint(0, 0)))

        (patch,) = windows_opened_over(window, scale=0.5)

        assert patch.at == QPoint(round(at.x() * 0.5), round(at.y() * 0.5))
        assert (patch.width, patch.height) == (
            round(menu.width() * 0.5), round(menu.height() * 0.5))
        menu.close()

    def test_a_press_off_a_menu_puts_it_away(self, tmp_path, qtbot):
        """As a mouse pressed anywhere else would: a list left open is a list
        covering the picture until something else closes it."""
        window = self._window(qtbot)
        menu = QMenu(window)
        menu.addAction("one")
        menu.popup(window.mapToGlobal(QPoint(150, 150)))
        qtbot.waitUntil(menu.isVisible)
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("press 10 10")
            headset._heard("release")
        finally:
            headset.close()

        assert not menu.isVisible()

    def test_a_press_off_an_open_dialog_is_refused_as_a_mouse_would_be(
            self, tmp_path, qtbot):
        """A dialog waiting on an answer holds the window under it still; a press
        that reached past it would act while the question was still standing."""
        window = self._window(qtbot)
        label = QLabel("x", window)
        label.setGeometry(10, 10, 40, 20)
        label.show()
        pressed: list[bool] = []
        label.mousePressEvent = lambda event: pressed.append(True)
        dialog = QDialog(window)
        dialog.setModal(True)
        dialog.resize(60, 60)
        dialog.show()
        qtbot.waitUntil(dialog.isVisible)
        headset = HeadsetWindow(window, _hosted(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("press 20 15")
            headset._heard("release")
        finally:
            headset.close()
            dialog.close()

        assert pressed == []
