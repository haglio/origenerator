from __future__ import annotations

import logging
import struct
import threading

import shiboken6
from app_support.frame_channel import LOOK_AGAIN_AFTER_S
from app_support.threading_utils import wait_until
from funestra.file_channel import append_command, consume_command_file
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QMenu, QWidget

from origenerator.gui import headset_window
from origenerator.gui.drag_thumbnail import DragOut
from origenerator.gui.headset_window import (
    CAP_PX,
    HEARTBEAT_S,
    HeadsetWindow,
    PressReader,
    windows_opened_over,
    within_the_cap,
)
from tests.drawn_on_the_graphics_card import drawn_on_the_graphics_card
from tests.hosted_launch import a_headset_session_publishing_into


def test_the_poll_says_how_much_it_has_handled_while_the_room_has_it(
        tmp_path, qtbot, caplog):
    window = QWidget()
    window.resize(200, 100)
    qtbot.addWidget(window)
    window.show()
    headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
    try:
        with caplog.at_level(logging.INFO):
            headset.publish(now=1.0)
            headset.said_how_it_goes(now=1.0)
            headset.said_how_it_goes(now=1.0 + HEARTBEAT_S / 2)
            beats = caplog.text.count("Still publishing")
            headset.said_how_it_goes(now=1.0 + HEARTBEAT_S + 0.01)
    finally:
        headset.close()

    assert beats == 0, "it spoke before the first heartbeat was due"
    assert caplog.text.count("Still publishing") == 1, (
        "a line at a steady beat puts the moment the room stopped taking presses in the log")
    assert "(1 published, 0 presses taken)" in caplog.text


def test_presses_the_channel_cannot_read_name_themselves(tmp_path, qtbot, caplog):
    window = QWidget()
    window.resize(200, 100)
    qtbot.addWidget(window)
    window.show()
    headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
    (tmp_path / "input.txt").write_bytes(b"\xff\xfe press 1 1")
    try:
        with caplog.at_level(logging.WARNING):
            wait_until(lambda: "input.txt" in caplog.text)
    finally:
        headset.close()

    assert "input.txt" in caplog.text, (
        "a room whose presses go nowhere looks exactly like one whose screen is dead")


def test_the_presses_file_is_read_off_the_windows_thread(tmp_path):
    read_on: list[int] = []

    def read(path, **kwargs):
        read_on.append(threading.get_ident())
        return consume_command_file(path, **kwargs)

    presses = PressReader(tmp_path / "input.txt", read=read).start()
    try:
        append_command(tmp_path / "input.txt", "press 1 2")
        taken: list[str] = []
        wait_until(lambda: taken.extend(presses.taken()) or taken)
    finally:
        presses.stop()

    assert taken == ["press 1 2"]
    assert threading.get_ident() not in read_on, (
        "renaming, reading and deleting the presses file took 4.5 ms on average and 88 ms at "
        "worst on his computer, and the room writes it 90 times a second, so on the window's "
        "thread it held the window still while he pointed")


def test_a_tick_hands_over_the_presses_already_read_without_opening_the_file(tmp_path, qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(200, 100)
    label = QLabel("x", window)
    label.setGeometry(20, 30, 60, 20)
    pressed = _presses_on(label)

    class _ReadAlready:
        def taken(self):
            return ["press 25 35"]

        def stop(self):
            pass

    headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path),
                            presses=_ReadAlready())
    try:
        headset._tick()
    finally:
        headset.close()

    assert pressed == ["5,5"]


def test_the_frame_a_preview_is_playing_is_in_the_frame_the_room_gets(tmp_path):
    assert drawn_on_the_graphics_card(
        "the_middle_of_the_frame_the_room_gets", tmp_path) == QColor("red")


class TestHowBigAPublishedFrameMayBe:
    def test_a_window_within_the_cap_is_published_at_its_own_size(self):
        frame = QImage(200, 100, QImage.Format.Format_RGBA8888)

        assert within_the_cap(frame).size() == frame.size()

    def test_a_window_past_the_cap_is_scaled_until_it_fits(self):
        within = within_the_cap(QImage(CAP_PX * 2, CAP_PX, QImage.Format.Format_RGBA8888))

        assert within.width() == CAP_PX
        assert within.height() == CAP_PX // 2
        assert within.format() == QImage.Format.Format_RGBA8888


def _counting_looks(monkeypatch) -> list[int]:
    looked: list[int] = []
    look = headset_window.what_the_window_shows

    def counted(window):
        looked.append(1)
        return look(window)

    monkeypatch.setattr(headset_window, "what_the_window_shows", counted)
    return looked


