"""The one panel a slideshow wears: what the slideshow tells it to draw, where the
Funestra draws it, and what a press on it asks of the slideshow."""
from __future__ import annotations

import json

import numpy as np
import pytest
from app_support.osr2_device import Osr2Mode, Osr2Trouble
from funestra.hud_corners import CORNER_PLUS_OVERLAY_ID
from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.hud_placement import HudCorner
from funestra.modes import Osr2State
from funestra.satellite_hud import MARGIN
from funestra.timeline import TIMELINE_HEIGHT
from PyQt6.QtCore import QEvent, QPoint, QPointF
from PyQt6.QtWidgets import QApplication

from origenerator.gui.hud_queue import CANCEL, OPEN
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.motion_panel import MotionPanel
from origenerator.gui.osr2_control import Osr2Control
from origenerator.gui.slideshow_pace import MAX_S, MIN_S, STEP_S
from origenerator.gui.slideshow_panel import slideshow_hud_model
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.slideshow import in_order
from tests import gestures
from tests.funestra_fakes import FakeEngine
from tests.motion_doubles import FakeMotion
from tests.slideshow_hud_support import button_on_screen, panel_targets


def _inflight(key="j1", status="queued", cancel=None, **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "started_at", "typical_seconds")}
    return InFlightItem(key=key, caption="Alpha Workflow › a paper kite",
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), cancel=cancel, **kw)


def _window(qtbot, items=(("scene one.png", "image"), ("scene two.png", "image")), **kw):
    kw.setdefault("engine", FakeEngine())
    window = SlideshowView(list(items), shuffle=in_order, **kw)
    qtbot.addWidget(window)
    return window


def _dressed(qtbot, items=(("scene one.png", "image"), ("scene two.png", "image")),
             side="portrait", **kw):
    wear = {name: kw.pop(name) for name in ("dashboard_cmd_file", "collapse", "open_in", "label_for")
            if name in kw}
    window = _window(qtbot, items, **kw)
    window.wear_the_hud(side, **wear)
    return window


def _panel(window):
    """The panel as the Funestra composited it: where, and the pixels."""
    window._pane.tick()
    return window._pane._engine.overlays[HUD_OVERLAY_ID]


def _lit_order(model) -> list[str]:
    return [button.command for row in model.rows for button in row
            if button.command in ("portrait_shuffle", "portrait_latest") and button.lit]


def test_the_panel_lights_the_order_the_slideshow_is_playing_in(qtbot):
    for order_label, lit in (("Latest", ["portrait_latest"]),
                             ("Shuffle", ["portrait_shuffle"]),
                             ("", [])):
        window = _window(qtbot, [("scene one.png", "image")], hud=HudFacts(order_label=order_label))

        assert _lit_order(slideshow_hud_model("portrait", window.slideshow)) == lit, order_label


def test_the_panel_carries_what_is_being_made_of_the_item_on_screen(qtbot):
    window = _window(qtbot, [("scene one.png", "image", "id-one")])

    window.slideshow.note_enhancing({"id-one": "running"})

    assert slideshow_hud_model("portrait", window.slideshow).item_note == "Enhancing…"


def test_a_slideshow_wears_its_panel_the_moment_it_is_dressed(qtbot):
    window = _dressed(qtbot)

    (x, y, _bgra) = _panel(window)

    assert (x, y) == (MARGIN, MARGIN)


def test_an_undressed_slideshow_wears_nothing(qtbot):
    window = _window(qtbot)

    window._pane.tick()

    assert HUD_OVERLAY_ID not in window._pane._engine.overlays


def test_a_slideshow_whose_funestra_is_not_open_yet_still_has_its_panel_ready(qtbot):
    """The first beat comes before the pane has a window to hand the engine."""
    window = SlideshowView([("scene one.mp4", "video")], shuffle=in_order)
    qtbot.addWidget(window)
    window.wear_the_hud("portrait")

    assert window._hud_model() is not None


def test_a_slideshow_with_nothing_to_map_has_no_panel(qtbot, monkeypatch):
    slideshow = _window(qtbot).slideshow
    monkeypatch.setattr(slideshow, "hud_map", lambda: None)

    assert slideshow_hud_model("portrait", slideshow) is None


