from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import QUrl, QSize, QPointF, QEvent
from PyQt6.QtGui import QResizeEvent, QMouseEvent, QImage
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtMultimedia import QMediaPlayer, QVideoFrame

import origenerator.gui.preview_widget as preview_widget
from origenerator.funscript import funscript_path_for, synthesize_actions, write_funscript
from origenerator.gui.drag_thumbnail import THUMBNAIL_BOX
from origenerator.gui.generation_drag import GENERATION_MIME
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.ken_burns import TICK_MS, ZOOM_SPAN, progress_step, zoom_at

from PyQt6.QtCore import Qt


def _scripted_video(tmp_path, name="clip.mp4"):
    """A temp video path with a real funscript sidecar written beside it."""
    vid = tmp_path / name
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    return vid


def _make_png(path):
    Image.new("RGB", (32, 24), (10, 120, 200)).save(path, "PNG")
    return path


def _make_tall_png(path):
    """A tall image whose aspect ratio doesn't match a wide pane, so a correct
    fit touches the short edges and leaves the long ones letterboxed."""
    Image.new("RGB", (24, 60), (10, 120, 200)).save(path, "PNG")
    return path


def _animated_webp(path):
    """A tiny two-frame looping WebP — an animated image, played by QMovie."""
    frames = [Image.new("RGB", (32, 24), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
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


def test_player_accessor_exposes_the_media_player(make_preview):
    w = make_preview()
    assert w.player() is w._player


def test_current_video_path_is_the_shown_video_else_none(make_preview, tmp_path):
    w = make_preview()
    assert w.current_video_path() is None  # placeholder
    vid = tmp_path / "clip.mp4"
    w.show_video(vid)
    assert w.current_video_path() == vid
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w.current_video_path() is None  # an image isn't a video


def test_show_image_displays_scaled_pixmap(make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_make_png(tmp_path / "p.png"))
    pm = w._image_label.pixmap()
    assert not pm.isNull()
    assert pm.width() <= 200 and pm.height() <= 150
    assert w.is_showing_video() is False


def test_show_image_fits_the_pane_without_clipping(qtbot, tmp_path):
    # A tall image in a wide pane is scaled as large as it fits with no part clipped:
    # it touches one edge pair and stays within the other — letterboxed, never cropped.
    w = PreviewWidget(player=MagicMock())
    qtbot.addWidget(w)
    w._image_label.resize(400, 300)
    w.show_image(_make_tall_png(tmp_path / "tall.png"))
    pm = w._image_label.pixmap()
    assert pm.width() <= 400 and pm.height() <= 300           # nothing clipped off
    assert pm.width() == 400 or pm.height() == 300            # as large as it fits


def test_image_refits_when_the_pane_grows(qtbot, tmp_path):
    # Regression: the image was scaled once at the label's tiny pre-fullscreen size
    # and never again, so on the full screen it sat small with black on all four
    # sides. A later resize of the label must refit it to the new size.
    w = PreviewWidget(player=MagicMock())
    qtbot.addWidget(w)
    w._image_label.resize(80, 240)
    w.show_image(_make_tall_png(tmp_path / "tall.png"))
    old = w._image_label.size()
    w._image_label.resize(600, 500)                           # pane grows to fullscreen
    QApplication.sendEvent(w._image_label, QResizeEvent(QSize(600, 500), old))
    pm = w._image_label.pixmap()
    assert pm.width() <= 600 and pm.height() <= 500           # still nothing clipped
    assert pm.width() == 600 or pm.height() == 500            # refit as large as it fits


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


# --- letting go of files a delete is about to move --------------------------

def test_release_media_drops_the_file_it_is_showing(make_preview, tmp_path):
    w = make_preview()
    clip = tmp_path / "clip.mp4"
    w.show_video(clip)

    w.release_media([clip])

    assert not w.is_showing_any([clip])
    w._player.setSource.assert_called_with(QUrl())  # the handle is let go


def test_release_media_leaves_a_pane_showing_something_else_alone(make_preview, tmp_path):
    # Only what's about to be deleted is dropped: a pane on another item keeps it.
    w = make_preview()
    kept = tmp_path / "kept.mp4"
    w.show_video(kept)

    w.release_media([tmp_path / "doomed.mp4"])

    assert w.is_showing_any([kept])


def test_release_media_matches_the_same_file_spelled_differently(make_preview, tmp_path):
    w = make_preview()
    clip = tmp_path / "clip.mp4"
    w.show_video(clip)

    w.release_media([tmp_path / "sub" / ".." / "clip.mp4"])  # same file, other spelling

    assert not w.is_showing_any([clip])


def test_release_media_reaches_a_fullscreen_view_of_the_file(make_preview, tmp_path):
    # A fullscreen show built over this pane holds the file open too.
    w = make_preview()
    clip = tmp_path / "clip.mp4"
    w.show_video(clip)
    w._fullscreen = MagicMock()

    w.release_media([clip])

    w._fullscreen.release_media.assert_called_once_with([clip])


def test_video_preview_is_muted(make_preview):
    w = make_preview()
    assert w._audio.isMuted() is True


def test_audio_plays_when_not_muted(qtbot):
    # The fullscreen view opts in to sound; the inline preview stays muted (above).
    w = PreviewWidget(player=MagicMock(), mute_audio=False)
    qtbot.addWidget(w)
    assert w._audio.isMuted() is False


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


def test_an_animated_preview_is_fitted_into_the_pane_without_being_stretched(
        make_preview, tmp_path):
    # The hazard this scaling exists for, and the one it was never asked about: a
    # 4:3 loop stretched to fill a square pane is a different picture from the one
    # that was made, and the shape is what a viewer notices first.
    w = make_preview()
    w._image_label.resize(200, 200)

    w.show_image(_make_animated_gif(tmp_path / "loop.gif"))  # 16 x 12 native

    assert w._image_label.movie().scaledSize() == QSize(200, 150)


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

def _arm(preview, cls=None):
    """Wire what a double-click here opens, as the gallery does — the pane itself
    has no idea what folder its generation sits in, so the window is built for it.
    Returns a list the built windows land in."""
    built = []

    def make(media, frame):
        win = (cls or _FakeFullscreen)(media, frame=frame)
        built.append(win)
        win.showFullScreen()
        return win

    preview.set_fullscreen_factory(make)
    return built


def test_double_click_opens_fullscreen_for_shown_media(make_preview, tmp_path):
    w = make_preview()
    built = _arm(w)
    png = _make_png(tmp_path / "p.png")
    w.show_image(png)

    w.mouseDoubleClickEvent(None)

    assert built[0].media == (png, "image")
    assert built[0].isVisible()
    assert w._fullscreen is built[0]  # kept alive here, and fed from here


def test_a_pane_with_nothing_wired_opens_nothing(make_preview, tmp_path):
    # Without the gallery behind it there is no folder to make a show of.
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w.open_fullscreen() is None


def test_open_fullscreen_is_a_no_op_without_media(make_preview):
    w = make_preview()  # just the placeholder
    _arm(w)
    assert w.open_fullscreen() is None


def test_a_plain_message_opens_nothing(make_preview):
    w = make_preview()
    _arm(w)
    w.show_message("Nothing to show")  # not a running generation: nothing to watch
    assert w.open_fullscreen() is None


def test_a_preview_that_opted_out_never_opens_fullscreen(qtbot, tmp_path):
    # A slideshow's own inner preview passes allow_fullscreen=False.
    w = PreviewWidget(player=MagicMock(), allow_fullscreen=False)
    qtbot.addWidget(w)
    _arm(w)
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w.open_fullscreen() is None


def test_double_click_runs_the_callback_when_it_cannot_open_fullscreen(qtbot):
    # A slideshow's inner preview opts out of opening another, so a double-click
    # there runs the callback (which closes the show) instead.
    called = []
    w = PreviewWidget(player=MagicMock(), allow_fullscreen=False,
                      on_double_click=lambda: called.append(True))
    qtbot.addWidget(w)
    w.mouseDoubleClickEvent(None)
    assert called == [True]


# --- watching a generation fullscreen while it's still being made -----------

class _FakeFullscreen(QWidget):
    """Stands in for the slideshow a double-click opens, so a test can see what
    the pane feeds a show opened over a running generation, without a real media
    backend."""

    def __init__(self, media, *, frame=None, **kwargs):
        super().__init__()
        self.media = media
        self.frames = [frame] if frame is not None else []
        self.landed = None
        self._live = media is None

    def is_live(self):
        return self._live

    def show_frame(self, data):
        self.frames.append(data)

    def show_landed(self, media):
        self.landed = media
        self._live = False

    def showFullScreen(self):
        self.show()


@pytest.fixture
def live_preview(make_preview):
    """A preview mirroring a running generation, with the show it opens faked out."""
    preview = make_preview()
    _arm(preview)
    return preview


def test_a_live_frame_opens_fullscreen_over_the_generation(live_preview):
    # The reported gap: double-clicking a generating preview did nothing, so a run
    # could only be watched full-screen once it had finished.
    live_preview.show_frame(_png_bytes())

    win = live_preview.open_fullscreen()

    assert win is not None
    assert win.media is None          # no file behind it yet — it follows the run
    assert win.frames == [_png_bytes()]  # seeded with the frame that was on screen


def test_fullscreen_opens_over_the_wait_before_the_first_frame(live_preview):
    live_preview.show_message("Waiting for preview…", live=True)
    win = live_preview.open_fullscreen()
    assert win is not None and win.frames == []  # nothing to seed it with yet


def test_the_generation_streams_on_into_the_open_view(live_preview):
    # Opened over the wait, it fills in as the run's frames arrive.
    live_preview.show_message("Waiting for preview…", live=True)
    win = live_preview.open_fullscreen()

    live_preview.show_frame(_png_bytes())

    assert win.frames == [_png_bytes()]


def test_blanking_between_rebuilds_keeps_the_view_on_the_generation(live_preview):
    # Every gallery rebuild clears the pane to its placeholder while a run streams;
    # that must not take the fullscreen view off the generation it's watching.
    live_preview.show_frame(_png_bytes())
    win = live_preview.open_fullscreen()

    live_preview.clear()             # the rebuild's blank
    live_preview.show_frame(_png_bytes())  # the frames resume

    assert win.frames == [_png_bytes(), _png_bytes()]
    assert win.landed is None        # and it was never told the run had landed


def test_a_blank_before_the_result_still_lands_the_view(live_preview, tmp_path):
    # The finish path blanks the pane (that same rebuild) a beat before the saved
    # file reaches it, so the hand-off can't key off the pane still looking live.
    live_preview.show_frame(_png_bytes())
    win = live_preview.open_fullscreen()

    live_preview.clear()
    png = _make_png(tmp_path / "done.png")
    live_preview.show_image(png)

    assert win.landed == (png, "image")


def test_the_finished_file_takes_over_from_the_frames(live_preview, tmp_path):
    live_preview.show_frame(_png_bytes())
    win = live_preview.open_fullscreen()

    png = _make_png(tmp_path / "done.png")
    live_preview.show_image(png)  # the run landed: the pane swaps to the saved file

    assert win.landed == (png, "image")


def test_a_dismissed_view_stops_being_fed(live_preview, tmp_path):
    live_preview.show_frame(_png_bytes())
    win = live_preview.open_fullscreen()
    win.close()

    live_preview.show_frame(_png_bytes())
    live_preview.show_image(_make_png(tmp_path / "done.png"))

    assert win.frames == [_png_bytes()]  # only the frame it was opened with
    assert win.landed is None


def test_a_landed_view_is_not_hijacked_by_the_next_run(live_preview, tmp_path):
    live_preview.show_frame(_png_bytes())
    win = live_preview.open_fullscreen()
    live_preview.show_image(_make_png(tmp_path / "done.png"))  # this run landed

    live_preview.show_frame(_png_bytes())  # a later run starts streaming

    assert win.frames == [_png_bytes()]  # the view still shows what it landed on


# --- funscript strip: proof a shown video carries a stroke script -----------

def _strip_preview(qtbot):
    w = PreviewWidget(player=MagicMock(), show_funscript_strip=True)
    qtbot.addWidget(w)
    return w


def test_no_strip_unless_opted_in(make_preview, tmp_path):
    w = make_preview()  # the default (slideshow/plain) preview has no strip
    assert w._strip is None
    w.show_video(_scripted_video(tmp_path))  # still works without one


def test_scripted_video_shows_its_heatmap_strip(qtbot, tmp_path):
    w = _strip_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    assert w._strip._actions
    assert not w._strip.isHidden()


def test_video_without_a_funscript_hides_the_strip(qtbot, tmp_path):
    w = _strip_preview(qtbot)
    w.show_video(tmp_path / "unscripted.mp4")  # no sidecar written
    assert not w._strip._actions
    assert w._strip.isHidden()


def test_showing_an_image_hides_the_strip(qtbot, tmp_path):
    w = _strip_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w._strip.isHidden()


def test_clearing_hides_the_strip(qtbot, tmp_path):
    w = _strip_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    w.clear()
    assert w._strip.isHidden()


# --- dragging the shown generation out to a combine slot --------------------

@pytest.fixture
def drags(monkeypatch):
    """The drags the preview begins, in the order it began them.

    Stands in for QDrag, whose exec is modal and blocks on a real drag loop. The
    list is this test's own: the stand-in used to keep its latest instance on the
    class, where four of these tests read whatever the one before them had left
    behind — and the video drag passed that way with its own feature broken.
    """
    started = []

    class _Drag:
        def __init__(self, _source):
            self.mime = None
            self.pixmap = None
            started.append(self)

        def setMimeData(self, mime):
            self.mime = mime

        def setPixmap(self, pixmap):
            self.pixmap = pixmap

        def exec(self, *args, **kwargs):
            return None

    monkeypatch.setattr(preview_widget, "QDrag", _Drag)
    return started


def _press(w, x=0, y=0):
    w.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _move(w, x, y, button=Qt.MouseButton.LeftButton):
    w.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, button, Qt.KeyboardModifier.NoModifier,
    ))


