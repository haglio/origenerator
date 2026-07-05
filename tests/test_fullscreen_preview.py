from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QUrl, QEvent
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.fullscreen_preview import FullscreenPreview


def _make_png(path):
    Image.new("RGB", (32, 24), (10, 120, 200)).save(path, "PNG")
    return path


def _escape(win):
    win.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )


def test_shows_the_image(qtbot, tmp_path):
    png = _make_png(tmp_path / "p.png")
    win = FullscreenPreview((png, "image"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview._media == (png, "image")
    assert win._preview.is_showing_video() is False


def test_plays_the_video(qtbot, tmp_path):
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview.is_showing_video() is True
    win._preview._player.play.assert_called_once()


def test_escape_closes_it(qtbot, tmp_path):
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.showFullScreen()
    _escape(win)
    assert not win.isVisible()


def test_double_click_on_the_media_closes_it(qtbot, tmp_path):
    # The click lands on the inner preview (the media fills the window), not the
    # window itself — the reported bug was that only Escape closed it.
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.showFullScreen()
    win._preview.mouseDoubleClickEvent(None)
    assert not win.isVisible()


def test_closing_releases_the_video_file(qtbot, tmp_path):
    # A held media handle blocks move-to-trash on Windows, so closing must drop it.
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    win.close()
    win._preview._player.setSource.assert_called_with(QUrl())


def test_the_fullscreen_preview_does_not_nest_another(qtbot, tmp_path):
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview.open_fullscreen() is None
