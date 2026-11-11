from __future__ import annotations

import gc
from io import BytesIO
from unittest.mock import MagicMock, call

import pytest
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QPointF, QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QResizeEvent
from PyQt6.QtMultimedia import QMediaMetaData, QMediaPlayer, QVideoFrame
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.fun_time_mode import FunestraChannel
from origenerator.funscript import (
    funscript_path_for,
    synthesize_actions,
    write_funscript,
)
from origenerator.gui import corner_buttons, drag_thumbnail, icons, viewport
from origenerator.gui.combination import Combination
from origenerator.gui.drag_thumbnail import THUMBNAIL_MAX
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_slideshow import FunestraSlideshow, Playing, Seat
from origenerator.gui.generation_drag import GENERATION_MIME
from origenerator.gui.viewport import Viewport
from origenerator.output_places import OutputPlaces
from tests.heard_drags import HeardDrags


def _scripted_video(tmp_path, name="clip.mp4"):
    vid = tmp_path / name
    write_funscript(vid.with_suffix(".funscript"),
                    synthesize_actions(2.0, hz=1.0))
    return vid


def _make_png(path):
    Image.new("RGB", (32, 24), (10, 120, 200)).save(path, "PNG")
    return path


def _make_tall_png(path):
    Image.new("RGB", (24, 60), (10, 120, 200)).save(path, "PNG")
    return path


def _animated_webp(path):
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
    # The real Qt Multimedia backend deadlocks at session shutdown once a player has started
    def _make(**kwargs):
        w = Viewport(player=MagicMock(), **kwargs)
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


def test_show_image_displays_scaled_pixmap(make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 150)
    w.show_image(_make_png(tmp_path / "p.png"))
    pm = w._image_label.pixmap()
    assert not pm.isNull()
    assert pm.width() <= 200
    assert pm.height() <= 150
    assert w.is_showing_video() is False


def test_show_image_fits_the_pane_without_clipping(qtbot, tmp_path):
    w = Viewport(player=MagicMock())
    qtbot.addWidget(w)
    w._image_label.resize(400, 300)
    w.show_image(_make_tall_png(tmp_path / "tall.png"))
    pm = w._image_label.pixmap()
    assert pm.width() <= 400
    assert pm.height() <= 300
    assert pm.width() == 400 or pm.height() == 300
    assert (pm.width(), pm.height()) == (120, 300), (
        "a tall image whose aspect ratio does not match a wide pane: a correct fit touches the "
        "short edges and leaves the long ones letterboxed")


def test_image_refits_when_the_pane_grows(qtbot, tmp_path):
    w = Viewport(player=MagicMock())
    qtbot.addWidget(w)
    w._image_label.resize(80, 240)
    w.show_image(_make_tall_png(tmp_path / "tall.png"))
    old = w._image_label.size()
    w._image_label.resize(600, 500)
    QApplication.sendEvent(w._image_label, QResizeEvent(QSize(600, 500), old))
    pm = w._image_label.pixmap()
    assert pm.width() <= 600
    assert pm.height() <= 500
    assert pm.width() == 600 or pm.height() == 500


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


def test_moving_off_a_clip_releases_it_so_its_next_showing_reads_it_afresh(make_preview, tmp_path):
    w = make_preview()
    w.show_video(tmp_path / "broken.mp4")

    w.show_image(_make_png(tmp_path / "next.png"))

    w._player.setSource.assert_called_with(QUrl())


def test_clear_releases_the_video_file(make_preview, tmp_path):
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4")
    w.clear()
    w._player.setSource.assert_called_with(QUrl())


def test_release_media_drops_the_file_it_is_showing(make_preview, tmp_path):
    w = make_preview()
    video = tmp_path / "clip.mp4"
    w.show_video(video)

    w.release_media([video])

    assert not w.is_showing_any([video])
    w._player.setSource.assert_called_with(QUrl())


def test_release_media_leaves_a_pane_showing_something_else_alone(make_preview, tmp_path):
    w = make_preview()
    kept = tmp_path / "kept.mp4"
    w.show_video(kept)

    w.release_media([tmp_path / "doomed.mp4"])

    assert w.is_showing_any([kept])