def _presses_on(label: QLabel) -> list[str]:
    pressed: list[str] = []
    label.mousePressEvent = (
        lambda event: pressed.append(f"{event.position().x():.0f},{event.position().y():.0f}"))
    return pressed


class TestTheRoomsPressesReachTheWindow:
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
        pressed = _presses_on(window.findChild(QLabel, "target"))
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset._heard("press 25 35")
        finally:
            headset.close()

        assert pressed == ["5,5"], "the press did not arrive where it was aimed"

    def test_a_right_click_is_handed_over_without_waiting_for_what_it_opens(
            self, tmp_path, qtbot):
        # Qt's menu.exec() runs an event loop of its own, so a click handed over inside the poll's tick never returns.
        window = self._window(qtbot)
        opened: list[str] = []
        window.contextMenuEvent = lambda event: opened.append("menu")
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("rightclick 20 15")

            assert opened == [], "the poll waited for the menu it opened"

            QApplication.processEvents()
        finally:
            headset.close()

        assert opened == ["menu"]

    def test_a_right_click_asks_the_widget_under_it_for_its_menu(self, tmp_path, qtbot):
        window = self._window(qtbot)
        target = window.findChild(QLabel, "target")
        target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        asked: list[str] = []
        target.customContextMenuRequested.connect(
            lambda at: asked.append(f"{at.x()},{at.y()}"))
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset._heard("rightclick 25 35")
            QApplication.processEvents()
        finally:
            headset.close()

        assert asked == ["5,5"], "the menu was not asked for where it was aimed"

    def test_a_press_lands_where_it_was_aimed_on_a_frame_drawn_smaller(
            self, tmp_path, qtbot):
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(CAP_PX * 2, CAP_PX)
        label = QLabel("x", window)
        label.setObjectName("target")
        label.setGeometry(CAP_PX, 200, 400, 200)
        window.show()
        pressed = _presses_on(label)
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard(f"press {CAP_PX // 2 + 50} 150")
        finally:
            headset.close()

        assert pressed == ["100,100"], "the press did not arrive where it was aimed"

    def test_a_hand_that_shakes_on_the_trigger_starts_no_drag(self, tmp_path, qtbot):
        # A Qt drag runs off the real mouse, which nobody holds in a headset, so the app would wait on it forever.
        window = self._window(qtbot)
        label = window.findChild(QLabel, "target")
        gesture = DragOut()
        dragged: list[bool] = []
        label.mousePressEvent = gesture.note_press
        label.mouseMoveEvent = lambda event: dragged.append(gesture.should_start(event))
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset._heard("press 25 35")
            headset._heard("drag 75 45")
            headset._heard("release")
        finally:
            headset.close()

        assert dragged == [False], "a shake of the laser started a drag"

    def test_the_rest_of_the_app_drags_as_it_did_before(self, tmp_path, qtbot):
        before = QApplication.startDragDistance()
        headset = HeadsetWindow(self._window(qtbot), a_headset_session_publishing_into(tmp_path))
        try:
            headset._heard("press 25 35")
            headset._heard("drag 75 45")
            headset._heard("release")
        finally:
            headset.close()

        assert QApplication.startDragDistance() == before

    def test_a_release_whose_press_took_its_widget_away_is_dropped(self, tmp_path, qtbot):
        window = self._window(qtbot)
        label = window.findChild(QLabel, "target")
        label.mousePressEvent = lambda event: label.deleteLater()
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset._heard("press 25 35")
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            headset._heard("drag 26 35")
            headset._heard("release")
        finally:
            headset.close()

        assert not shiboken6.isValid(label)

    def test_a_press_with_no_pixel_is_dropped_rather_than_guessed(self, tmp_path, qtbot, caplog):
        window = self._window(qtbot)
        pressed = _presses_on(window.findChild(QLabel, "target"))
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset._heard("press 25 35")
            headset._heard("release")
            with caplog.at_level(logging.WARNING):
                headset._heard("press")
                headset._heard("press 4")
        finally:
            headset.close()

        assert pressed == ["5,5"], "a press with no pixel was aimed at the last place the pointer was"
        assert caplog.text.count("A headset press with no pixel") == 2, (
            "a line short of a pixel is a line to say something about")

    def test_the_window_is_published_once_for_each_way_it_looks(self, tmp_path, qtbot):
        def published() -> tuple[int, int, int]:
            header = (tmp_path / "frame.bin").read_bytes()[:20]
            sequence, _token, width, height = struct.unpack("<QIII", header)
            return sequence, width, height

        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            first = published()
            headset.publish(now=2.0)
            again = published()
        finally:
            headset.close()

        assert first[1] == window.width(), "the window was not published at its own width"
        assert first[0] % 2 == 0, "the frame was left mid-write"
        assert again == first, "the same frame was published twice"


    def test_a_hover_alone_does_not_grab_the_window_again(self, tmp_path, qtbot, monkeypatch):
        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            looked = _counting_looks(monkeypatch)

            headset._heard("hover 30 40")
            headset.publish(now=1.0 + LOOK_AGAIN_AFTER_S / 2)

            assert looked == [], (
                "pointing at the window is not a change to it, and the room sends a hover every "
                "time the laser moves a pixel: taken as a reason to look, each one costs a grab "
                "of the whole window at the poll's rate, which in the headset halved the room's "
                "frame rate and stopped the Funestras showing new frames while the user pointed "
                "at the gallery")
        finally:
            headset.close()

    def test_a_press_that_changes_the_window_has_it_looked_at_without_waiting(
            self, tmp_path, qtbot, monkeypatch):
        window = self._window(qtbot)
        window.show()
        label = window.findChild(QLabel, "target")
        label.mousePressEvent = lambda event: label.setText("pressed")
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            looked = _counting_looks(monkeypatch)

            headset._heard("press 30 40")
            QApplication.processEvents()
            headset.publish(now=1.0 + LOOK_AGAIN_AFTER_S / 2)

            assert looked == [1], (
                "what a press does to the window is what the room is waiting to see, so that "
                "one is worth the grab it costs")
        finally:
            headset.close()

    def test_a_window_nothing_has_changed_on_is_never_looked_at_again(
            self, tmp_path, qtbot, monkeypatch):
        window = self._window(qtbot)
        window.show()
        QApplication.processEvents()
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            looked = _counting_looks(monkeypatch)

            headset._heard("press 30 40")
            headset._heard("release")
            for tick in range(1, 6):
                QApplication.processEvents()
                headset.publish(now=1.0 + tick * LOOK_AGAIN_AFTER_S)

            assert looked == [], (
                "a look copies the whole window and compares it, so a window that looks as it "
                "did is never looked at, however often the timer comes round")
        finally:
            headset.close()

    def test_a_change_on_the_window_is_looked_at_once(self, tmp_path, qtbot, monkeypatch):
        window = self._window(qtbot)
        window.show()
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            looked = _counting_looks(monkeypatch)

            window.findChild(QLabel, "target").setText("changed")
            for tick in range(1, 6):
                QApplication.processEvents()
                headset.publish(now=1.0 + tick * LOOK_AGAIN_AFTER_S)

            assert looked == [1]
        finally:
            headset.close()