def _drag_out(w):
    """Press then move far enough past the start-drag threshold to begin a drag."""
    _press(w, 0, 0)
    _move(w, 200, 200)


def test_showing_media_alone_does_not_arm_a_drag(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w._draggable_id is None  # the owner must arm it with the shown generation


def test_set_draggable_id_arms_the_drag(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_draggable_id("gen1")
    assert w._draggable_id == "gen1"


@pytest.mark.parametrize("transient", [
    lambda w: w.show_frame(_png_bytes()),      # a live in-progress frame
    lambda w: w.show_message("Waiting…"),      # a transient note
    lambda w: w.clear(),                        # back to the placeholder
    lambda w: w.show_combination(None, None),   # a pair with nothing made from it yet
])
def test_a_transient_view_disarms_the_drag(make_preview, transient):
    w = make_preview()
    w.set_draggable_id("gen1")
    transient(w)
    assert w._draggable_id is None  # nothing saved to drag out of a transient view


def test_dragging_the_armed_preview_carries_its_generation(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_draggable_id("gen1")
    started, ended = [], []
    w.drag_started.connect(started.append)
    w.drag_ended.connect(lambda: ended.append(True))

    _drag_out(w)

    assert started == ["gen1"]      # announced so a combine slot lights at drag start
    assert ended == [True]          # and cleared when the gesture ends
    (drag,) = drags
    assert bytes(drag.mime.data(GENERATION_MIME)).decode() == "gen1"


def test_a_dragged_still_trails_a_thumbnail_not_the_whole_pane(
        qtbot, make_preview, tmp_path, drags):
    # The pane fits its picture to its own size, which is far bigger than a drop
    # slot; under the cursor it travels as a thumbnail like every other drag.
    w = make_preview()
    w.show()
    w.resize(600, 480)
    qtbot.waitUntil(lambda: w._image_label.width() > THUMBNAIL_BOX)
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_draggable_id("gen1")

    shown = w._image_label.pixmap()
    assert max(shown.width(), shown.height()) > THUMBNAIL_BOX  # the pane fits it big

    _drag_out(w)

    (drag,) = drags
    assert max(drag.pixmap.width(), drag.pixmap.height()) == THUMBNAIL_BOX


def test_a_dragged_animation_trails_the_frame_it_is_on(make_preview, tmp_path, drags):
    # An animated WebP plays through a QMovie, so the label holds no pixmap.
    w = make_preview()
    w.show_image(_animated_webp(tmp_path / "a.webp"))
    w.set_draggable_id("gen1")

    _drag_out(w)

    (drag,) = drags
    assert w._image_label.pixmap().isNull()  # nothing there to reach for
    assert not drag.pixmap.isNull()  # the movie's frame all the same


def test_a_dragged_video_trails_the_frame_on_screen(make_preview, tmp_path, drags):
    # A video's picture is on the player's surface, in no label at all — the last
    # frame handed to the sink is the only hold on it, and without it a dragged
    # video was the one drag in the app that showed nothing.
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4")
    w.set_draggable_id("gen1")
    frame = QImage(160, 120, QImage.Format.Format_RGB32)
    frame.fill(0x2288FF)
    w._video.videoSink().setVideoFrame(QVideoFrame(frame))

    _drag_out(w)

    (drag,) = drags
    assert drag.pixmap is not None and not drag.pixmap.isNull()
    assert max(drag.pixmap.width(), drag.pixmap.height()) == THUMBNAIL_BOX


def test_a_video_with_no_frame_yet_drags_bare(make_preview, tmp_path, drags):
    # Dragged before the first frame arrives there is genuinely nothing to show,
    # and that must not stop the drag.
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4")
    w.set_draggable_id("gen1")
    started = []
    w.drag_started.connect(started.append)

    _drag_out(w)

    (drag,) = drags
    assert started == ["gen1"]
    assert drag.pixmap is None


def test_an_unarmed_preview_does_not_drag(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))  # shown, but never armed
    started = []
    w.drag_started.connect(started.append)

    _drag_out(w)

    assert started == []
    assert drags == []  # no QDrag was ever built


def test_a_small_move_is_a_click_not_a_drag(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_draggable_id("gen1")

    _press(w, 0, 0)
    _move(w, 2, 2)  # within the start-drag distance — a click, not a drag

    assert drags == []


# --- the show's slow push into the still -------------------------------------

def _big_png(path):
    """Big enough that a crop of it still has pixels to spare when scaled up."""
    Image.new("RGB", (400, 300), (10, 120, 200)).save(path, "PNG")
    return path


def _bordered_png(path):
    """Blue inside a fat red border, so the crop shows in a corner pixel: the
    border is the first thing a push into the middle throws away."""
    image = Image.new("RGB", (400, 300), (200, 0, 0))
    image.paste(Image.new("RGB", (320, 220), (0, 0, 200)), (40, 40))
    image.save(path, "PNG")
    return path


def test_the_zoom_draws_the_middle_of_the_picture(make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_bordered_png(tmp_path / "p.png"))
    assert w._image_label.pixmap().toImage().pixelColor(0, 0).red() > 100

    w.set_zoom(1.5)  # far enough in to be past the border on every side

    corner = w._image_label.pixmap().toImage().pixelColor(0, 0)
    assert corner.blue() > 100 and corner.red() < 100


def test_the_push_never_moves_the_drawn_rect_by_so_much_as_a_pixel(make_preview, tmp_path):
    # Exactly, not nearly.  A frame that changes size by one pixel is re-centered
    # by the label, so the picture hops sideways several times a second — which
    # is what a first cut of this did, and it reads as a twitch rather than a
    # camera move.  The overlays placed against this rect care too.
    w = make_preview()
    w.resize(200, 150)
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))
    w.set_zoom(1.0)
    before = w.media_rect()

    for step in range(1, 41):
        w.set_zoom(1.0 + (ZOOM_SPAN - 1) * step / 40)
        assert w.media_rect() == before


def test_the_push_moves_by_a_fraction_of_a_pixel_every_tick(make_preview, tmp_path):
    # Fixed frame, but not a frozen picture: consecutive ticks of a real slide's
    # rate must each redraw something different, or the move is stepping rather
    # than creeping.
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_bordered_png(tmp_path / "p.png"))
    w.set_zoom(1.0)

    frames = []
    for tick in range(1, 4):
        w.set_zoom(zoom_at(tick * progress_step(TICK_MS, 4000)))
        frames.append(w._image_label.pixmap().toImage())

    assert frames[0] != frames[1] and frames[1] != frames[2]


