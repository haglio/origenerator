from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QWidget
from PyQt6.QtMultimedia import QMediaPlayer

import origenerator.gui.fullscreen_preview as fullscreen_preview
from origenerator.gui.preview_widget import PreviewWidget


def _make_png(path):
    Image.new("RGB", (32, 24), (10, 120, 200)).save(path, "PNG")
    return path


def _png_bytes():
    buf = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _make_animated_gif(path):
    frames = [Image.new("RGB", (16, 12), (i * 60, 0, 0)) for i in range(3)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return path


@pytest.fixture
def make_preview(qtbot):
    """Build PreviewWidgets backed by a mock player.

    The real QtMultimedia backend deadlocks at session shutdown if a player has
    been started, so unit tests inject a mock and assert playback *intent*
    (setSource/play/stop calls) rather than driving the backend.
    """
    def _make():
        w = PreviewWidget(player=MagicMock())
        qtbot.addWidget(w)
        return w

    return _make


def test_preview_starts_with_placeholder(make_preview):
    w = make_preview()
    assert w.is_showing_video() is False
    assert w._image_label.pixmap().isNull()


def test_show_image_displays_scaled_pixmap(make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_make_png(tmp_path / "p.png"))
    pm = w._image_label.pixmap()
    assert not pm.isNull()
    assert pm.width() <= 200 and pm.height() <= 150
    assert w.is_showing_video() is False


def test_show_image_stops_any_playing_video(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w._player.stop.assert_called()


def test_show_video_sets_source_and_plays(make_preview, tmp_path):
    w = make_preview()
    vid = tmp_path / "clip.mp4"
    w.show_video(vid)
    assert w.is_showing_video() is True
    w._player.setSource.assert_called_once_with(QUrl.fromLocalFile(str(vid)))
    w._player.play.assert_called_once()


def test_clear_resets_to_placeholder(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.clear()
    assert w.is_showing_video() is False
    assert w._image_label.pixmap().isNull()
    w._player.stop.assert_called()


def test_clear_releases_the_video_file(make_preview, tmp_path):
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4")
    w.clear()
    # Dropping the source unlocks the file, so a previewed clip can be deleted
    # (a held media handle blocks the move-to-trash on Windows).
    w._player.setSource.assert_called_with(QUrl())


def test_video_preview_is_muted(make_preview):
    w = make_preview()
    assert w._audio.isMuted() is True


def test_show_media_routes_to_video(make_preview, tmp_path):
    w = make_preview()
    w.show_media(tmp_path / "c.mp4", "video")
    assert w.is_showing_video() is True
    w._player.play.assert_called_once()


def test_show_media_routes_to_image(make_preview, tmp_path):
    w = make_preview()
    w.show_media(_make_png(tmp_path / "p.png"), "image")
    assert w.is_showing_video() is False
    w._player.play.assert_not_called()


def test_show_image_animates_animated_file(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_animated_gif(tmp_path / "loop.gif"))
    assert w._image_label.movie() is not None
    assert w.is_showing_video() is False  # animated images use the image page


def test_show_static_image_uses_no_movie(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w._image_label.movie() is None
    assert not w._image_label.pixmap().isNull()


def test_switching_from_animation_to_static_stops_movie(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_animated_gif(tmp_path / "loop.gif"))
    movie = w._image_label.movie()
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w._image_label.movie() is None
    assert movie.state().name == "NotRunning"


def test_clear_stops_animation(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_animated_gif(tmp_path / "loop.gif"))
    w.clear()
    assert w._image_label.movie() is None


def test_show_frame_displays_image_from_bytes(make_preview):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_frame(_png_bytes())
    assert not w._image_label.pixmap().isNull()
    assert w.is_showing_video() is False


def test_show_frame_stops_any_playing_video(make_preview, tmp_path):
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4")
    w.show_frame(_png_bytes())
    assert w.is_showing_video() is False
    w._player.stop.assert_called()


def test_show_frame_ignores_undecodable_bytes(make_preview):
    w = make_preview()
    w.show_frame(b"not an image")
    assert w._image_label.pixmap().isNull()


# --- slideshow support: play a video once and report when it ends -----------

def test_video_loops_by_default(make_preview):
    w = make_preview()
    w._player.setLoops.assert_called_with(QMediaPlayer.Loops.Infinite)


def test_slideshow_mode_plays_a_video_once(qtbot):
    w = PreviewWidget(player=MagicMock(), loop_videos=False)
    qtbot.addWidget(w)
    w._player.setLoops.assert_called_with(QMediaPlayer.Loops.Once)


def test_reaching_end_of_media_emits_video_ended(make_preview):
    w = make_preview()
    ended = []
    w.video_ended.connect(lambda: ended.append(True))
    w._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    assert ended == [True]


def test_other_media_status_does_not_emit_video_ended(make_preview):
    w = make_preview()
    ended = []
    w.video_ended.connect(lambda: ended.append(True))
    w._on_media_status(QMediaPlayer.MediaStatus.LoadedMedia)
    assert ended == []


# --- double-click to open the current media fullscreen ----------------------

def test_double_click_opens_fullscreen_for_shown_media(make_preview, tmp_path, monkeypatch):
    opened = {}

    class Fake(QWidget):
        def __init__(self, media, **kwargs):
            super().__init__()
            opened["media"] = media

        def showFullScreen(self):
            opened["shown"] = True

    monkeypatch.setattr(fullscreen_preview, "FullscreenPreview", Fake)
    w = make_preview()
    png = _make_png(tmp_path / "p.png")
    w.show_image(png)
    win = w.mouseDoubleClickEvent(None) or w._fullscreen
    assert opened["media"] == (png, "image")
    assert opened.get("shown") is True
    assert w._fullscreen is win


def test_open_fullscreen_is_a_no_op_without_media(make_preview):
    w = make_preview()  # just the placeholder
    assert w.open_fullscreen() is None


def test_open_fullscreen_ignores_a_live_frame(make_preview):
    # A generating preview shows streamed frames with no file behind them yet.
    w = make_preview()
    w.show_frame(_png_bytes())
    assert w.open_fullscreen() is None


def test_a_preview_that_opted_out_never_opens_fullscreen(qtbot, tmp_path):
    # The slideshow / the fullscreen view itself pass allow_fullscreen=False.
    w = PreviewWidget(player=MagicMock(), allow_fullscreen=False)
    qtbot.addWidget(w)
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w.open_fullscreen() is None


def test_double_click_runs_the_callback_when_it_cannot_open_fullscreen(qtbot):
    # The fullscreen view's inner preview opts out of opening another, so a
    # double-click there runs the callback (which closes the view) instead.
    called = []
    w = PreviewWidget(player=MagicMock(), allow_fullscreen=False,
                      on_double_click=lambda: called.append(True))
    qtbot.addWidget(w)
    w.mouseDoubleClickEvent(None)
    assert called == [True]