class _Paints(QObject):
    def __init__(self, *widgets: QWidget) -> None:
        super().__init__()
        self.of: list[str] = []
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            self.of.append(type(watched).__name__)
        return False


def _frame_pixels(tmp_path) -> tuple[int, int, bytes]:
    published = (tmp_path / "frame.bin").read_bytes()
    _sequence, _token, width, height = struct.unpack("<QIII", published[:20])
    return width, height, published[20:20 + width * height * 4]


def _grabbed_pixels(window) -> tuple[int, int, bytes]:
    image = window.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return image.width(), image.height(), bytes(image.constBits())


class TestWhatTheFrameShows:
    def _window(self, qtbot, *, on_screen=True) -> QWidget:
        window = QWidget()
        qtbot.addWidget(window)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, not on_screen)
        window.resize(240, 160)
        label = QLabel("a made-up line", window)
        label.setGeometry(20, 30, 120, 20)
        window.show()
        wait_until(lambda: window.windowHandle().isExposed() or not on_screen,
                   pump=QApplication.processEvents)
        QApplication.processEvents()
        return window

    def test_the_frame_is_the_window_as_it_last_drew_itself_without_drawing_it_again(
            self, tmp_path, qtbot):
        window = self._window(qtbot)
        paints = _Paints(window.findChild(QLabel))
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
        finally:
            headset.close()

        assert paints.of == [], (
            "drawing the whole window again for each frame, the TOC and every tile included, "
            "was most of what held the window still while he pointed in the headset; the "
            "window already holds what it drew for the screen")
        assert _frame_pixels(tmp_path) == _grabbed_pixels(window)

    def test_a_window_that_draws_nothing_for_the_screen_is_drawn_for_its_frame(
            self, tmp_path, qtbot):
        window = self._window(qtbot, on_screen=False)
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
        finally:
            headset.close()

        assert _frame_pixels(tmp_path) == _grabbed_pixels(window)

    def test_what_the_graphics_card_draws_is_drawn_again_and_nothing_else(
            self, tmp_path, qtbot):
        window = self._window(qtbot)
        in_qt_quick = QQuickWidget(window)
        in_qt_quick.setGeometry(150, 40, 60, 50)
        in_qt_quick.show()
        QApplication.processEvents()
        paints = _Paints(window.findChild(QLabel), in_qt_quick)
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
        finally:
            headset.close()

        assert paints.of == ["QQuickWidget"], (
            "a video playing in a preview is drawn on the graphics card and is missing from "
            "what the window drew for the screen, so its part is drawn again for the frame")