def test_release_media_matches_the_same_file_spelled_differently(make_preview, tmp_path):
    w = make_preview()
    video = tmp_path / "clip.mp4"
    w.show_video(video)

    w.release_media([tmp_path / "sub" / ".." / "clip.mp4"])

    assert not w.is_showing_any([video])


def test_release_media_reaches_a_fullscreen_view_of_the_file(make_preview, tmp_path):
    w = make_preview()
    video = tmp_path / "clip.mp4"
    w.show_video(video)
    w._fullscreen = MagicMock()

    w.release_media([video])

    w._fullscreen.release_media.assert_called_once_with([video])


def test_a_video_plays_with_no_sound_output_at_all(make_preview, tmp_path):
    w = make_preview()

    w.show_video(tmp_path / "clip.mp4")
    w.release_player()

    assert [c for c in w._player.method_calls if c[0] == "setAudioOutput"] == []




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
    assert w.is_showing_video() is False


def test_an_animated_preview_is_fitted_into_the_pane_without_being_stretched(
        make_preview, tmp_path):
    w = make_preview()
    w._image_label.resize(200, 200)

    w.show_image(_make_animated_gif(tmp_path / "loop.gif"))

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


def test_a_truncated_frame_leaves_what_is_on_screen_as_it_was(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_message("modified")
    shown = w._image_label.pixmap().cacheKey()

    w.show_frame(b"not an image")

    assert w._image_label.pixmap().cacheKey() == shown
    assert w._message.text() == "modified"
    assert not w._message.isHidden(), (
        "a frame is decoded before the pane is put down, so one that does not decode leaves "
        "the screen as it was")


def test_the_video_on_screen_is_named_by_the_run_it_came_from(make_preview, tmp_path):
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4", "alpha-1")
    assert w.video_on_screen() == "alpha-1"


def test_an_image_or_the_frames_of_a_run_still_going_are_no_video_on_screen(
        make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"), "alpha-1")
    assert w.video_on_screen() is None

    w.show_video(tmp_path / "clip.mp4", "alpha-1")
    w.show_frame(_png_bytes())
    assert w.video_on_screen() is None


def test_a_video_loops(make_preview):
    w = make_preview()
    w._player.setLoops.assert_called_with(QMediaPlayer.Loops.Infinite)














def _arm(preview):
    built = []

    def make(media, generation):
        slideshow = _FakeSlideshow(media, generation=generation)
        built.append(slideshow)
        return slideshow

    preview.set_fullscreen_factory(make)
    return built


def test_double_click_opens_fullscreen_on_the_shown_generation(make_preview, tmp_path):
    w = make_preview()
    built = _arm(w)
    png = _make_png(tmp_path / "p.png")
    w.show_image(png, "gen1")

    w.mouseDoubleClickEvent(None)

    assert (built[0].media, built[0].generation) == ((png, "image"), "gen1")
    assert w._fullscreen is built[0]


def test_a_pane_with_nothing_wired_opens_nothing(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w.open_fullscreen() is None


def test_open_fullscreen_is_a_no_op_without_media(make_preview):
    w = make_preview()
    _arm(w)
    assert w.open_fullscreen() is None


def test_a_plain_message_opens_nothing(make_preview):
    w = make_preview()
    _arm(w)
    w.show_message("Nothing to show")
    assert w.open_fullscreen() is None










class _FakeSlideshow:
    def __init__(self, media, *, generation=None):
        self.media = media
        self.generation = generation
        self._showing = True

    def is_showing(self):
        return self._showing

    def close(self):
        self._showing = False


@pytest.fixture
def live_preview(make_preview):
    preview = make_preview()
    _arm(preview)
    return preview


def test_a_live_frame_opens_fullscreen_over_the_generation(live_preview):
    live_preview.show_frame(_png_bytes())

    win = live_preview.open_fullscreen()

    assert win is not None
    assert win.media is None


def test_fullscreen_opens_over_the_wait_before_the_first_frame(live_preview):
    live_preview.show_message("Waiting for preview…", live=True)
    win = live_preview.open_fullscreen()
    assert win is not None
    assert win.media is None


def _slideshow_on_a_sessions_funestra(tmp_path):
    channel = FunestraChannel(
        playlist=tmp_path / "landscape.tsv",
        command_file=tmp_path / "landscape_cmd.txt",
        status_file=tmp_path / "landscape_status.txt",
        hud_file=tmp_path / "origenerator_landscape_hud.json")
    slideshow = FunestraSlideshow(
        Playing([(str(tmp_path / "a.png"), "image", "id-a")]),
        Seat("landscape", channel, FrameFiles(tmp_path / "frames")))
    slideshow._timer.stop()
    return slideshow


def test_a_pane_whose_item_went_to_a_sessions_funestra_goes_on_taking_runs_and_files(
        make_preview, tmp_path):
    slideshow = _slideshow_on_a_sessions_funestra(tmp_path)
    preview = make_preview()
    preview.set_fullscreen_factory(lambda media, generation: slideshow)
    preview.show_image(_make_png(tmp_path / "a.png"))
    assert preview.open_fullscreen() is slideshow
    handed_over = slideshow.channel.command_file.read_text(encoding="utf-8")

    preview.show_frame(_png_bytes())
    preview.show_image(_make_png(tmp_path / "landed.png"))

    assert not preview._image_label.pixmap().isNull()
    assert slideshow.channel.command_file.read_text(encoding="utf-8") == handed_over


def _scrubber_preview(qtbot):
    w = Viewport(player=MagicMock(), show_scrubber=True)
    qtbot.addWidget(w)
    return w


def test_no_timeline_unless_opted_in(make_preview, tmp_path):
    w = make_preview()
    assert w._scrubber is None
    w.show_video(_scripted_video(tmp_path))


def test_a_scripted_video_fills_its_timeline_with_the_motion(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    assert w._scrubber._actions
    assert not w._scrubber.isHidden()


def test_a_script_in_the_scripts_folder_fills_the_timeline(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(viewport, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    vid = tmp_path / "video" / "filed.mp4"
    vid.parent.mkdir()
    write_funscript(funscript_path_for(vid, places=OutputPlaces.in_one_folder(tmp_path)),
                    synthesize_actions(2.0, hz=1.0))

    w = _scrubber_preview(qtbot)
    w.show_video(vid)

    assert w._scrubber._actions
    assert not w._scrubber.isHidden()


def test_the_corners_keep_off_the_timeline_while_a_videos_size_is_unknown(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.resize(320, 480)
    w.show()
    w.show_video(_scripted_video(tmp_path))
    w.set_actions("gen-1")
    w.layout().activate()
    scrubber_top = w._scrubber.geometry().top()
    assert not w._scrubber.isHidden()
    assert scrubber_top > 0
    assert w.media_rect().bottomLeft().y() < scrubber_top
    assert all(b.geometry().bottomLeft().y() < scrubber_top
               for b in w._controls.buttons())


def test_the_cursor_follows_playback_position(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    follow = w._player.positionChanged.connect.call_args.args[0]
    follow(1500)
    assert w._scrubber._position == 1500
    w.show_video(_scripted_video(tmp_path, name="next.mp4"))
    assert w._scrubber._position is None


def test_the_timeline_takes_the_videos_length_from_the_player(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    length = w._player.durationChanged.connect.call_args.args[0]
    length(4000)
    assert w._scrubber._duration == 4000


def test_the_corners_follow_the_item_when_the_timeline_takes_its_room(qtbot, tmp_path):
    player = MagicMock()
    player.metaData.return_value.value.side_effect = (
        lambda key: QSize(480, 864) if key == QMediaMetaData.Key.Resolution else None)
    w = Viewport(player=player, show_scrubber=True)
    qtbot.addWidget(w)
    w.resize(320, 480)
    w.show()
    w.layout().activate()
    w.show_video(_scripted_video(tmp_path))
    w.set_actions("gen-1")
    w.layout().activate()
    scrubber_top = w._scrubber.geometry().top()
    assert not w._scrubber.isHidden()
    assert scrubber_top > 0
    assert w.media_rect().bottomLeft().y() < scrubber_top
    assert all(b.geometry().bottomLeft().y() < scrubber_top
               for b in w._controls.buttons())


def test_the_corners_move_to_the_item_once_a_videos_resolution_arrives(qtbot, tmp_path):
    known = {}
    player = MagicMock()
    player.metaData.return_value.value.side_effect = known.get
    w = Viewport(player=player, show_scrubber=True)
    qtbot.addWidget(w)
    w.resize(480, 320)
    w.show()
    w.layout().activate()
    w.show_video(_scripted_video(tmp_path))
    w.set_actions("gen-1")
    w.layout().activate()
    over_the_whole_pane = [b.geometry() for b in w._controls.buttons()]
    the_resolution_arrived = player.metaDataChanged.connect.call_args.args[0]

    known[QMediaMetaData.Key.Resolution] = QSize(480, 864)
    the_resolution_arrived()

    assert w.media_rect().width() < w.width()
    assert [b.geometry() for b in w._controls.buttons()] != over_the_whole_pane, (
        "until a video's resolution arrives the item can only be taken for the whole pane, so "
        "the corners are placed again when it does")
    assert all(w.media_rect().contains(b.geometry()) for b in w._controls.buttons()
               if not b.isHidden())


def test_a_video_without_a_funscript_still_gets_its_timeline(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.show_video(tmp_path / "unscripted.mp4")
    assert not w._scrubber._actions
    assert not w._scrubber.isHidden()


def test_showing_an_image_takes_the_timeline_away(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    w.show_image(_make_png(tmp_path / "p.png"))
    assert w._scrubber.isHidden()


def test_clearing_takes_the_timeline_away(qtbot, tmp_path):
    w = _scrubber_preview(qtbot)
    w.show_video(_scripted_video(tmp_path))
    w.clear()
    assert w._scrubber.isHidden()


@pytest.fixture
def drags(monkeypatch):
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

    monkeypatch.setattr(drag_thumbnail, "QDrag", _Drag)
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
    _press(w, 0, 0)
    _move(w, 200, 200)


@pytest.mark.parametrize("transient", [
    lambda w: w.show_frame(_png_bytes()),
    lambda w: w.show_message("Waiting…"),
    lambda w: w.clear(),
    lambda w: w.show_combination(Combination()),
])
def test_a_transient_view_disarms_the_drag(make_preview, transient, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"), "gen1")
    transient(w)
    assert w._generation is None


def test_dragging_the_armed_preview_carries_its_generation(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"), "gen1")
    heard = HeardDrags()

    _drag_out(w)

    assert heard.generations() == ["gen1"]
    assert heard.ended == 1
    (drag,) = drags
    assert bytes(drag.mime.data(GENERATION_MIME)).decode() == "gen1"


def test_a_dragged_still_trails_a_thumbnail_not_the_whole_pane(
        qtbot, make_preview, tmp_path, drags):
    w = make_preview()
    w.show()
    w.resize(600, 480)
    qtbot.waitUntil(lambda: w._image_label.width() > THUMBNAIL_MAX)
    w.show_image(_make_png(tmp_path / "p.png"), "gen1")

    shown = w._image_label.pixmap()
    assert max(shown.width(), shown.height()) > THUMBNAIL_MAX

    _drag_out(w)

    (drag,) = drags
    assert max(drag.pixmap.width(), drag.pixmap.height()) == THUMBNAIL_MAX


def test_a_dragged_animation_trails_the_frame_it_is_on(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_animated_webp(tmp_path / "a.webp"), "gen1")

    _drag_out(w)

    (drag,) = drags
    assert w._image_label.pixmap().isNull()
    assert not drag.pixmap.isNull()


def test_a_dragged_video_trails_the_frame_on_screen(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4", "gen1")
    frame = QImage(160, 120, QImage.Format.Format_RGB32)
    frame.fill(0x2288FF)
    w._video.video_sink().setVideoFrame(QVideoFrame(frame))

    _drag_out(w)

    (drag,) = drags
    assert drag.pixmap is not None
    assert not drag.pixmap.isNull()
    assert max(drag.pixmap.width(), drag.pixmap.height()) == THUMBNAIL_MAX


def test_a_video_with_no_frame_yet_drags_bare(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_video(tmp_path / "clip.mp4", "gen1")
    heard = HeardDrags()

    _drag_out(w)

    (drag,) = drags
    assert heard.generations() == ["gen1"]
    assert drag.pixmap is None


def test_an_unarmed_preview_does_not_drag(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    heard = HeardDrags()

    _drag_out(w)

    assert heard.started == []
    assert drags == []


def test_a_small_move_is_a_click_not_a_drag(make_preview, tmp_path, drags):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"), "gen1")

    _press(w, 0, 0)
    _move(w, 2, 2)

    assert drags == []


def _video_frame(color: str) -> QVideoFrame:
    pixels = QImage(64, 36, QImage.Format.Format_RGB32)
    pixels.fill(QColor(color))
    return QVideoFrame(pixels)


def _middle_of_the_media(w) -> QColor:
    shot = w._media_host.grab().toImage()
    return shot.pixelColor(shot.width() // 2, shot.height() // 2)


def _show_a_red_video(w, tmp_path):
    w.show_video(tmp_path / "clip.mp4")
    w._video.video_sink().setVideoFrame(_video_frame("red"))


def _show_a_red_still(w, tmp_path):
    path = tmp_path / "red.png"
    Image.new("RGB", (64, 36), (255, 0, 0)).save(path, "PNG")
    w.show_image(path)


def test_a_playing_video_is_drawn_in_the_preview_itself(make_preview, tmp_path):
    w = make_preview()
    w.resize(320, 240)

    _show_a_red_video(w, tmp_path)

    assert _middle_of_the_media(w) == QColor("red")


@pytest.mark.parametrize("show_red", [_show_a_red_video, _show_a_red_still],
                         ids=["video", "still"])
def test_a_message_leaves_the_item_under_it_as_it_was(make_preview, tmp_path, show_red):
    w = make_preview()
    w.resize(320, 240)
    show_red(w, tmp_path)

    w.set_message("(not yet generated with modifications)")

    assert _middle_of_the_media(w) == QColor("red")


def test_a_preview_starts_with_no_message(make_preview):
    w = make_preview()
    assert w._message.isHidden()


def test_a_message_says_its_piece(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))

    w.set_message("(not yet generated with modifications)")

    assert not w._message.isHidden()
    assert w._message.text() == "(not yet generated with modifications)"


def test_a_message_already_up_is_not_raised_again(make_preview, tmp_path, monkeypatch):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_message("modified")
    raised = []
    monkeypatch.setattr(w, "_raise_message", lambda: raised.append("again"))

    w.set_message("modified")

    assert raised == [], "already saying exactly this: it is not raised again mid-typing"


def test_the_plate_sits_in_the_top_left_corner_clear_of_both_edges(make_preview, tmp_path):
    w = make_preview()
    w._media_host.resize(300, 200)
    w.show_image(_make_png(tmp_path / "p.png"))

    w.set_message("modified")

    assert 0 < w._message.x() < w._media_host.width() // 2
    assert 0 < w._message.y() < w._media_host.height() // 2
    assert w._message.width() <= w._media_host.width()


def test_clearing_the_message_takes_it_away(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_message("modified")

    w.set_message(None)

    assert w._message.isHidden()


@pytest.mark.parametrize("show", [
    lambda w, tmp: w.show_image(_make_png(tmp / "q.png")),
    lambda w, tmp: w.show_video(tmp / "clip.mp4"),
    lambda w, tmp: w.show_frame(_png_bytes()),
    lambda w, tmp: w.show_message("Waiting for preview…"),
    lambda w, tmp: w.clear(),
    lambda w, tmp: w.show_combination(Combination(_make_png(tmp / "c.png"))),
])
def test_a_new_view_drops_the_message_about_the_last_one(make_preview, tmp_path, show):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_message("modified")

    show(w, tmp_path)

    assert w._message.isHidden()


def test_frames_of_the_item_itself_leave_the_message_up(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_message("modified")

    w.show_frame(_png_bytes(), enhancing=True)

    assert not w._message.isHidden()
    assert w._message.text() == "modified"


def test_a_kept_message_rides_over_the_frame_that_lands_under_it(make_preview, tmp_path):
    w = make_preview()
    # A QStackedLayout does nothing when told to show the page it is already showing.
    w.show_video(tmp_path / "clip.mp4")
    w.set_message("modified")

    w.show_frame(_png_bytes(), enhancing=True)

    order = w._media_host.children()
    assert order.index(w._message) > order.index(w._image_label)


def test_narrowing_the_pane_wraps_the_plate_to_fit_inside_it(make_preview, tmp_path):
    w = make_preview()
    w._media_host.resize(600, 200)
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_message("(not yet generated with modifications)")
    old = w._image_label.size()

    w._media_host.resize(120, 200)
    w._image_label.resize(120, 200)
    QApplication.sendEvent(w._image_label, QResizeEvent(QSize(120, 200), old))

    assert w._message.x() + w._message.width() <= w._media_host.width()



def test_a_combination_shows_the_pair_instead_of_the_placeholder(make_preview, tmp_path):
    w = make_preview()
    frame = _make_png(tmp_path / "frame.png")
    video = _animated_webp(tmp_path / "source.webp")

    w.show_combination(Combination(frame, video))

    assert w._stack.currentWidget() is w._combination
    assert not w._combination.image_label.pixmap().isNull()
    assert not w._combination.plus_label.isHidden()


def test_the_source_video_half_of_a_combination_loops_in_gray(make_preview, tmp_path):
    w = make_preview()
    w.show()
    w.resize(400, 200)

    w.show_combination(Combination(_make_png(tmp_path / "frame.png"),
                                   _animated_webp(tmp_path / "source.webp")))

    color = w._combination.video_label.pixmap().toImage().pixelColor(1, 1)
    assert color.red() == color.green() == color.blue()


def test_a_combination_with_no_source_video_shows_the_frame_alone(make_preview, tmp_path):
    w = make_preview()

    w.show_combination(Combination(_make_png(tmp_path / "frame.png")))

    assert w._stack.currentWidget() is w._combination
    assert w._combination.plus_label.isHidden()
    assert w._combination.video_label.isHidden()


@pytest.mark.parametrize("edited", [False, True])
def test_the_clip_stands_in_parentheses_once_its_prompt_was_edited(make_preview, tmp_path,
                                                                   edited):
    w = make_preview()

    w.show_combination(Combination(_make_png(tmp_path / "frame.png"),
                                   _animated_webp(tmp_path / "source.webp"), edited))

    parens = (w._combination.open_paren_label, w._combination.close_paren_label)
    assert [label.isHidden() for label in parens] == [not edited, not edited]


@pytest.mark.parametrize("edited", [False, True])
def test_the_pair_asks_for_no_more_width_than_its_pane_has(qtbot, tmp_path, edited):
    host = QWidget()
    qtbot.addWidget(host)
    host.setFixedSize(440, 320)
    w = Viewport(player=MagicMock(), parent=host)
    w.setGeometry(0, 0, 440, 320)
    host.show()

    w.show_combination(Combination(_make_png(tmp_path / "frame.png"),
                                   _animated_webp(tmp_path / "source.webp"), edited))
    view = w._combination
    view.layout().activate()

    assert view.layout().minimumSize().width() <= view.width()


def test_a_frame_with_no_clip_beside_it_has_nothing_to_enclose(make_preview, tmp_path):
    w = make_preview()

    w.show_combination(Combination(_make_png(tmp_path / "frame.png"), None, True))

    assert w._combination.open_paren_label.isHidden()
    assert w._combination.close_paren_label.isHidden()


def test_an_edit_marked_on_the_pair_on_screen_encloses_its_clip_without_restarting_it(
        make_preview, tmp_path):
    w = make_preview()
    w.show_combination(Combination(_make_png(tmp_path / "frame.png"),
                                   _animated_webp(tmp_path / "source.webp")))
    looping = w._combination._movie

    w.mark_prompt_edited(True)

    assert not w._combination.open_paren_label.isHidden()
    assert not w._combination.close_paren_label.isHidden()
    assert w._combination._movie is looping


def test_showing_anything_else_puts_the_combination_down(make_preview, tmp_path):
    w = make_preview()
    w.show_combination(Combination(_make_png(tmp_path / "frame.png"),
                                   _animated_webp(tmp_path / "source.webp")))

    w.show_image(_make_png(tmp_path / "later.png"))

    assert w._stack.currentWidget() is w._image_label
    assert w._combination._movie is None

def _corners(w):
    return w._controls.buttons()


def test_an_armed_preview_wears_the_same_corners_a_thumbnail_does(make_preview,
                                                                  tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))

    w.set_actions("p1", favorite=True, enhance=icons.ENHANCE_HELD)

    assert all(not b.isHidden() for b in _corners(w))


def test_a_new_item_takes_the_last_one_s_corners_away(make_preview, tmp_path):
    w = make_preview()
    w.set_actions("p1", favorite=True, enhance=None)

    w.show_image(_make_png(tmp_path / "other.png"))

    assert w._actions_id is None
    assert all(b.isHidden() for b in _corners(w))


def test_a_running_generation_has_no_corners_to_press(make_preview):
    w = make_preview()
    w.set_actions("p1", favorite=False, enhance=None)

    w.show_frame(_png_bytes())

    assert w._actions_id is None
    assert all(b.isHidden() for b in _corners(w))


def test_a_corner_of_the_preview_names_the_generation_it_is_about(make_preview,
                                                                  tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_actions("p1", favorite=False, enhance=None)
    fired = []
    w.action_triggered.connect(lambda pid, action: fired.append((pid, action)))

    _corners(w)[0].click()

    assert fired == [("p1", corner_buttons.STAR)]


def test_right_clicking_the_item_asks_for_its_menu(make_preview, tmp_path):
    w = make_preview()
    w.show_image(_make_png(tmp_path / "p.png"))
    w.set_actions("p1", favorite=False, enhance=None)
    asked = []
    w.context_requested.connect(lambda pid, pos: asked.append(pid))

    w.customContextMenuRequested.emit(QPoint(5, 5))

    assert asked == ["p1"]


def test_right_clicking_an_unarmed_preview_asks_for_nothing(make_preview):
    w = make_preview()
    asked = []
    w.context_requested.connect(lambda pid, pos: asked.append(pid))

    w.customContextMenuRequested.emit(QPoint(5, 5))

    assert asked == []


def test_the_corners_follow_the_item_rather_than_the_pane(make_preview, tmp_path):
    w = make_preview()
    w.resize(400, 300)
    w._image_label.resize(400, 300)
    w.show_image(_make_tall_png(tmp_path / "tall.png"))
    w.set_actions("p1", favorite=True, enhance=None)

    area = w.media_rect()
    assert area.width() < w.width()
    assert area.contains(_corners(w)[0].geometry())



def _pane_holding_everything(w, tmp_path):
    w.show_image(_animated_webp(tmp_path / "held.webp"), "held")
    w.set_message("no longer what these settings would make")
    w.set_actions("held", favorite=True, enhance=None)
    w._player.reset_mock()
    return w


def test_showing_an_image_puts_down_all_the_pane_was_holding(make_preview, tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    path = _make_png(tmp_path / "next.png")
    w.show_image(path)

    assert w._player.stop.called
    assert w._message.isHidden()
    assert w._actions_id is None
    assert w._media == (path, "image")
    assert w._live is False
    assert w._movie is None
    assert w._generation is None


def test_showing_a_video_puts_down_all_the_pane_was_holding(make_preview, tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    path = tmp_path / "clip.mp4"
    w.show_video(path)

    assert not w._player.stop.called
    assert w._message.isHidden()
    assert w._actions_id is None
    assert w._media == (path, "video")
    assert w._live is False
    assert w._movie is None
    assert w._generation is None


def test_showing_a_live_frame_puts_down_all_the_pane_was_holding(make_preview,
                                                                 tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    data = _png_bytes()
    w.show_frame(data)

    assert w._player.stop.called
    assert w._message.isHidden()
    assert w._actions_id is None
    assert w._media is None
    assert w._live is True
    assert w._movie is None
    assert w._generation is None


def test_showing_a_combination_puts_down_all_the_pane_was_holding(make_preview,
                                                                  tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_combination(Combination(_make_png(tmp_path / "frame.png")))

    assert w._player.stop.called
    assert w._message.isHidden()
    assert w._actions_id is None
    assert w._media is None
    assert w._live is False
    assert w._movie is None
    assert w._generation is None


def test_showing_a_message_puts_down_all_the_pane_was_holding(make_preview,
                                                              tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_message("Waiting for preview…")

    assert w._player.stop.called
    assert w._message.isHidden()
    assert w._actions_id is None
    assert w._media is None
    assert w._live is False
    assert w._movie is None
    assert w._generation is None


def test_a_message_marked_live_leaves_the_pane_following_the_run(make_preview,
                                                                 tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_message("Generating…", live=True)

    assert w._live is True


def test_frames_of_the_item_itself_keep_the_message_they_are_about(make_preview,
                                                                  tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_frame(_png_bytes(), enhancing=True)

    assert not w._message.isHidden(), (
        "frames of an enhancement of the item on screen are the coming state of that item, so "
        "its message is as true of them and stays; cleared by each frame and put back by each "
        "keystroke, it would flicker at the rate the run streams while the form is typed in")


def test_frames_of_the_item_itself_keep_its_corners(make_preview, tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)
    star, trash, _plus = _corners(w)

    w.show_frame(_png_bytes(), enhancing=True)

    assert w.actions_id() == "held", (
        "frames of an enhancement of the item on screen are the coming state of that item, so "
        "its corners are as true of them and stay")
    assert not star.isHidden()
    assert not trash.isHidden()


def test_showing_a_folder_puts_down_all_the_pane_was_holding(make_preview,
                                                             tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)

    w.show_folder([_make_png(tmp_path / "wall.png")])

    assert w._player.stop.called
    assert w._message.isHidden()
    assert w._actions_id is None
    assert w._media is None
    assert w._live is False
    assert w._movie is None
    assert w._generation is None


def test_the_corners_over_a_folder_have_no_generation_to_fire_at(make_preview,
                                                                 tmp_path):
    w = _pane_holding_everything(make_preview(), tmp_path)
    fired = []
    w.action_triggered.connect(lambda pid, action: fired.append((pid, action)))

    w.show_folder([_make_png(tmp_path / "wall.png")])
    w._on_control("trash")

    assert fired == []
    assert all(b.isHidden() for b in _corners(w))


def test_the_player_is_torn_down_before_the_surface_it_renders_to(qapp):
    # Qt destroys a widget's children in the order they were parented; the real player must be parented before the video surface it renders to

    w = Viewport()
    order = []
    w._player.destroyed.connect(lambda *_: order.append("player"))
    w._video.destroyed.connect(lambda *_: order.append("surface"))

    del w
    gc.collect()

    assert order == ["player", "surface"]


def test_releasing_the_player_detaches_it_from_the_pane(make_preview):
    w = make_preview()
    p = w._player

    w.release_player()

    assert p.method_calls[-3:] == [
        call.stop(),
        call.setSource(QUrl()),
        call.setVideoOutput(None),
    ]


def test_a_folder_shown_fills_the_contact_sheet(make_preview, tmp_path):
    w = make_preview()

    w.show_folder([_make_png(tmp_path / "wall.png")])

    assert w._sheet.count() == 1, (
        "the pane is put down before the contact sheet is laid out, because putting it down "
        "clears the contact sheet")
