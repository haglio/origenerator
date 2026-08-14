"""AutoGenerateView — the loop's slideshow: rotation, satellite keys, stroke keys."""

from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QEvent, QUrl
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.auto_generate_view import AutoGenerateView
from origenerator.stroke_engine import Stroke


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


class FakeStroke:
    """Stands in for Osr2StrokeDriver: records the calls, flips on toggle. A
    real Stroke rides along so the drive panel can draw from it."""

    def __init__(self):
        self.active = False
        self.calls = []
        self.state = Stroke()

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        return self.active

    def stop(self):
        self.active = False
        self.calls.append(("stop",))

    def adjust_speed(self, delta):
        self.calls.append(("speed", delta))

    def adjust_amplitude(self, delta):
        self.calls.append(("amplitude", delta))

    def adjust_center(self, delta):
        self.calls.append(("center", delta))

    def toggle_cruise(self):
        self.calls.append("cruise")

    def quarter_offset(self):
        self.calls.append("nudge")

    def cycle_shape(self):
        self.calls.append(("shape",))

    def status_text(self):
        return "OSR2 stub"


def _view(qtbot, seeded=0, tmp_path=None):
    view = AutoGenerateView(player=MagicMock(), stroke=FakeStroke())
    qtbot.addWidget(view)
    for i in range(seeded):
        view.add_finished(_png(tmp_path / f"seed{i}.png"), "image", f"id-{i}")
    return view


def test_the_slots_either_side_ride_along_as_stills(qtbot, tmp_path):
    view = _view(qtbot, seeded=2, tmp_path=tmp_path)  # sitting on the live slot
    frame = _png_bytes()
    view.show_live_frame(frame)

    # Behind the live slot is the newest finished item; ahead, wrapping, the oldest.
    assert view._neighbors._sources == (str(tmp_path / "seed1.png"),
                                        str(tmp_path / "seed0.png"))

    _press(view, Qt.Key.Key_Left)  # step back onto the newest finished item
    # The live slot is next door now, and shows the generation's latest frame.
    assert view._neighbors._sources == (str(tmp_path / "seed0.png"), frame)


def test_opens_on_the_live_slot_awaiting_frames(qtbot):
    view = _view(qtbot)
    assert view._playlist.on_live()
    assert "Generating" in view._preview._image_label.text()


def test_a_live_frame_fills_the_live_slot(qtbot):
    view = _view(qtbot)
    view.show_live_frame(_png_bytes())
    # A streamed frame has no file behind it — an image is shown, not a video.
    assert view._preview.is_showing_video() is False
    assert view._preview._media is None


def test_seeding_accumulates_but_keeps_the_live_slot_on_screen(qtbot, tmp_path):
    view = _view(qtbot, seeded=2, tmp_path=tmp_path)
    assert view._playlist.count == 3
    assert view._playlist.on_live()
    assert view._counter.text().startswith("3 / 3")
    assert "generating" in view._counter.text()


def test_left_and_right_step_through_the_rotation(qtbot, tmp_path):
    view = _view(qtbot, seeded=2, tmp_path=tmp_path)
    _press(view, Qt.Key.Key_Left)                      # off the live slot
    assert view._playlist.current()[2] == "id-1"       # the newest finished item
    assert view._preview._media is not None
    _press(view, Qt.Key.Key_Right)                     # and back onto it
    assert view._playlist.on_live()


def test_the_rotation_auto_advances_on_the_dwell_timer(qtbot, tmp_path):
    view = _view(qtbot, seeded=1, tmp_path=tmp_path)
    assert view._timer.isActive()          # the live slot dwells like an image
    view._advance()
    assert view._playlist.current()[2] == "id-0"       # wrapped to the oldest
    assert view._timer.isActive()          # and re-armed for the next step


def test_a_completion_takes_over_the_live_slot_on_screen(qtbot, tmp_path):
    view = _view(qtbot)
    view.show_live_frame(_png_bytes())
    view.note_finished(_png(tmp_path / "done.png"), "image", "id-done")
    assert view._preview._media == (str(tmp_path / "done.png"), "image")
    assert not view._playlist.on_live()    # showing the finished file...
    assert view._playlist.live             # ...with the next launch's slot trailing


def test_up_on_the_live_slot_asks_to_cancel(qtbot):
    view = _view(qtbot)
    view.show_live_frame(_png_bytes())
    fired = []
    view.cancel_requested.connect(lambda: fired.append(True))
    _press(view, Qt.Key.Key_Up)
    assert fired == [True]
    # The skipped generation's frame is dropped; the next launch streams fresh ones.
    assert "Generating" in view._preview._image_label.text()