def test_a_new_picture_is_drawn_at_whatever_zoom_it_was_told(make_preview, tmp_path):
    # The show resets the zoom itself when it puts a new slide up; a version of
    # the SAME picture swapped in under it keeps the push it was part-way through.
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))
    w.set_zoom(1.08)

    w.show_image(_big_png(tmp_path / "q.png"))

    assert w._zoom == 1.08


def test_a_pane_nobody_pushes_is_drawn_exactly_as_it_always_was(make_preview, tmp_path):
    # The painter path belongs to the show.  Every other pane — the info pane's
    # preview, the strips — keeps the plain fit, so nothing about them changed.
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))

    assert w._pushing is False
    assert w._push_source is None


def test_the_zoom_never_backs_out_past_the_whole_picture(make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))

    w.set_zoom(0.5)

    assert w._zoom == 1.0

# --- the notice: this picture isn't what the settings beside it would make ---

def test_a_preview_starts_with_no_notice(make_preview):
    w = make_preview()
    assert w._notice.isHidden()
    assert w._notice_dim.isHidden()


def test_a_notice_dims_the_media_and_says_its_piece(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))

    w.set_notice("(not yet generated with modifications)")

    assert not w._notice.isHidden()
    assert w._notice.text() == "(not yet generated with modifications)"
    assert not w._notice_dim.isHidden()  # the picture behind it is dimmed


