"""The one panel a show wears: what the show tells it to draw, where the
Funestra draws it, and what a press on it asks of the show."""
from __future__ import annotations

import json

import numpy as np
import pytest
from player_core.hud_corners import CORNER_PLUS_OVERLAY_ID
from player_core.hud_overlay import HUD_OVERLAY_ID
from player_core.hud_placement import HudCorner
from player_core.satellite_hud import MARGIN
from player_core.timeline import TIMELINE_HEIGHT, bar_track_x
from PyQt6.QtCore import QEvent, QPointF
from PyQt6.QtWidgets import QApplication

from origenerator.gui.hud_queue import CANCEL, OPEN
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.motion_panel import MotionPanel
from origenerator.gui.osr2_control import Osr2Control
from origenerator.gui.show_panel import show_hud_model
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_pace import MAX_S, MIN_S, STEP_S
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import in_order
from tests.funestra_fakes import FakePlayer
from tests.motion_doubles import FakeMotion
from tests.show_hud_support import panel_targets


def _inflight(key="j1", status="queued", cancel=None, **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "started_at", "typical_seconds")}
    return InFlightItem(key=key, caption="Alpha Workflow › a paper kite",
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), cancel=cancel, **kw)


def _show(qtbot, items=(("scene one.png", "image"), ("scene two.png", "image")), **kw):
    kw.setdefault("player", FakePlayer())
    show = SlideshowView(list(items), shuffle=in_order, **kw)
    qtbot.addWidget(show)
    return show


def _dressed(qtbot, items=(("scene one.png", "image"), ("scene two.png", "image")),
             side="portrait", **kw):
    wear = {name: kw.pop(name) for name in ("dashboard_cmd_file", "collapse", "open_in", "label_for")
            if name in kw}
    show = _show(qtbot, items, **kw)
    show.wear_the_hud(side, **wear)
    return show


def _panel(show):
    """The panel as the Funestra composited it: where, and the pixels."""
    show._pane.tick()
    return show._pane._player.overlays[HUD_OVERLAY_ID]


def _lit_order(model) -> list[str]:
    return [button.command for row in model.rows for button in row
            if button.command in ("portrait_shuffle", "portrait_latest") and button.lit]


def test_the_panel_lights_the_order_the_show_is_playing_in(qtbot):
    for order_label, lit in (("Latest", ["portrait_latest"]),
                             ("Shuffle", ["portrait_shuffle"]),
                             ("", [])):
        show = _show(qtbot, [("scene one.png", "image")], hud=HudFacts(order_label=order_label))

        assert _lit_order(show_hud_model("portrait", show)) == lit, order_label


def test_the_panel_carries_what_is_being_made_of_the_item_on_screen(qtbot):
    show = _show(qtbot, [("scene one.png", "image", "id-one")])

    show.note_enhancing({"id-one": "running"})

    assert show_hud_model("portrait", show).item_note == "Enhancing…"


def test_a_show_wears_its_panel_the_moment_it_is_dressed(qtbot):
    show = _dressed(qtbot)

    (x, y, _bgra) = _panel(show)

    assert (x, y) == (MARGIN, MARGIN)


def test_an_undressed_show_wears_nothing(qtbot):
    show = _show(qtbot)

    show._pane.tick()

    assert HUD_OVERLAY_ID not in show._pane._player.overlays


def test_a_show_whose_funestra_is_not_open_yet_still_has_its_panel_ready(qtbot):
    """The first beat comes before the pane has a window to hand the engine."""
    show = SlideshowView([("scene one.mp4", "video")], shuffle=in_order)
    qtbot.addWidget(show)
    show.wear_the_hud("portrait")

    assert show._hud_model() is not None


def test_the_panel_names_the_item_the_way_this_app_names_it(qtbot):
    show = _dressed(qtbot, [("scene one.png", "image", "id-one")],
                    label_for=lambda prompt_id: f"Example folder / {prompt_id}")

    assert show.item_label() == "Example folder / id-one"