def test_up_on_a_finished_item_marks_it_weird_and_drops_it(qtbot, tmp_path):
    view = _view(qtbot, seeded=2, tmp_path=tmp_path)
    _press(view, Qt.Key.Key_Left)  # onto id-1
    condemned = []
    view.weird_requested.connect(condemned.append)
    _press(view, Qt.Key.Key_Up)
    assert condemned == ["id-1"]
    assert [item[2] for item in view._playlist._items] == ["id-0"]


def test_condemning_the_last_item_of_a_dead_loop_closes_the_view(qtbot, tmp_path):
    view = _view(qtbot, seeded=1, tmp_path=tmp_path)
    view.show()
    view.set_generating(False)     # the loop ended; only id-0 remains
    _press(view, Qt.Key.Key_Up)
    assert not view.isVisible()


def test_down_locks_the_current_item_against_the_advance(qtbot, tmp_path):
    view = _view(qtbot, seeded=1, tmp_path=tmp_path)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked
    assert not view._timer.isActive()
    assert "locked" in view._counter.text()
    _press(view, Qt.Key.Key_Down)  # release
    assert not view._playlist.locked
    assert view._timer.isActive()


def test_stepping_away_releases_the_lock(qtbot, tmp_path):
    view = _view(qtbot, seeded=1, tmp_path=tmp_path)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Right)
    assert not view._playlist.locked


def test_a_finished_video_advances_unless_locked(qtbot, tmp_path):
    view = _view(qtbot)
    view.note_finished("clip.mp4", "video", "id-v")  # on screen, the live slot trailing
    view._preview.video_ended.emit()
    assert view._playlist.on_live()                  # it played through: moved on
    _press(view, Qt.Key.Key_Left)                    # back onto the video
    _press(view, Qt.Key.Key_Down)                    # lock it
    view._preview.video_ended.emit()
    assert view._playlist.current()[2] == "id-v"     # held: it replays instead


def test_the_loop_ending_drops_the_live_slot_but_keeps_rotating(qtbot, tmp_path):
    view = _view(qtbot, seeded=2, tmp_path=tmp_path)
    view.set_generating(False)
    assert view._playlist.count == 2
    assert view._preview._media is not None          # fell back to the newest item
    assert "generating" not in view._counter.text()


def test_the_drive_panel_shows_only_while_the_stroke_runs(qtbot):
    # A readout of a stroke nobody is making is not information: the panel is
    # built with the view but stays down until the stroke is actually driving,
    # and goes back down when it stops.
    view = _view(qtbot)
    assert view._stroke_panel is not None
    assert view._stroke_panel.isHidden()
    assert "Space" in view._stroke_panel.toolTip()

    _press(view, Qt.Key.Key_Space)
    assert not view._stroke_panel.isHidden()

    _press(view, Qt.Key.Key_Space)
    assert view._stroke_panel.isHidden()


def test_space_toggles_the_stroke(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Space)
    assert ("toggle", True) in view._stroke.calls
    _press(view, Qt.Key.Key_Space)
    assert ("toggle", False) in view._stroke.calls


def test_the_stroke_keys_map_like_genau(qtbot):
    view = _view(qtbot)
    for key in (Qt.Key.Key_J, Qt.Key.Key_L, Qt.Key.Key_7, Qt.Key.Key_9,
                Qt.Key.Key_U, Qt.Key.Key_O, Qt.Key.Key_I):
        _press(view, key)
    assert view._stroke.calls == [
        ("speed", -5), ("speed", 5),
        ("amplitude", -10), ("amplitude", 10),
        ("center", -5), ("center", 5),
        ("shape",),
    ]


def test_escape_closes_and_emits_closed(qtbot):
    view = _view(qtbot)
    view.showFullScreen()
    closed = []
    view.closed.connect(lambda: closed.append(True))
    _press(view, Qt.Key.Key_Escape)
    assert not view.isVisible()
    assert closed == [True]


def test_closing_leaves_the_stroke_running_and_releases_the_media(qtbot):
    # The stroke is the gallery's, app-global: dismissing the slideshow must not
    # park the device mid-use. (Esc in the gallery is the panic-stop.)
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Space)   # the stroke is driving
    view.close()
    assert ("stop",) not in view._stroke.calls
    assert view._stroke.active
    view._preview._player.setSource.assert_called_with(QUrl())
