from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import QUrl, QSize, QPointF, QEvent
from PyQt6.QtGui import QResizeEvent, QMouseEvent
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtMultimedia import QMediaPlayer

import origenerator.gui.preview_widget as preview_widget
from origenerator.funscript import funscript_path_for, synthesize_actions, write_funscript
from origenerator.gui.generation_drag import GENERATION_MIME
from origenerator.gui.preview_widget import PreviewWidget

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
    assert w._strip.has_script() is True
    assert not w._strip.isHidden()


def test_video_without_a_funscript_hides_the_strip(qtbot, tmp_path):
    w = _strip_preview(qtbot)
    w.show_video(tmp_path / "unscripted.mp4")  # no sidecar written
    assert w._strip.has_script() is False
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

class _FakeDrag:
    """Stands in for QDrag so a test can drive the drag path without the modal,
    blocking QDrag.exec (and without a real drag loop)."""

    last = None

    def __init__(self, source):
        self.mime = None
        self.pixmap = None
        _FakeDrag.last = self

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, pixmap):
        self.pixmap = pixmap

    def exec(self, *args, **kwargs):
        return None


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
])
def test_a_transient_view_disarms_the_drag(make_preview, transient):
    w = make_preview()
    w.set_draggable_id("gen1")
    transient(w)
    assert w._draggable_id is None  # nothing saved to drag out of a transient view


def test_dragging_the_armed_preview_carries_its_generation(make_preview, tmp_path, monkeypatch):
    monkeypatch.setattr(preview_widget, "QDrag", _FakeDrag)
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_draggable_id("gen1")
    started, ended = [], []
    w.drag_started.connect(started.append)
    w.drag_ended.connect(lambda: ended.append(True))

    _drag_out(w)

    assert started == ["gen1"]      # announced so a combine slot lights at drag start
    assert ended == [True]          # and cleared when the gesture ends
    assert bytes(_FakeDrag.last.mime.data(GENERATION_MIME)).decode() == "gen1"


def test_an_unarmed_preview_does_not_drag(make_preview, tmp_path, monkeypatch):
    monkeypatch.setattr(preview_widget, "QDrag", _FakeDrag)
    _FakeDrag.last = None
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))  # shown, but never armed
    started = []
    w.drag_started.connect(started.append)

    _drag_out(w)

    assert started == []
    assert _FakeDrag.last is None  # no QDrag was ever built


def test_a_small_move_is_a_click_not_a_drag(make_preview, tmp_path, monkeypatch):
    monkeypatch.setattr(preview_widget, "QDrag", _FakeDrag)
    _FakeDrag.last = None
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_draggable_id("gen1")

    _press(w, 0, 0)
    _move(w, 2, 2)  # within the start-drag distance — a click, not a drag

    assert _FakeDrag.last is None


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


def test_the_zoom_leaves_the_drawn_rect_where_it_was(make_preview, tmp_path):
    # The one thing the crop exists for: the neighbor stills and the HUD map are
    # placed against this rect, so a push that grew the drawn picture would shove
    # them around twenty times a second.
    w = make_preview()
    w.resize(200, 150)
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))
    before = w.media_rect()

    for step in range(1, 11):
        w.set_zoom(1.0 + 0.10 * step / 10)
        rect = w.media_rect()
        # Within a pixel: the crop is rounded to whole source pixels.
        assert abs(rect.width() - before.width()) <= 1
        assert abs(rect.height() - before.height()) <= 1
        assert abs(rect.center().x() - before.center().x()) <= 1
        assert abs(rect.center().y() - before.center().y()) <= 1


def test_a_new_picture_is_drawn_at_whatever_zoom_it_was_told(make_preview, tmp_path):
    # The show resets the zoom itself when it puts a new slide up; a version of
    # the SAME picture swapped in under it keeps the push it was part-way through.
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))
    w.set_zoom(1.08)

    w.show_image(_big_png(tmp_path / "q.png"))

    assert w._zoom == 1.08


def test_the_zoom_never_backs_out_past_the_whole_picture(make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_big_png(tmp_path / "p.png"))

    w.set_zoom(0.5)

    assert w._zoom == 1.0
