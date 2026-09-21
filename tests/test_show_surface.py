"""The show's own pane: what it asks the players' engine for."""
from __future__ import annotations

import os
from io import BytesIO

from PIL import Image
from PyQt6.QtCore import QPointF, QSize, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui import show_surface
from origenerator.gui.show_surface import ShowSurface, _NotYetOpened
from origenerator.media import MediaType
from tests.show_surface_fakes import FakeEngine


def _png_bytes() -> bytes:
    """A streamed in-progress frame: encoded image bytes, no file on disk."""
    buf = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _click(surface) -> QMouseEvent:
    at = QPointF(surface.rect().center())
    return QMouseEvent(QMouseEvent.Type.MouseButtonPress, at,
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


def _surface(qtbot, **kw):
    engine = FakeEngine()
    surface = ShowSurface(engine=engine, **kw)
    qtbot.addWidget(surface)
    return surface, engine


def test_a_slide_is_handed_to_the_engine_to_open(qtbot, tmp_path):
    picture = tmp_path / "made-up.png"
    picture.write_bytes(b"")
    surface, engine = _surface(qtbot)

    surface.show_media(str(picture), MediaType.IMAGE)

    assert engine.loaded == [picture]
    assert surface.current_media_path() == str(picture)


def test_the_pace_a_picture_holds_for_goes_to_the_engine(qtbot):
    surface, engine = _surface(qtbot)

    surface.set_pace(6)

    assert engine.pace == 6


def test_an_item_that_ran_out_is_said_once(qtbot, tmp_path):
    clip = tmp_path / "made-up.mp4"
    clip.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.show_media(str(clip), MediaType.VIDEO)
    ended = []
    surface.media_ended.connect(lambda: ended.append(1))

    engine.eof = True
    surface._follow_the_engine()
    surface._follow_the_engine()

    assert ended == [1]


def test_a_file_that_would_not_open_is_said_rather_than_waited_out(qtbot, tmp_path):
    clip = tmp_path / "made-up.mp4"
    clip.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.show_media(str(clip), MediaType.VIDEO)
    refused = []
    surface.media_unplayable.connect(lambda: refused.append(1))

    engine.idle = True
    surface._follow_the_engine()
    surface._follow_the_engine()

    assert refused == [1]


def test_nothing_is_said_about_an_engine_with_nothing_asked_of_it(qtbot):
    surface, engine = _surface(qtbot)
    said = []
    surface.media_ended.connect(lambda: said.append("ended"))
    surface.media_unplayable.connect(lambda: said.append("refused"))

    engine.idle = True
    engine.eof = True
    surface._follow_the_engine()

    assert said == []


def test_a_freeze_reaches_the_engine_and_the_next_slide_arrives_frozen(qtbot, tmp_path):
    first, second = (tmp_path / "one.png"), (tmp_path / "two.png")
    for picture in (first, second):
        picture.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.show_media(str(first), MediaType.IMAGE)

    surface.set_paused(True)
    assert engine.paused is True

    surface.show_media(str(second), MediaType.IMAGE)
    assert engine.paused is True


def test_the_show_owns_its_sound(qtbot):
    surface, engine = _surface(qtbot)

    surface.set_audio_muted(True)

    assert engine.muted is True
    assert surface.audio_muted() is True


def test_a_run_still_being_made_is_its_frames_rather_than_a_file(qtbot, tmp_path):
    picture = tmp_path / "made-up.png"
    picture.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.show_media(str(picture), MediaType.IMAGE)

    surface.show_frame(_png_bytes())

    assert surface.current_media_path() == ""
    assert engine.loaded == [picture]          # the engine was not asked again


def test_a_message_stands_where_the_picture_would(qtbot):
    surface, _engine = _surface(qtbot)

    surface.show_message("Generating…")

    assert surface._picture.text() == "Generating…"
    assert surface.current_media_path() == ""


def test_the_picture_is_measured_where_it_is_actually_drawn(qtbot, tmp_path):
    """A portrait picture on a wide pane leaves surround either side of it, and
    what is floated beside the picture has to keep clear of the picture, not of
    the pane."""
    picture = tmp_path / "made-up.png"
    picture.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.resize(800, 600)
    surface.layout().activate()
    surface.show_media(str(picture), MediaType.IMAGE)
    engine.video_dims = (600, 900)

    rect = surface.media_rect()

    assert rect.width() == 400 and rect.height() == 600
    assert rect.center() == surface._media_host.geometry().center()


def test_a_pane_with_nothing_measurable_on_it_is_measured_whole(qtbot):
    surface, _engine = _surface(qtbot)
    surface.resize(800, 600)
    surface.layout().activate()

    assert surface.media_rect() == surface._media_host.geometry()


def test_a_picture_of_a_new_size_is_said_once(qtbot, tmp_path):
    picture = tmp_path / "made-up.png"
    picture.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.show_media(str(picture), MediaType.IMAGE)
    sizes = []
    surface.media_resized.connect(lambda: sizes.append(1))

    engine.video_dims = (600, 900)
    surface._follow_the_engine()
    surface._follow_the_engine()

    assert sizes == [1]


def test_a_file_about_to_be_deleted_is_let_go_of(qtbot, tmp_path):
    picture = tmp_path / "made-up.png"
    picture.write_bytes(b"")
    surface, _engine = _surface(qtbot)
    surface.show_media(str(picture), MediaType.IMAGE)

    surface.release_media([str(picture)])

    assert surface.current_media_path() == ""


def test_a_file_that_is_not_the_one_on_screen_is_left_alone(qtbot, tmp_path):
    picture, other = (tmp_path / "one.png"), (tmp_path / "two.png")
    for each in (picture, other):
        each.write_bytes(b"")
    surface, _engine = _surface(qtbot)
    surface.show_media(str(picture), MediaType.IMAGE)

    surface.release_media([str(other)])

    assert surface.current_media_path() == str(picture)


def test_a_clip_names_itself_for_the_device_to_drive_off(qtbot, tmp_path):
    clip, picture = (tmp_path / "made-up.mp4"), (tmp_path / "made-up.png")
    for each in (clip, picture):
        each.write_bytes(b"")
    surface, _engine = _surface(qtbot)

    surface.show_media(str(clip), MediaType.VIDEO)
    assert surface.current_video_path() == str(clip)
    assert surface.is_showing_video() is True

    surface.show_media(str(picture), MediaType.IMAGE)
    assert surface.current_video_path() is None
    assert surface.is_showing_video() is False


def test_closing_the_pane_closes_the_engine(qtbot):
    surface, engine = _surface(qtbot)

    surface.close_engine()

    assert engine.closed is True


def test_a_press_over_the_picture_reaches_the_show(qtbot):
    pressed = []
    surface, _engine = _surface(qtbot, on_press=lambda: pressed.append(1))

    surface.mousePressEvent(_click(surface))

    assert pressed == [1]


def test_a_double_click_over_the_picture_reaches_the_show(qtbot):
    twice = []
    surface, _engine = _surface(qtbot, on_double_click=lambda: twice.append(1))

    surface.mouseDoubleClickEvent(_click(surface))

    assert twice == [1]


def test_a_live_frame_is_refitted_when_the_pane_changes_shape(qtbot):
    surface, _engine = _surface(qtbot)
    surface.show()                 # an unshown pane is never resized at all
    surface._picture.resize(800, 600)
    surface.show_frame(_png_bytes())
    assert surface._picture.pixmap().size() == QSize(800, 600)

    surface._picture.resize(400, 300)

    assert surface._picture.pixmap().size() == QSize(400, 300)


def test_the_drive_is_told_where_the_clip_has_got_to(qtbot):
    surface, engine = _surface(qtbot)
    engine.position_ms = 12345.6

    assert surface.position() == 12345


# --- opening the engine, and what it is handed when it does -----------------

def test_a_pane_with_no_window_to_draw_into_keeps_the_stand_in(qtbot):
    """The suite draws on a platform with no windows in it, and an engine
    handed one of those has nothing to paint."""
    surface = ShowSurface()
    qtbot.addWidget(surface)

    surface.show()
    surface.open_the_engine()

    assert isinstance(surface._engine, _NotYetOpened)


def test_an_engine_that_will_not_open_leaves_the_stand_in(qtbot, monkeypatch, caplog):
    surface = ShowSurface()
    qtbot.addWidget(surface)
    monkeypatch.setattr(QApplication.instance(), "platformName", lambda: "windows")
    monkeypatch.setattr("player_core.mpv_player.MpvPlayer",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("no engine")))

    surface.open_the_engine()

    assert isinstance(surface._engine, _NotYetOpened)
    assert "could not open" in caplog.text