def test_the_panel_names_the_item_the_way_this_app_names_it(qtbot):
    window = _dressed(qtbot, [("scene one.png", "image", "id-one")],
                         label_for=lambda prompt_id: f"Example folder / {prompt_id}")

    assert window.item_label() == "Example folder / id-one"


class TestTheOnePanelASlideshowWears:
    """A slideshow used to wear TWO panels: the Funestras' HUD for the set, and Genau's
    whole console seated under it for the device.  Between them the status was
    said twice and disagreed -- "Looping seeds · Shuffle" over "Unlocked · 4s" --
    and prev, next, lock and trash were drawn on both.

    One panel now: the Funestras' HUD, carrying the device's line and the drive
    readout out of the console's own code.
    """

    @staticmethod
    def _window(qtbot, **kwargs):
        motion = FakeMotion()
        return _window(qtbot, motion=motion, actions=SlideshowActions(osr2_control=Osr2Control(motion)),
                          **kwargs)

    def test_the_slideshow_floats_no_second_panel(self, qtbot):
        assert self._window(qtbot).findChildren(MotionPanel) == []

    def _model(self, qtbot):
        window = self._window(qtbot)
        return slideshow_hud_model("portrait", window.slideshow, device=window.hud_device)

    def test_the_device_is_on_the_one_panel(self, qtbot):
        model = self._model(qtbot)

        assert model.osr2 != ""          # who has the device
        assert model.drive is not None   # and the motion it is being sent

    def test_the_osr2_line_carries_the_max_intensity_the_motion_is_held_to(self, qtbot):
        window = self._window(qtbot)
        window._motion.set_max_intensity(35)

        assert slideshow_hud_model("portrait", window.slideshow, device=window.hud_device).max_intensity == 35

    def test_a_slideshow_that_is_not_driving_the_device_carries_no_max_intensity(self, qtbot):
        assert slideshow_hud_model("portrait", self._window(qtbot).slideshow).max_intensity is None

    def test_the_pace_rides_with_the_rows_that_step_the_set(self, qtbot):
        """It sets how long an unheld slide stays up, which is about the set."""
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert "genau_clip_seconds_up" in posted
        assert "robot_hand_cycle_shape" not in posted

    def test_everything_that_aims_the_device_rides_with_the_device(self, qtbot):
        """Human-inspired motion, the waveform and the OSR2 switch act on the
        OSR2, so they sit in its own block at the foot of the
        panel rather than up among the rows that act on the set."""
        model = self._model(qtbot)
        aiming = [button.command for row in model.osr2_rows for button in row]

        assert "robot_hand_toggle_learned" in aiming
        assert "robot_hand_cycle_shape" in aiming
        assert "robot_hand_release" in aiming

    def test_the_transport_is_drawn_once(self, qtbot):
        """The console's own prev/next/lock/trash row is off it: the side's
        four are already there, and they act on the very same slideshow."""
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert posted.count("portrait_prev") == 1
        assert "genau_prev_clip" not in posted
        assert "main_lock" not in posted
        assert "genau_weird_clip" not in posted

    def test_the_readout_the_slideshow_composes_reaches_the_panel_the_funestra_draws(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")

        assert panel_targets(window).tracks

    def test_a_press_on_the_motion_row_reaches_the_motion(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")

        window.press("robot_hand_cycle_shape")

        assert "shape" in window._motion.calls

    def test_a_press_on_the_clip_seconds_pair_paces_the_slideshow(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")

        window.press("genau_clip_seconds_up")
        assert window.slideshow.dwell_s == 4 + STEP_S

        window.press("genau_clip_seconds_down")
        assert window.slideshow.dwell_s == 4

    def test_the_clip_seconds_pair_stops_at_its_ends(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")

        window.slideshow.set_dwell_s(MAX_S)
        window.press("genau_clip_seconds_up")
        assert window.slideshow.dwell_s == MAX_S

        window.slideshow.set_dwell_s(MIN_S)
        window.press("genau_clip_seconds_down")
        assert window.slideshow.dwell_s == MIN_S

    def test_a_hosted_side_verb_still_goes_out_on_the_sessions_channel(self, qtbot, tmp_path):
        """The device rows are checked before the session's transport now, so a
        side verb that fell into them would be swallowed instead of posted."""
        window = self._window(qtbot)
        channel = tmp_path / "dashboard_cmd.txt"
        window.wear_the_hud("portrait", dashboard_cmd_file=channel)

        window.press("portrait_next")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_next"]

    def test_a_press_on_the_transport_still_reaches_the_slideshow(self, qtbot):
        """The device rows sit beside the side's own band, not in place of it."""
        window = self._window(qtbot)
        window.wear_the_hud("portrait")
        before = window.slideshow._set.playlist.index

        window.press("portrait_next")
        window.slideshow.tick()  # it reads its Funestra, as its poll does a moment later

        assert window.slideshow._set.playlist.index != before

    def _worn_on_a_device_that_is_on(self, qtbot, monkeypatch, now):
        monkeypatch.setattr("origenerator.gui.slideshow_view.osr2_device.device_mode",
                            lambda: Osr2Mode.CONTROLLED)
        window = self._window(qtbot, clock=lambda: now[0])
        window.wear_the_hud("portrait")
        return window

    def test_the_panel_says_why_the_broker_cannot_hear_the_osr2(self, qtbot, monkeypatch):
        monkeypatch.setattr("origenerator.gui.slideshow_view.osr2_device.device_mode",
                            lambda: Osr2Mode.OFF)
        monkeypatch.setattr("origenerator.gui.slideshow_view.osr2_device.device_trouble",
                            lambda: Osr2Trouble.NOT_ANSWERING)
        window = self._window(qtbot)

        assert window.hud_device.osr2 is Osr2State.NO_ANSWER

    def test_an_idle_device_leaves_the_panel_on_its_resting_beat(self, qtbot, monkeypatch):
        now = [0.0]
        window = self._worn_on_a_device_that_is_on(qtbot, monkeypatch, now)
        first = window._hud_model()

        now[0] = 0.15

        assert window._hud_model() is first

    def test_a_moving_trace_rebuilds_the_panel_on_the_fast_beat(self, qtbot, monkeypatch):
        now = [0.0]
        window = self._worn_on_a_device_that_is_on(qtbot, monkeypatch, now)
        window._motion.active = True
        first = window._hud_model()

        now[0] = 0.15

        assert window._hud_model() is not first


class TestWhereTheSlideshowsPanelSits:
    """The room moves this panel round the corners of the slideshow, and collapses it
    to a square with a plus on it."""

    @staticmethod
    def _window(qtbot, **kw):
        window = _dressed(qtbot, [("scene one.png", "image")], **kw)
        window.resize(900, 600)
        window.show()
        return window

    def test_the_panel_moves_to_the_corner_it_is_given(self, qtbot):
        window = self._window(qtbot)

        window.set_hud_place(HudCorner.LOWER_RIGHT, False)

        x, y, bgra = _panel(window)
        width, height = window._pane._device_size()
        assert x == width - MARGIN - bgra.shape[1]
        assert y == height - MARGIN - bgra.shape[0]

    def test_a_collapsed_panel_is_the_plus_button_alone(self, qtbot):
        window = self._window(qtbot)
        wide = _panel(window)[2].shape[1]

        window.set_hud_place(HudCorner.UPPER_LEFT, True)

        assert _panel(window)[2].shape[1] < wide
        assert [button.command for _rect, button in panel_targets(window).buttons] == [
            "portrait_hud_restore"]

    def test_a_standalone_press_on_the_minus_collapses_it_here(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(qtbot, collapse=collapsed.append)

        window.press("portrait_hud_minimize")

        assert collapsed == [True]

    def test_a_click_landing_on_the_minus_is_what_collapses_it(self, qtbot):
        """The whole way in: a left button down on the square, where the panel
        drew it, and the panel is a plus by the time the button comes back up."""
        collapsed: list[bool] = []
        window = self._window(qtbot, collapse=collapsed.append)
        (rect, _minus), = [(rect, button) for rect, button in panel_targets(window).buttons
                           if button.command.endswith("hud_minimize")]

        _click_at(window, rect)

        assert collapsed == [True]

    def test_a_click_on_the_plus_asks_for_the_panel_back(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(qtbot, collapse=collapsed.append)
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = panel_targets(window).buttons

        _click_at(window, rect)

        assert collapsed == [False]

    def test_a_hosted_press_on_the_minus_goes_out_on_the_sessions_channel(
            self, qtbot, tmp_path):
        channel = tmp_path / "dashboard_cmd.txt"
        window = self._window(qtbot, dashboard_cmd_file=channel)

        window.press("portrait_hud_minimize")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_hud_minimize"]

    def _a_plus_nobody_has_pointed_at(self, qtbot):
        window = self._window(qtbot)
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        return _panel(window)[2]

    def test_a_click_on_the_minus_leaves_the_plus_without_its_tooltip(self, qtbot):
        window = self._window(qtbot, collapse=lambda minimized: window.set_hud_place(
            HudCorner.UPPER_LEFT, minimized))
        (rect, _minus), = [(rect, button) for rect, button in panel_targets(window).buttons
                           if button.command.endswith("hud_minimize")]
        _point_at(window, rect)

        _click_at(window, rect)

        assert np.array_equal(_panel(window)[2], self._a_plus_nobody_has_pointed_at(qtbot))

    def test_the_plus_drops_its_tooltip_when_the_pointer_leaves_the_window(self, qtbot):
        window = self._window(qtbot)
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = panel_targets(window).buttons
        _point_at(window, rect)
        assert not np.array_equal(_panel(window)[2], self._a_plus_nobody_has_pointed_at(qtbot))

        QApplication.sendEvent(window._pane._window, QEvent(QEvent.Type.Leave))

        assert np.array_equal(_panel(window)[2], self._a_plus_nobody_has_pointed_at(qtbot))


class TestACornerThePanelIsNotIn:
    """A click in any other corner of the slideshow sends its panel there, the way it
    does on every Funestra, and the pointer in such a corner shows the plus that
    says so."""

    @staticmethod
    def _window(qtbot, **kw):
        return TestWhereTheSlideshowsPanelSits._window(qtbot, **kw)

    def test_a_click_there_opens_the_panel_there(self, qtbot):
        opened: list[HudCorner] = []
        window = self._window(qtbot, open_in=opened.append)
        _panel(window)
        width, height = window._pane._device_size()

        window._pane.press(QPointF(width - 3, height - 3))
        window._pane.release()

        assert opened == [HudCorner.LOWER_RIGHT]

    def test_a_hosted_click_there_goes_out_on_the_sessions_channel(self, qtbot, tmp_path):
        channel = tmp_path / "dashboard_cmd.txt"
        window = self._window(qtbot, dashboard_cmd_file=channel)

        window.press("portrait_hud_restore_at|lower_left")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_hud_restore_at|lower_left"]

    def test_the_pointer_there_shows_the_plus(self, qtbot):
        window = self._window(qtbot)
        _panel(window)
        width, height = window._pane._device_size()

        window._pane.motion(QPointF(width - 3, height - 3), held=False)
        window._pane.tick()

        assert CORNER_PLUS_OVERLAY_ID in window._pane._engine.overlays

    def test_the_pointer_leaving_the_window_takes_the_plus_down(self, qtbot):
        window = self._window(qtbot)
        window.set_hud_place(HudCorner.LOWER_RIGHT, False)
        _panel(window)
        _width, height = window._pane._device_size()
        window._pane.motion(QPointF(3, height - 3), held=False)
        window._pane.tick()

        QApplication.sendEvent(window._pane._window, QEvent(QEvent.Type.Leave))
        window._pane.tick()

        assert CORNER_PLUS_OVERLAY_ID not in window._pane._engine.overlays


def _middle_of(window, rect) -> QPointF:
    left, top, _bgra = _panel(window)
    return QPointF(left + rect[0] + rect[2] / 2, top + rect[1] + rect[3] / 2)


def _point_at(window, rect) -> None:
    window._pane.motion(_middle_of(window, rect), held=False)


def _click_at(window, rect) -> None:
    """A left click at the middle of *rect*, in the panel's own pixels, where
    the Funestra composited the panel."""
    window._pane.press(_middle_of(window, rect))
    window._pane.release()


def test_an_image_still_being_generated_is_drawn_on_the_map_without_its_frame_bytes(qtbot):
    window = _window(qtbot, [("scene one.png", "image", "id-one")])
    window.slideshow.note_generating("id-run", b"\x89PNG frame bytes")
    window.slideshow.slideshow_step(1)
    window.slideshow.tick()  # it reads its Funestra, as its poll does a moment later

    corner = slideshow_hud_model("portrait", window.slideshow).corner

    assert (corner.path, corner.thumb) == ("", "")


class TestTheQueueOnTheOnePanel:
    """The lower strip's queue rides on the panel a slideshow already wears.

    A slideshow covers the strip, and a slideshow is when the user keeps adding to it
    (locking a slide asks for an enhancement).  It used to float in the
    lower-left corner as a plate of its own, which is a second panel over the
    same image.
    """

    def test_what_is_in_flight_is_a_block_of_the_panel(self, qtbot):
        window = _dressed(qtbot)
        window.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)

        assert [line.key for line in window._hud_model().foot.lines] == ["j1"]

    def test_a_panel_over_an_idle_queue_grows_no_block(self, qtbot):
        window = _dressed(qtbot)
        window.set_queue([], 0)

        assert window._hud_model().foot is None

    def test_a_press_on_the_block_reaches_the_queue_through_the_panel(self, qtbot):
        """The Funestra hands the pointer on the block back in the block's own
        pixels; the slideshow places it against the rows it painted."""
        stopped = []
        window = _dressed(qtbot)
        window.set_queue([_inflight("j1", cancel=lambda: stopped.append("j1"),
                                       typical_seconds=30)], 0)
        panel_targets(window)
        x, y, width, height = window._queue_pointer.where(f"{CANCEL}|j1")

        window.press(f"foot_press|{x + width // 2}|{y + height // 2}")

        assert stopped == ["j1"]

    def test_a_click_landing_on_the_block_is_placed_against_its_rows(self, qtbot):
        """The whole way in: a press on the Funestra's window, over the block."""
        opened = []
        window = _dressed(qtbot)
        window.set_queue([_inflight("j1", reveal=lambda: opened.append("j1"),
                                       typical_seconds=30)], 0)
        foot = panel_targets(window).foot
        row = window._queue_pointer.where(f"{OPEN}|j1")
        rect = (foot[0] + row[0], foot[1] + row[1], row[2], row[3])

        _click_at(window, rect)

        assert opened == ["j1"]

    def test_the_wheel_over_the_block_scrolls_the_line(self, qtbot):
        window = _dressed(qtbot)
        window.set_queue([_inflight(f"j{index}", typical_seconds=30) for index in range(7)], 0)
        panel_targets(window)
        x, y, width, height = window._queue_pointer.where(f"{OPEN}|j2")

        window.press(f"foot_wheel|-1|{x + width // 2}|{y + height // 2}")

        assert [line.key for line in window._hud_model().foot.drawn][0] == "j1"


class TestTheRowOnTheOnePanel:
    """The track, the time and the volume ride on the one panel a slideshow wears,
    and they are the Funestra's own."""

    def _window(self, qtbot, items, **kw):
        return _dressed(qtbot, items, engine=FakeEngine(duration_ms=60_000), **kw)

    def test_a_slideshow_of_a_video_draws_the_scrubber_on_the_panel(self, qtbot):
        window = self._window(qtbot, [("scene one.mp4", "video")])

        assert panel_targets(window).row is not None

    def test_a_slideshow_of_an_image_keeps_the_scrubber_on_the_panel(self, qtbot):
        window = self._window(qtbot, [("scene one.png", "image")])
        window._pane._engine.showing_image = True

        assert panel_targets(window).row is not None

    def _press_the_middle_of_the_track(self, window):
        row = panel_targets(window).row
        x, y, _width, height = row.rect
        track_x0, track_x1 = row.track
        left, top, _bgra = _panel(window)
        window._pane.press(QPointF(left + x + (track_x0 + track_x1) // 2,
                                   top + y + height - TIMELINE_HEIGHT // 2))

    def test_pressing_the_middle_of_the_track_runs_the_video_to_its_middle(self, qtbot):
        window = self._window(qtbot, [("scene one.mp4", "video")])

        self._press_the_middle_of_the_track(window)

        assert window._pane._engine.position_ms == pytest.approx(30_000, abs=200)

    def test_pressing_the_middle_of_an_images_track_takes_its_time_back_to_the_middle(
            self, qtbot):
        window = self._window(qtbot, [("scene one.png", "image")])
        engine = window._pane._engine
        engine.showing_image = True
        engine.image_time = (7_000.0, 8_000.0)

        self._press_the_middle_of_the_track(window)

        assert engine.picture_seeks == [pytest.approx(4_000, abs=100)]

    def test_the_panel_follows_the_video_along_the_track(self, qtbot):
        window = self._window(qtbot, [("scene one.mp4", "video")])
        before = _panel(window)[2]

        window._pane._engine.position_ms = 30_000

        assert _panel(window)[2] is not before

    def _track_fill(self, window, fraction: float):
        """The color of the track *fraction* of the way along it."""
        row = panel_targets(window).row
        x, y, _width, height = row.rect
        track_x0, track_x1 = row.track
        bgra = _panel(window)[2]
        return tuple(bgra[y + height - TIMELINE_HEIGHT // 2,
                          x + round(track_x0 + (track_x1 - track_x0 - 1) * fraction)])

    def _slideshow_of(self, qtbot, tmp_path, name, actions=None):
        video = tmp_path / name
        video.write_bytes(b"")
        if actions is not None:
            video.with_suffix(".funscript").write_text(
                json.dumps({"actions": actions}), encoding="utf-8")
        return _dressed(qtbot, [(str(video), "video")], engine=FakeEngine(duration_ms=4_000))

    def test_the_track_is_colored_by_the_funscript_of_the_video_on_screen(
            self, qtbot, tmp_path):
        # Half as much motion in the first half of the clip as in the second.
        slow = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(0, 2_000, 500))]
        fast = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(2_000, 4_001, 125))]
        window = self._slideshow_of(qtbot, tmp_path, "scene one.mp4", slow + fast)
        window._pane.tick()  # the first beat measures the track, the second fills it

        assert self._track_fill(window, 0.25) != self._track_fill(window, 0.75)

    def test_a_video_with_no_funscript_gets_the_plain_track(self, qtbot, tmp_path):
        scripted = self._slideshow_of(qtbot, tmp_path, "scene one.mp4",
                                      [{"at": at, "pos": 100 * (index % 2)}
                                       for index, at in enumerate(range(0, 4_001, 125))])
        plain = self._slideshow_of(qtbot, tmp_path, "scene two.mp4")
        scripted._pane.tick()
        plain._pane.tick()

        assert self._track_fill(plain, 0.5) != self._track_fill(scripted, 0.5)


class TestASlideshowOverASessionsRegion:
    """A slideshow over a session's region in a window of this app's hands the
    transport to the session; what only it holds -- which version of the
    image is on screen, how fast its own Funestra plays -- it answers here."""

    @staticmethod
    def _slideshow_over_a_region(qtbot, tmp_path, items, **kw):
        window = _window(qtbot, items, **kw)
        window.resize(900, 700)
        with qtbot.waitExposed(window):
            window.show()
        window.wear_the_hud("portrait", dashboard_cmd_file=tmp_path / "dashboard_cmd.txt")
        window._pane.tick()
        return window

    def test_its_versions_button_steps_the_image_on_screen(self, qtbot, tmp_path):
        enhanced, original = str(tmp_path / "e1.png"), str(tmp_path / "src.png")
        window = self._slideshow_over_a_region(qtbot, tmp_path, [(enhanced, "image", "id-a")])
        window.slideshow.set_levels({enhanced: [(enhanced, "image", "Enhanced"), (original, "image", "Base")]})
        window._pane.tick()

        gestures.click(window._pane._window, button_on_screen(window, "portrait_cycle_version"))

        assert str(window._pane._engine.on_screen) == original

    def test_its_speed_buttons_change_how_fast_it_plays(self, qtbot, tmp_path):
        window = self._slideshow_over_a_region(qtbot, tmp_path, [("scene one.mp4", "video")])
        before = window._pane.playback.speed

        gestures.click(window._pane._window, button_on_screen(window, "portrait_speed_up"))

        assert window._pane.playback.speed > before

    def test_a_double_click_on_its_image_leaves_the_room_as_it_was(self, qtbot, tmp_path):
        asked = []
        window = self._slideshow_over_a_region(
            qtbot, tmp_path, [("scene one.png", "image")],
            actions=SlideshowActions(omnipause=lambda: asked.append("the room's pause")))
        window = window._pane._window

        gestures.double_click(window, QPoint(window.width() * 3 // 4, window.height() * 3 // 4))

        qtbot.waitUntil(lambda: not window.isVisible())
        assert asked == ["the room's pause"] * 2  # the first click's pause, taken back