class TestTheOnePanelAShowWears:
    """A show used to wear TWO panels: the players' HUD for the set, and Genau's
    whole console seated under it for the device.  Between them the status was
    said twice and disagreed -- "Looping seeds · Shuffle" over "Unlocked · 4s" --
    and prev, next, lock and trash were drawn on both.

    One panel now: the players' HUD, carrying the device's line and the drive
    readout out of the console's own code.
    """

    @staticmethod
    def _show(qtbot, **kwargs):
        motion = FakeMotion()
        return _show(qtbot, motion=motion, actions=ShowActions(osr2_control=Osr2Control(motion)),
                     **kwargs)

    def test_the_show_floats_no_second_panel(self, qtbot):
        assert self._show(qtbot).findChildren(MotionPanel) == []

    def _model(self, qtbot):
        show = self._show(qtbot)
        return show_hud_model("portrait", show, device=show.hud_device)

    def test_the_device_is_on_the_one_panel(self, qtbot):
        model = self._model(qtbot)

        assert model.osr2 != ""          # who has the device
        assert model.drive is not None   # and the motion it is being sent

    def test_the_osr2_line_carries_the_max_intensity_the_motion_is_held_to(self, qtbot):
        show = self._show(qtbot)
        show._motion.set_max_intensity(35)

        assert show_hud_model("portrait", show, device=show.hud_device).max_intensity == 35

    def test_a_show_that_is_not_driving_the_device_carries_no_max_intensity(self, qtbot):
        assert show_hud_model("portrait", self._show(qtbot)).max_intensity is None

    def test_the_pace_rides_with_the_rows_that_step_the_set(self, qtbot):
        """It sets how long an unheld slide stays up, which is about the set."""
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert "genau_clip_seconds_up" in posted
        assert "robot_hand_cycle_shape" not in posted

    def test_everything_that_aims_the_device_rides_with_the_device(self, qtbot):
        """Cruise, human-inspired, the waveform, the quarter nudge and the four
        control states act on the OSR2, so they sit in its own block at the foot
        of the panel rather than up among the rows that act on the set."""
        model = self._model(qtbot)
        aiming = [button.command for row in model.osr2_rows for button in row]

        assert "robot_hand_toggle_cruise" in aiming
        assert "robot_hand_toggle_learned" in aiming
        assert "robot_hand_cycle_shape" in aiming
        assert "quarter_button" in aiming
        assert "osr2_control_off" in aiming

    def test_the_transport_is_drawn_once(self, qtbot):
        """The console's own prev/next/lock/trash row is off it: the side's
        four are already there, and they act on the very same show."""
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert posted.count("portrait_prev") == 1
        assert "genau_prev_clip" not in posted
        assert "main_lock" not in posted
        assert "genau_weird_clip" not in posted

    def test_the_readout_the_show_composes_reaches_the_panel_the_funestra_draws(self, qtbot):
        show = self._show(qtbot)
        show.wear_the_hud("portrait")

        assert panel_targets(show).tracks

    def test_a_press_on_the_motion_row_reaches_the_motion(self, qtbot):
        show = self._show(qtbot)
        show.wear_the_hud("portrait")

        show.press("robot_hand_cycle_shape")

        assert "shape" in show._motion.calls

    def test_a_press_on_the_clip_seconds_pair_paces_the_show(self, qtbot):
        show = self._show(qtbot, image_dwell_ms=4000)
        show.wear_the_hud("portrait")

        show.press("genau_clip_seconds_up")
        assert show.dwell_s == 4 + STEP_S

        show.press("genau_clip_seconds_down")
        assert show.dwell_s == 4

    def test_the_clip_seconds_pair_stops_at_its_ends(self, qtbot):
        show = self._show(qtbot)
        show.wear_the_hud("portrait")

        show.set_dwell_s(MAX_S)
        show.press("genau_clip_seconds_up")
        assert show.dwell_s == MAX_S

        show.set_dwell_s(MIN_S)
        show.press("genau_clip_seconds_down")
        assert show.dwell_s == MIN_S

    def test_a_hosted_side_verb_still_goes_out_on_the_sessions_channel(self, qtbot, tmp_path):
        """The device rows are checked before the session's transport now, so a
        side verb that fell into them would be swallowed instead of posted."""
        show = self._show(qtbot)
        channel = tmp_path / "dashboard_cmd.txt"
        show.wear_the_hud("portrait", dashboard_cmd_file=channel)

        show.press("portrait_next")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_next"]

    def test_a_press_on_the_transport_still_reaches_the_show(self, qtbot):
        """The device rows sit beside the side's own band, not in place of it."""
        show = self._show(qtbot)
        show.wear_the_hud("portrait")
        before = show._playlist.index

        show.press("portrait_next")

        assert show._playlist.index != before