def test_the_engine_opens_on_the_slide_and_pace_it_missed(tmp_path):
    waiting = _NotYetOpened()
    waiting.set_muted(True)
    waiting.set_pace(6)
    waiting.load(tmp_path / "made-up.png")
    waiting.set_paused(True)
    opened = FakeEngine()

    waiting.replay(opened)

    assert opened.muted is True
    assert opened.pace == 6
    assert opened.loaded == [tmp_path / "made-up.png"]
    assert opened.paused is True


def test_an_engine_that_opens_before_a_slide_is_handed_nothing_to_play():
    waiting = _NotYetOpened()
    opened = FakeEngine()

    waiting.replay(opened)

    assert opened.loaded == []
    assert opened.pace is None
    assert opened.paused is None


def test_letting_go_of_a_file_lets_the_engine_go_of_it_too(qtbot, tmp_path):
    """Windows refuses to move a file out from under an open handle, and the
    engine holds one on whatever it is playing."""
    picture = tmp_path / "made-up.png"
    picture.write_bytes(b"")
    surface, engine = _surface(qtbot)
    surface.show_media(str(picture), MediaType.IMAGE)

    surface.release_media([str(picture)])

    assert engine.stopped is True


def test_the_engine_copy_beside_the_checkouts_goes_in_front(monkeypatch, tmp_path):
    """The engine is one file, fetched once for the machine, with a copy beside
    the checkouts. The machine-wide folder has answered nothing at all to this
    app while answering every other process, so the copy beside goes first."""
    beside = tmp_path / "player_core" / "vendor"
    beside.mkdir(parents=True)
    (beside / "libmpv-2.dll").write_bytes(b"")
    monkeypatch.setattr(show_surface, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setenv("PATH", r"C:\somewhere\else")

    show_surface._offer_the_copy_beside_the_checkouts()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(beside)


def test_no_copy_beside_the_checkouts_leaves_the_path_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(show_surface, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setenv("PATH", r"C:\somewhere\else")

    show_surface._offer_the_copy_beside_the_checkouts()

    assert os.environ["PATH"] == r"C:\somewhere\else"
