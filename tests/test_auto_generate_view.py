from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QEvent, QUrl
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.auto_generate_view import AutoGenerateView, _MAX_PER_SIDE


def _png(path):
    Image.new("RGB", (16, 16), (20, 80, 160)).save(path, "PNG")
    return str(path)


def _png_bytes():
    import io
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


def _press(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_up_asks_to_cancel_the_current_generation(qtbot):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    fired = []
    view.cancel_requested.connect(lambda: fired.append(True))
    _press(view, Qt.Key.Key_Up)
    assert fired == [True]


def test_down_asks_to_star_the_current_item(qtbot):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    fired = []
    view.star_requested.connect(lambda: fired.append(True))
    _press(view, Qt.Key.Key_Down)
    assert fired == [True]


def test_escape_closes_and_emits_closed(qtbot):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    view.showFullScreen()
    closed = []
    view.closed.connect(lambda: closed.append(True))
    _press(view, Qt.Key.Key_Escape)
    assert not view.isVisible()
    assert closed == [True]


def test_finished_items_accumulate_alternating_out_to_both_sides(qtbot, tmp_path):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    view.add_thumbnail(_png(tmp_path / "a.png"))
    assert len(view._right_thumbs) == 1 and len(view._left_thumbs) == 0
    view.add_thumbnail(_png(tmp_path / "b.png"))
    assert len(view._right_thumbs) == 1 and len(view._left_thumbs) == 1


def test_a_side_keeps_only_a_bounded_recent_history(qtbot, tmp_path):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    png = _png(tmp_path / "t.png")
    for _ in range(_MAX_PER_SIDE * 2 + 4):  # plenty for both sides to overflow
        view.add_thumbnail(png)
    assert len(view._right_thumbs) == _MAX_PER_SIDE
    assert len(view._left_thumbs) == _MAX_PER_SIDE


def test_live_frame_fills_the_centre(qtbot):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    view.show_live_frame(_png_bytes())
    # A streamed frame has no file behind it — the centre shows an image, not a video.
    assert view._preview.is_showing_video() is False
    assert view._preview._media is None


def test_center_media_shows_a_finished_file(qtbot, tmp_path):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    png = _png(tmp_path / "done.png")
    view.show_center_media(png, "image")
    assert view._preview._media == (png, "image")


def test_star_overlay_toggles_and_resets_on_a_new_item(qtbot, tmp_path):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    assert view._star.isHidden()

    view.set_center_starred(True)
    assert not view._star.isHidden()

    # A fresh item taking the centre clears the confirmation.
    view.show_live_frame(_png_bytes())
    assert view._star.isHidden()


def test_closing_releases_the_centre_media_file(qtbot):
    view = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(view)
    view.close()
    view._preview._player.setSource.assert_called_with(QUrl())