class TestWhatOpensOverTheWindow:
    def _window(self, qtbot) -> QWidget:
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(300, 300)
        window.show()
        return window

    def test_a_list_dropped_from_the_room_is_chosen_from_in_the_room(self, tmp_path, qtbot):
        window = self._window(qtbot)
        dropdown = QComboBox(window)
        dropdown.addItems(["alpha", "beta", "gamma"])
        dropdown.setGeometry(20, 20, 120, 24)
        dropdown.show()
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("press 30 30")
            headset._heard("release")
            qtbot.waitUntil(dropdown.view().isVisible)
            # A Qt list ignores a release within a double-click interval of opening.
            qtbot.wait(QApplication.doubleClickInterval() + 100)
            view = dropdown.view()
            item = view.visualRect(dropdown.model().index(2, 0)).center()
            at = window.mapFromGlobal(view.viewport().mapToGlobal(item))
            headset._heard(f"hover {at.x()} {at.y()}")
            headset._heard(f"press {at.x()} {at.y()}")
            headset._heard("release")
        finally:
            headset.close()

        assert dropdown.currentText() == "gamma"

    def test_a_menu_open_over_the_window_is_in_its_frame(self, tmp_path, qtbot):
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

    def test_a_menu_that_opens_over_a_published_window_is_grabbed_into_it(
            self, tmp_path, qtbot, monkeypatch):
        window = self._window(qtbot)
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        menu = QMenu(window)
        menu.addAction("one")
        try:
            headset.publish(now=1.0)
            looked = _counting_looks(monkeypatch)

            menu.popup(window.mapToGlobal(QPoint(40, 60)))
            wait_until(menu.isVisible, pump=QApplication.processEvents)
            headset.publish(now=1.0 + LOOK_AGAIN_AFTER_S)
            QApplication.processEvents()
            headset.publish(now=1.0 + 2 * LOOK_AGAIN_AFTER_S)
            menu.close()
            QApplication.processEvents()
            headset.publish(now=1.0 + 3 * LOOK_AGAIN_AFTER_S)
        finally:
            headset.close()
            menu.close()

        assert looked == [1, 1], "the menu opening and the menu closing are each one grab"

    def test_a_menu_open_over_the_window_is_off_the_monitors_too(
            self, tmp_path, qtbot, monkeypatch):
        window = self._window(qtbot)
        menu = QMenu(window)
        menu.addAction("one")
        menu.popup(window.mapToGlobal(QPoint(40, 60)))
        qtbot.waitUntil(menu.isVisible)
        its_window = int(menu.winId())
        hidden = []
        monkeypatch.setattr(headset_window, "keep_out_of_sight", hidden.append)
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
        finally:
            headset.close()
            menu.close()

        assert hidden == [its_window]

    def test_a_press_off_a_menu_puts_it_away(self, tmp_path, qtbot):
        window = self._window(qtbot)
        menu = QMenu(window)
        menu.addAction("one")
        menu.popup(window.mapToGlobal(QPoint(150, 150)))
        qtbot.waitUntil(menu.isVisible)
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("press 10 10")
            headset._heard("release")
        finally:
            headset.close()

        assert not menu.isVisible()

    def test_a_press_off_an_open_dialog_is_refused_as_a_mouse_would_be(
            self, tmp_path, qtbot):
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
        headset = HeadsetWindow(window, a_headset_session_publishing_into(tmp_path))
        try:
            headset.publish(now=1.0)
            headset._heard("press 20 15")
            headset._heard("release")
        finally:
            headset.close()
            dialog.close()

        assert pressed == []