def test_the_dim_covers_the_media_and_the_plate_sits_top_left(make_preview, tmp_path):
    w = make_preview()
    w._media_host.resize(300, 200)
    w.show_image(_make_png(tmp_path / "p.png"))

    w.set_notice("modified")

    assert w._notice_dim.geometry() == w._media_host.rect()   # the whole picture
    # ...and the message in its top-left corner, clear of both edges.
    assert 0 < w._notice.x() < w._media_host.width() // 2
    assert 0 < w._notice.y() < w._media_host.height() // 2
    assert w._notice.width() <= w._media_host.width()


def test_clearing_the_notice_takes_the_dim_with_it(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_notice("modified")

    w.set_notice(None)

    assert w._notice.isHidden()
    assert w._notice_dim.isHidden()


@pytest.mark.parametrize("show", [
    lambda w, tmp: w.show_image(_make_png(tmp / "q.png")),
    lambda w, tmp: w.show_video(tmp / "clip.mp4"),
    lambda w, tmp: w.show_frame(_png_bytes()),
    lambda w, tmp: w.show_message("Waiting for preview…"),
    lambda w, tmp: w.clear(),
    lambda w, tmp: w.show_combination(_make_png(tmp / "c.png"), None),
])
def test_a_new_view_drops_the_notice_about_the_last_one(make_preview, tmp_path, show):
    # A notice is about the picture it was set over, so it can never outlive it —
    # least of all over the live frames of the run that answers it.
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_notice("modified")

    show(w, tmp_path)

    assert w._notice.isHidden()
    assert w._notice_dim.isHidden()


def test_frames_of_the_picture_itself_leave_the_notice_up(make_preview, tmp_path):
    # An enhancement streams the coming state of what is already on display —
    # not a run of the settings beside it — so a notice about that picture is
    # just as true of the version arriving, and the two belong on screen
    # together. Cleared by each frame and re-asserted by each keystroke, it
    # blinked at the rate the run streamed while the form was typed in.
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_notice("modified")

    w.show_frame(_png_bytes(), keep_notice=True)

    assert not w._notice.isHidden()
    assert w._notice.text() == "modified"
    assert not w._notice_dim.isHidden()  # dimmed over the frames as well


def test_a_kept_notice_rides_over_the_frame_that_lands_under_it(make_preview, tmp_path):
    # Switching the stacked layout to the picture raises that widget above every
    # sibling it has, the notice included — so a kept one is lifted back.
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4")  # the stack is on the video surface
    w.set_notice("modified")

    w.show_frame(_png_bytes(), keep_notice=True)

    order = w._media_host.children()
    assert order.index(w._notice) > order.index(w._image_label)
    assert order.index(w._notice_dim) > order.index(w._image_label)


def test_resizing_re_places_the_notice(make_preview, tmp_path):
    w = make_preview()
    w._media_host.resize(300, 200)
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_notice("modified")
    old = w._image_label.size()

    w._media_host.resize(500, 400)
    w._image_label.resize(500, 400)
    # The label's resize is what the pane's refit rides on (see eventFilter).
    QApplication.sendEvent(w._image_label, QResizeEvent(QSize(500, 400), old))

    assert w._notice_dim.geometry() == w._media_host.rect()



# --- a combination, before anything has been made from it --------------------

def test_a_combination_shows_the_pair_instead_of_the_placeholder(make_preview, tmp_path):
    # "Edit…" hands a tab a picture and a past video's settings. The
    # idle line ("select a generation to preview") describes a tab pointed at
    # nothing, which is exactly what this is not.
    w = make_preview()
    frame = _make_png(tmp_path / "frame.png")
    clip = _animated_webp(tmp_path / "recipe.webp")

    w.show_combination(frame, clip)

    assert w._stack.currentWidget() is w._combination
    assert not w._combination.image_label.pixmap().isNull()
    assert not w._combination.plus_label.isHidden()


def test_the_recipe_half_of_a_combination_loops_in_gray(make_preview, tmp_path):
    w = make_preview()
    w.show(); w.resize(400, 200)

    w.show_combination(_make_png(tmp_path / "frame.png"),
                       _animated_webp(tmp_path / "recipe.webp"))

    color = w._combination.video_label.pixmap().toImage().pixelColor(1, 1)
    assert color.red() == color.green() == color.blue()  # the recipe, not a result


def test_a_combination_with_no_recipe_video_shows_the_frame_alone(make_preview, tmp_path):
    # A curated act is pinned in the content overlay: there is no past video
    # behind it, so there is no sum to draw a plus in the middle of.
    w = make_preview()

    w.show_combination(_make_png(tmp_path / "frame.png"), None)

    assert w._stack.currentWidget() is w._combination
    assert w._combination.plus_label.isHidden()
    assert w._combination.video_label.isHidden()


def test_showing_anything_else_puts_the_combination_down(make_preview, tmp_path):
    # Its clip would otherwise keep looping behind whatever replaced it.
    w = make_preview()
    w.show_combination(_make_png(tmp_path / "frame.png"),
                       _animated_webp(tmp_path / "recipe.webp"))

    w.show_image(_make_png(tmp_path / "later.png"))

    assert w._stack.currentWidget() is w._image_label
    assert w._combination._movie is None
# --- the corner controls over the picture ------------------------------------

def _corners(w):
    """The preview's star, trash can and plus, in that order."""
    return w._controls.buttons()


def test_an_armed_preview_wears_the_same_corners_a_thumbnail_does(make_preview,
                                                                  tmp_path):
    from origenerator.gui import icons

    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))

    w.set_actions("p1", starred=True, enhance=icons.ENHANCE_HELD)

    assert all(not b.isHidden() for b in _corners(w))


