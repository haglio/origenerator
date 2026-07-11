from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QUrl, QEvent, QSize
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import QApplication

from origenerator.funscript import funscript_path_for, synthesize_actions, write_funscript
from origenerator.gui.fullscreen_preview import FullscreenPreview


def _make_png(path):
    Image.new("RGB", (32, 24), (10, 120, 200)).save(path, "PNG")
    return path


def _make_tall_png(path):
    """A tall image whose aspect ratio doesn't match a wide screen, so a correct
    fit touches the short edges and leaves the long ones letterboxed."""
    Image.new("RGB", (24, 60), (10, 120, 200)).save(path, "PNG")
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


def test_fits_the_image_to_the_screen_without_clipping(qtbot, tmp_path):
    # The image shows as large as it fits the screen with nothing clipped off, and
    # refits when the window grows to fullscreen — the reported "black on all four
    # sides" was the image left scaled at its tiny pre-show size on the full screen.
    win = FullscreenPreview((_make_tall_png(tmp_path / "tall.png"), "image"),
                            player=MagicMock())
    qtbot.addWidget(win)
    label = win._preview._image_label
    old = label.size()
    label.resize(600, 500)  # stand in for the screen the window grows to
    QApplication.sendEvent(label, QResizeEvent(QSize(600, 500), old))
    pm = label.pixmap()
    assert pm.width() <= 600 and pm.height() <= 500        # nothing clipped off
    assert pm.width() == 600 or pm.height() == 500         # as large as it fits


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


def test_watching_a_scripted_video_fullscreen_shows_its_strip(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    win = FullscreenPreview((vid, "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview._strip is not None
    assert win._preview._strip.has_script() is True


def test_plays_audio_unlike_the_muted_inline_preview(qtbot, tmp_path):
    # Double-clicking a clip to watch it fullscreen is deliberate, so it's heard.
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview._audio.isMuted() is False


def test_emits_closed_when_dismissed(qtbot, tmp_path):
    # The gallery listens for this to hand the OSR2 back when the view goes away.
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    closed = []
    win.closed.connect(lambda: closed.append(True))
    win.close()
    assert closed == [True]


def test_osr2_drive_target_bundles_the_scripted_video(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    player = MagicMock()
    win = FullscreenPreview((vid, "video"), player=player)
    qtbot.addWidget(win)
    target = win.osr2_drive_target()
    assert target is not None
    path, tgt_player, actions = target
    assert path == vid and tgt_player is player and actions


def test_osr2_drive_target_is_none_for_an_image(qtbot, tmp_path):
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    assert win.osr2_drive_target() is None


def test_osr2_drive_target_is_none_for_an_unscripted_video(qtbot, tmp_path):
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win.osr2_drive_target() is None
