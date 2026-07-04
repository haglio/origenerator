"""SlideshowView — the fullscreen player: show, advance, pause, and keys."""

from unittest.mock import MagicMock

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.slideshow_view import SlideshowView

_ITEMS = [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")]


def _view(qtbot, items=_ITEMS, **kw):
    view = SlideshowView(items, player=MagicMock(), **kw)
    qtbot.addWidget(view)
    return view


def _press(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_opens_on_the_first_item(qtbot):
    view = _view(qtbot)
    assert view._playlist.current() == ("a.png", "image")
    assert view._preview.is_showing_video() is False


def test_right_and_left_navigate(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)
    assert view._playlist.current() == ("b.mp4", "video")
    assert view._preview.is_showing_video() is True
    _press(view, Qt.Key.Key_Left)
    assert view._playlist.current() == ("a.png", "image")


def test_a_finished_video_advances_to_the_next(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    view._preview.video_ended.emit()        # it played through
    assert view._playlist.current() == ("c.png", "image")


def test_pausing_stops_a_finished_video_from_advancing(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    _press(view, Qt.Key.Key_Space)          # pause
    view._preview.video_ended.emit()
    assert view._playlist.current() == ("b.mp4", "video")  # stayed put
    assert view._playlist.paused


def test_space_toggles_pause_and_the_caption_reflects_it(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Space)
    assert view._playlist.paused
    assert "paused" in view._counter.text()
    _press(view, Qt.Key.Key_Space)
    assert not view._playlist.paused
    assert "paused" not in view._counter.text()


def test_escape_closes_the_view(qtbot):
    view = _view(qtbot)
    view.show()
    _press(view, Qt.Key.Key_Escape)
    assert not view.isVisible()


def test_up_and_down_adjust_the_dwell(qtbot):
    view = _view(qtbot, image_dwell_ms=4000)
    _press(view, Qt.Key.Key_Up)
    assert view._playlist.image_dwell_ms == 5000
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.image_dwell_ms == 3000


def test_the_caption_shows_position(qtbot):
    view = _view(qtbot)
    assert view._counter.text().startswith("1 / 3")
    _press(view, Qt.Key.Key_Right)
    assert view._counter.text().startswith("2 / 3")