def test_a_new_picture_takes_the_last_one_s_corners_away(make_preview, tmp_path):
    # The corners are about the generation on screen, so they can no more outlive
    # it than the "no longer these settings" notice can.
    w = make_preview()
    w.set_actions("p1", starred=True, enhance=None)

    w.show_image(_make_png(tmp_path / "other.png"))

    assert w._actions_id is None
    assert all(b.isHidden() for b in _corners(w))


def test_a_running_generation_has_no_corners_to_press(make_preview):
    # Live frames are a part-drawn file that does not exist yet: nothing to
    # bookmark, bin or enhance.
    w = make_preview()
    w.set_actions("p1", starred=False, enhance=None)

    w.show_frame(_png_bytes())

    assert w._actions_id is None
    assert all(b.isHidden() for b in _corners(w))


def test_a_corner_of_the_preview_names_the_generation_it_is_about(make_preview,
                                                                  tmp_path):
    from origenerator.gui import corner_controls

    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_actions("p1", starred=False, enhance=None)
    fired = []
    w.action_triggered.connect(lambda pid, action: fired.append((pid, action)))

    _corners(w)[0].click()

    assert fired == [("p1", corner_controls.STAR)]


def test_right_clicking_the_picture_asks_for_its_menu(make_preview, tmp_path):
    from PyQt6.QtCore import QPoint

    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_actions("p1", starred=False, enhance=None)
    asked = []
    w.context_requested.connect(lambda pid, pos: asked.append(pid))

    w.customContextMenuRequested.emit(QPoint(5, 5))

    assert asked == ["p1"]