class TestWhereTheShowsPanelSits:
    """The room moves this panel round the corners of the show, and collapses it
    to a square with a plus on it."""

    @staticmethod
    def _show(qtbot, **kw):
        show = _dressed(qtbot, [("scene one.png", "image")], **kw)
        show.resize(900, 600)
        show.show()
        return show

    def test_the_panel_moves_to_the_corner_it_is_given(self, qtbot):
        show = self._show(qtbot)

        show.set_hud_place(HudCorner.LOWER_RIGHT, False)

        x, y, bgra = _panel(show)
        width, height = show._pane._device_size()
        assert x == width - MARGIN - bgra.shape[1]
        assert y == height - MARGIN - bgra.shape[0]

    def test_a_collapsed_panel_is_the_plus_button_alone(self, qtbot):
        show = self._show(qtbot)
        wide = _panel(show)[2].shape[1]

        show.set_hud_place(HudCorner.UPPER_LEFT, True)

        assert _panel(show)[2].shape[1] < wide
        assert [button.command for _rect, button in panel_targets(show).buttons] == [
            "portrait_hud_restore"]

    def test_a_standalone_press_on_the_minus_collapses_it_here(self, qtbot):
        collapsed: list[bool] = []
        show = self._show(qtbot, collapse=collapsed.append)

        show.press("portrait_hud_minimize")

        assert collapsed == [True]

    def test_a_click_landing_on_the_minus_is_what_collapses_it(self, qtbot):
        """The whole way in: a left button down on the square, where the panel
        drew it, and the panel is a plus by the time the button comes back up."""
        collapsed: list[bool] = []
        show = self._show(qtbot, collapse=collapsed.append)
        (rect, _minus), = [(rect, button) for rect, button in panel_targets(show).buttons
                           if button.command.endswith("hud_minimize")]

        _click_at(show, rect)

        assert collapsed == [True]

    def test_a_click_on_the_plus_asks_for_the_panel_back(self, qtbot):
        collapsed: list[bool] = []
        show = self._show(qtbot, collapse=collapsed.append)
        show.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = panel_targets(show).buttons

        _click_at(show, rect)

        assert collapsed == [False]

    def test_a_hosted_press_on_the_minus_goes_out_on_the_sessions_channel(
            self, qtbot, tmp_path):
        channel = tmp_path / "dashboard_cmd.txt"
        show = self._show(qtbot, dashboard_cmd_file=channel)

        show.press("portrait_hud_minimize")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_hud_minimize"]

    def _a_plus_nobody_has_pointed_at(self, qtbot):
        show = self._show(qtbot)
        show.set_hud_place(HudCorner.UPPER_LEFT, True)
        return _panel(show)[2]

    def test_a_click_on_the_minus_leaves_the_plus_without_its_tooltip(self, qtbot):
        show = self._show(qtbot, collapse=lambda minimized: show.set_hud_place(
            HudCorner.UPPER_LEFT, minimized))
        (rect, _minus), = [(rect, button) for rect, button in panel_targets(show).buttons
                           if button.command.endswith("hud_minimize")]
        _point_at(show, rect)

        _click_at(show, rect)

        assert np.array_equal(_panel(show)[2], self._a_plus_nobody_has_pointed_at(qtbot))

    def test_the_plus_drops_its_tooltip_when_the_pointer_leaves_the_window(self, qtbot):
        show = self._show(qtbot)
        show.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = panel_targets(show).buttons
        _point_at(show, rect)
        assert not np.array_equal(_panel(show)[2], self._a_plus_nobody_has_pointed_at(qtbot))

        QApplication.sendEvent(show._pane._window, QEvent(QEvent.Type.Leave))

        assert np.array_equal(_panel(show)[2], self._a_plus_nobody_has_pointed_at(qtbot))