def test_right_clicking_an_unarmed_preview_asks_for_nothing(make_preview):
    from PyQt6.QtCore import QPoint

    # The placeholder, or a slideshow's own inner preview: there is no row here.
    w = make_preview()
    asked = []
    w.context_requested.connect(lambda pid, pos: asked.append(pid))

    w.customContextMenuRequested.emit(QPoint(5, 5))

    assert asked == []


def test_the_corners_follow_the_picture_rather_than_the_pane(make_preview, tmp_path):
    # A portrait image in a wide pane is letterboxed, so corners pinned to the
    # pane would float in the black surround instead of on the picture.
    w = make_preview()
    w.resize(400, 300)
    w._image_label.resize(400, 300)
    w.show_image(_make_tall_png(tmp_path / "tall.png"))
    w.set_actions("p1", starred=True, enhance=None)

    picture = w.media_rect()
    assert picture.width() < w.width()          # it really is letterboxed
    assert picture.contains(_corners(w)[0].geometry())


# --- putting the pane down before laying new content in it -------------------
#
# Every show_* opens by clearing what the pane was holding: the playback, the
# notice, the corner controls, the media, the live follow and the drag. The set
# is the same six things each time, so these pin it as one list — including the
# two deliberate exceptions (a saved file leaves the drag for its owner to arm,
# a kept notice rides over the frames of the picture it is about) and the one
# that is a defect, held below.


def _pane_holding_everything(w, tmp_path):
    """A pane holding a saved generation with every resettable thing set: an
    animated picture, a notice over it, armed corners and an armed drag."""
    w.show_image(_animated_webp(tmp_path / "held.webp"))
    w.set_notice("no longer what these settings would make")
    w.set_actions("held", starred=True, enhance=None)
    w.set_draggable_id("held")
    w._player.reset_mock()
    return w


def test_showing_an_image_puts_down_all_the_pane_was_holding(make_preview, tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    path = _make_png(tmp_path / "next.png")
    w.show_image(path)

    assert w._player.stop.called            # whatever was playing
    assert w._notice.isHidden()             # the notice about the last picture
    assert w._actions_id is None            # and its corners
    assert w._media == (path, "image")
    assert (w._live, w._live_frame) == (False, None)
    assert w._movie is None                 # the animation it replaced
    assert w._draggable_id == "held"        # a saved file: the owner re-arms it


def test_showing_a_video_puts_down_all_the_pane_was_holding(make_preview, tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    path = tmp_path / "clip.mp4"
    w.show_video(path)

    assert not w._player.stop.called        # setSource takes over from the old clip
    assert w._notice.isHidden()
    assert w._actions_id is None
    assert w._media == (path, "video")
    assert (w._live, w._live_frame) == (False, None)
    assert w._movie is None
    assert w._draggable_id == "held"        # a saved file: the owner re-arms it


def test_showing_a_live_frame_puts_down_all_the_pane_was_holding(make_preview,
                                                                 tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    data = _png_bytes()
    w.show_frame(data)

    assert w._player.stop.called
    assert w._notice.isHidden()
    assert w._actions_id is None
    assert w._media is None                 # a frame is no file to open fullscreen
    assert (w._live, w._live_frame) == (True, data)
    assert w._movie is None
    assert w._draggable_id is None          # nor a saved generation to drag out


def test_showing_a_combination_puts_down_all_the_pane_was_holding(make_preview,
                                                                  tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_combination(_make_png(tmp_path / "frame.png"), None)

    assert w._player.stop.called
    assert w._notice.isHidden()
    assert w._actions_id is None
    assert w._media is None
    assert (w._live, w._live_frame) == (False, None)
    assert w._movie is None
    assert w._draggable_id is None


def test_showing_a_message_puts_down_all_the_pane_was_holding(make_preview,
                                                              tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_message("Waiting for preview…")

    assert w._player.stop.called
    assert w._notice.isHidden()
    assert w._actions_id is None
    assert w._media is None
    assert (w._live, w._live_frame) == (False, None)
    assert w._movie is None
    assert w._draggable_id is None


def test_a_message_marked_live_leaves_the_pane_following_the_run(make_preview,
                                                                 tmp_path):
    # The wait before a re-roll's first frame: the pane says it is generating and
    # a double-click still opens fullscreen over it.
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_message("Generating…", live=True)

    assert (w._live, w._live_frame) == (True, None)


def test_frames_of_the_picture_itself_keep_the_notice_they_are_about(make_preview,
                                                                     tmp_path):
    # An enhancement of the picture on screen: whatever the notice says about that
    # picture is just as true of the version being made, so it stays up.
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_frame(_png_bytes(), keep_notice=True)

    assert not w._notice.isHidden()


def test_showing_a_folder_puts_down_all_the_pane_was_holding(make_preview,
                                                             tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_folder([_make_png(tmp_path / "wall.png")])

    assert w._player.stop.called
    assert w._notice.isHidden()
    assert w._actions_id is None            # a wall of pictures is not a row
    assert w._media is None
    assert (w._live, w._live_frame) == (False, None)
    assert w._movie is None
    assert w._draggable_id is None


def test_the_corners_over_a_folder_have_no_generation_to_fire_at(make_preview,
                                                                 tmp_path):
    # The defect this closes (audit §3 bug 15, signed off 2026-08-31): the wall
    # kept the corners of whatever generation was there before it, so pressing
    # trash binned a picture the user was no longer looking at.
    w = _pane_holding_everything(make_preview(), tmp_path)
    fired = []
    w.action_triggered.connect(lambda pid, action: fired.append((pid, action)))

    w.show_folder([_make_png(tmp_path / "wall.png")])
    w._on_control("trash")

    assert fired == []
    assert all(b.isHidden() for b in _corners(w))