class TestACornerThePanelIsNotIn:
    """A click in any other corner of the show sends its panel there, the way it
    does on every player, and the pointer in such a corner shows the plus that
    says so."""

    @staticmethod
    def _show(qtbot, **kw):
        return TestWhereTheShowsPanelSits._show(qtbot, **kw)

    def test_a_click_there_opens_the_panel_there(self, qtbot):
        opened: list[HudCorner] = []
        show = self._show(qtbot, open_in=opened.append)
        _panel(show)
        width, height = show._pane._device_size()

        show._pane.press(QPointF(width - 3, height - 3))
        show._pane.release()

        assert opened == [HudCorner.LOWER_RIGHT]

    def test_a_hosted_click_there_goes_out_on_the_sessions_channel(self, qtbot, tmp_path):
        channel = tmp_path / "dashboard_cmd.txt"
        show = self._show(qtbot, dashboard_cmd_file=channel)

        show.press("portrait_hud_restore_at|lower_left")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_hud_restore_at|lower_left"]

    def test_the_pointer_there_shows_the_plus(self, qtbot):
        show = self._show(qtbot)
        _panel(show)
        width, height = show._pane._device_size()

        show._pane.motion(QPointF(width - 3, height - 3), held=False)
        show._pane.tick()

        assert CORNER_PLUS_OVERLAY_ID in show._pane._player.overlays

    def test_the_pointer_leaving_the_window_takes_the_plus_down(self, qtbot):
        show = self._show(qtbot)
        show.set_hud_place(HudCorner.LOWER_RIGHT, False)
        _panel(show)
        _width, height = show._pane._device_size()
        show._pane.motion(QPointF(3, height - 3), held=False)
        show._pane.tick()

        QApplication.sendEvent(show._pane._window, QEvent(QEvent.Type.Leave))
        show._pane.tick()

        assert CORNER_PLUS_OVERLAY_ID not in show._pane._player.overlays


def _middle_of(show, rect) -> QPointF:
    left, top, _bgra = _panel(show)
    return QPointF(left + rect[0] + rect[2] / 2, top + rect[1] + rect[3] / 2)


def _point_at(show, rect) -> None:
    show._pane.motion(_middle_of(show, rect), held=False)


def _click_at(show, rect) -> None:
    """A left click at the middle of *rect*, in the panel's own pixels, where
    the Funestra composited the panel."""
    show._pane.press(_middle_of(show, rect))
    show._pane.release()


def test_a_picture_still_being_generated_is_drawn_on_the_map_without_its_frame_bytes(qtbot):
    show = _show(qtbot, [("scene one.png", "image", "id-one")])
    show.note_generating("id-run", b"\x89PNG frame bytes")
    show.step(1)

    corner = show_hud_model("portrait", show).corner

    assert (corner.path, corner.thumb) == ("", "")


class TestTheQueueOnTheOnePanel:
    """The lower strip's queue rides on the panel a show already wears.

    A show covers the strip, and a show is when the user keeps adding to it
    (locking a slide asks for an enhancement).  It used to float in the
    lower-left corner as a plate of its own, which is a second panel over the
    same picture.
    """

    def test_what_is_in_flight_is_a_block_of_the_panel(self, qtbot):
        show = _dressed(qtbot)
        show.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)

        assert [line.key for line in show._hud_model().foot.lines] == ["j1"]

    def test_a_panel_over_an_idle_queue_grows_no_block(self, qtbot):
        show = _dressed(qtbot)
        show.set_queue([], 0)

        assert show._hud_model().foot is None

    def test_a_press_on_the_block_reaches_the_queue_through_the_panel(self, qtbot):
        """The Funestra hands the pointer on the block back in the block's own
        pixels; the show places it against the rows it painted."""
        stopped = []
        show = _dressed(qtbot)
        show.set_queue([_inflight("j1", cancel=lambda: stopped.append("j1"),
                                  typical_seconds=30)], 0)
        panel_targets(show)
        x, y, width, height = show._queue_pointer.where(f"{CANCEL}|j1")

        show.press(f"foot_press|{x + width // 2}|{y + height // 2}")

        assert stopped == ["j1"]

    def test_a_click_landing_on_the_block_is_placed_against_its_rows(self, qtbot):
        """The whole way in: a press on the Funestra's window, over the block."""
        opened = []
        show = _dressed(qtbot)
        show.set_queue([_inflight("j1", reveal=lambda: opened.append("j1"),
                                  typical_seconds=30)], 0)
        foot = panel_targets(show).foot
        row = show._queue_pointer.where(f"{OPEN}|j1")
        rect = (foot[0] + row[0], foot[1] + row[1], row[2], row[3])

        _click_at(show, rect)

        assert opened == ["j1"]

    def test_the_wheel_over_the_block_scrolls_the_line(self, qtbot):
        show = _dressed(qtbot)
        show.set_queue([_inflight(f"j{index}", typical_seconds=30) for index in range(7)], 0)
        panel_targets(show)
        x, y, width, height = show._queue_pointer.where(f"{OPEN}|j2")

        show.press(f"foot_wheel|-1|{x + width // 2}|{y + height // 2}")

        assert [line.key for line in show._hud_model().foot.drawn][0] == "j1"


class TestTheRowOnTheOnePanel:
    """The track, the time and the volume ride on the one panel a show wears,
    and they are the Funestra's own."""

    def _show(self, qtbot, items, **kw):
        return _dressed(qtbot, items, player=FakePlayer(duration_ms=60_000), **kw)

    def test_a_show_of_a_video_draws_the_scrubber_on_the_panel(self, qtbot):
        show = self._show(qtbot, [("scene one.mp4", "video")])

        assert panel_targets(show).row is not None

    def test_a_show_of_a_picture_draws_no_scrubber(self, qtbot):
        show = self._show(qtbot, [("scene one.png", "image")])
        show._pane._player.showing_picture = True

        assert panel_targets(show).row is None

    def test_pressing_the_middle_of_the_track_runs_the_video_to_its_middle(self, qtbot):
        show = self._show(qtbot, [("scene one.mp4", "video")])
        x, y, width, height = panel_targets(show).row
        track_x0, track_x1 = bar_track_x(width)
        left, top, _bgra = _panel(show)

        show._pane.press(QPointF(left + x + (track_x0 + track_x1) // 2,
                                 top + y + height - TIMELINE_HEIGHT // 2))

        assert show._pane._player.position_ms == pytest.approx(30_000, abs=200)

    def test_the_panel_follows_the_video_along_the_track(self, qtbot):
        show = self._show(qtbot, [("scene one.mp4", "video")])
        before = _panel(show)[2]

        show._pane._player.position_ms = 30_000

        assert _panel(show)[2] is not before

    def _track_fill(self, show, fraction: float):
        """The color of the track *fraction* of the way along it."""
        x, y, width, height = panel_targets(show).row
        track_x0, track_x1 = bar_track_x(width)
        bgra = _panel(show)[2]
        return tuple(bgra[y + height - TIMELINE_HEIGHT // 2,
                          x + round(track_x0 + (track_x1 - track_x0 - 1) * fraction)])

    def _show_of(self, qtbot, tmp_path, name, actions=None):
        video = tmp_path / name
        video.write_bytes(b"")
        if actions is not None:
            video.with_suffix(".funscript").write_text(
                json.dumps({"actions": actions}), encoding="utf-8")
        return _dressed(qtbot, [(str(video), "video")], player=FakePlayer(duration_ms=4_000))

    def test_the_track_is_colored_by_the_funscript_of_the_video_on_screen(
            self, qtbot, tmp_path):
        # Half as much motion in the first half of the clip as in the second.
        slow = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(0, 2_000, 500))]
        fast = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(2_000, 4_001, 125))]
        show = self._show_of(qtbot, tmp_path, "scene one.mp4", slow + fast)
        show._pane.tick()  # the first beat measures the track, the second fills it

        assert self._track_fill(show, 0.25) != self._track_fill(show, 0.75)

    def test_a_video_with_no_funscript_gets_the_plain_track(self, qtbot, tmp_path):
        scripted = self._show_of(qtbot, tmp_path, "scene one.mp4",
                                 [{"at": at, "pos": 100 * (index % 2)}
                                  for index, at in enumerate(range(0, 4_001, 125))])
        plain = self._show_of(qtbot, tmp_path, "scene two.mp4")
        scripted._pane.tick()
        plain._pane.tick()

        assert self._track_fill(plain, 0.5) != self._track_fill(scripted, 0.5)
