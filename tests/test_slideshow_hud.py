from __future__ import annotations

import json

import numpy as np
import pytest
from funestra.funestra_verbs import NEXT
from funestra.hud_controls import TRASH_TOOLTIP
from funestra.hud_corners import CORNER_PLUS_OVERLAY_ID
from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.hud_placement import HudCorner
from funestra.satellite_hud import MARGIN
from funestra.scrubber_bar import SCRUBBER_HEIGHT
from funestra.testing import FakeEngine
from PySide6.QtCore import QEvent, QPoint, QPointF
from PySide6.QtWidgets import QApplication

from origenerator.gui.hud_queue import CANCEL, OPEN
from origenerator.gui.inflight import EMPTY_QUEUE_TEXT, InFlightItem, RunReading
from origenerator.gui.osr2_controls import Osr2Controls
from origenerator.gui.slideshow_hud import HudPlacement, slideshow_hud_model
from origenerator.gui.slideshow_pace import MAX_S, MIN_S, STEP_S, SlideshowPace
from origenerator.gui.slideshow_view import HudWear, SlideshowView, ViewShow, ViewWiring
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.slideshow import in_order
from origenerator.slideshow_buttons import answer
from tests import gestures
from tests.closed_windows import is_closed
from tests.motion_doubles import FakeMotion
from tests.slideshow_hud_support import button_on_screen, hud_targets


def _inflight(key="j1", status="queued", cancel=None, **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "started_at", "typical_seconds")}
    return InFlightItem(key=key, caption="Alpha Workflow \u203a a paper kite",
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), cancel=cancel, **kw)


def _window(qtbot, items=(("scene one.png", "image"), ("scene two.png", "image")), **kw):
    kw.setdefault("engine", FakeEngine())
    wiring = {name: kw.pop(name) for name in ("engine", "motion", "radio", "volume", "clock")
              if name in kw}
    window = SlideshowView(list(items), ViewShow(shuffle=in_order, **kw), ViewWiring(**wiring))
    qtbot.addWidget(window)
    return window


def _dressed(qtbot, items=(("scene one.png", "image"), ("scene two.png", "image")),
             shape="portrait", **kw):
    wear = {name: kw.pop(name) for name in ("dashboard_cmd_file", "collapse", "open_in")
            if name in kw}
    window = _window(qtbot, items, **kw)
    window.wear_the_hud(shape, HudWear(**wear))
    return window


def _hud(window):
    window._pane.tick()
    return window._pane._engine.overlays[HUD_OVERLAY_ID]


def _lit_order(model) -> list[str]:
    return [button.command for row in model.rows for button in row
            if button.command in ("portrait_shuffle", "portrait_latest") and button.lit]


def test_the_hud_lights_the_order_the_slideshow_is_playing_in(qtbot):
    for order_label, lit in (("Latest", ["portrait_latest"]),
                             ("Shuffle", ["portrait_shuffle"])):
        window = _window(qtbot, [("scene one.png", "image")], hud=HudFacts(order_label=order_label))

        assert _lit_order(slideshow_hud_model("portrait", window.slideshow)) == lit, order_label


def test_the_title_names_the_one_kind_of_item_kept_when_images_or_videos_are_left_out(qtbot):
    window = _window(qtbot, [("scene one.png", "image", "id-one"),
                             ("scene two.mp4", "video", "id-two")])
    every = slideshow_hud_model("portrait", window.slideshow).title

    window.slideshow.set_media((True, False))
    images_only = slideshow_hud_model("portrait", window.slideshow).title
    window.slideshow.set_media((False, True))
    videos_only = slideshow_hud_model("portrait", window.slideshow).title

    assert (images_only, videos_only) == (f"{every} · Images", f"{every} · Videos")


def test_the_hud_carries_what_is_being_made_of_the_item_on_screen(qtbot):
    window = _window(qtbot, [("scene one.png", "image", "id-one")])

    window.slideshow.note_enhancing({"id-one": "running"})

    assert slideshow_hud_model("portrait", window.slideshow).item_note == "Enhancing…"


def test_a_slideshow_wears_its_hud_the_moment_it_is_dressed(qtbot):
    window = _dressed(qtbot)

    (x, y, _bgra) = _hud(window)

    assert (x, y) == (MARGIN, MARGIN)


def test_an_undressed_slideshow_wears_nothing(qtbot):
    window = _window(qtbot)

    window._pane.tick()

    assert HUD_OVERLAY_ID not in window._pane._engine.overlays


def test_a_slideshow_whose_funestra_is_not_open_yet_still_has_its_hud_ready(qtbot):
    window = SlideshowView([("scene one.mp4", "video")], ViewShow(shuffle=in_order))
    qtbot.addWidget(window)
    window.wear_the_hud("portrait")

    assert window._hud_model() is not None


def test_a_slideshow_with_nothing_to_map_has_no_hud(qtbot, monkeypatch):
    slideshow = _window(qtbot).slideshow
    monkeypatch.setattr(slideshow, "hud_map", lambda: None)

    assert slideshow_hud_model("portrait", slideshow) is None


def test_the_hud_names_the_item_the_way_this_app_names_it(qtbot):
    window = _dressed(qtbot, [("scene one.png", "image", "id-one")], actions=SlideshowActions(
        name_of=lambda prompt_id: f"Example folder / {prompt_id}"))

    assert slideshow_hud_model("portrait", window.slideshow).item_name == "Example folder / id-one"


def test_a_hud_with_no_one_to_name_its_items_names_none(qtbot):
    window = _dressed(qtbot, [("scene one.png", "image", "id-one")])

    assert slideshow_hud_model("portrait", window.slideshow).item_name == ""


class TestTheOneHudASlideshowWears:
    @staticmethod
    def _window(qtbot, **kwargs):
        return _window(qtbot, motion=FakeMotion(), **kwargs)

    def test_the_slideshow_floats_no_second_hud(self, qtbot):
        assert self._window(qtbot).findChildren(Osr2Controls) == [], (
            "the OSR2 is driven from Core's own OSR2 part; a second set of controls under the "
            "slideshow said the status twice, and the two disagreed")

    def _model(self, qtbot):
        window = self._window(qtbot)
        return slideshow_hud_model("portrait", window.slideshow, HudPlacement(drives_the_osr2=True))

    @pytest.mark.parametrize("hosted", [True, False])
    def test_no_slideshow_hud_carries_the_osr2_part(self, qtbot, tmp_path, hosted):
        window = self._window(qtbot)
        window.wear_the_hud("portrait", HudWear(
            dashboard_cmd_file=tmp_path / "dashboard_cmd.txt" if hosted else None))

        model = window._hud_model()

        assert (model.osr2, model.osr2_rows, model.osr2_controls, model.drive,
                model.max_intensity) == ("", (), (), None, None), (
            "his decision: the slideshow's OSR2 part was redundant with the one in Core")

    def test_the_window_driving_the_device_is_the_funestra_skip_ahead_can_act_on(self, qtbot):
        def skip_ahead(model):
            return next(button for row in model.rows for button in row
                        if button.command == "portrait_funscript_jump")

        driving = skip_ahead(self._model(qtbot))
        idle = skip_ahead(slideshow_hud_model("portrait", self._window(qtbot).slideshow))

        assert driving.tooltip.endswith("(this slide has no funscript)")
        assert idle.tooltip.endswith(
            "(this Funestra doesn't have the OSR2 and this slide has no funscript)")

    def test_a_window_wearing_the_hud_over_the_device_lets_skip_ahead_act(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")

        (jump,) = [button for row in window._hud_model().rows for button in row
                   if button.command == "portrait_funscript_jump"]

        assert jump.tooltip.endswith("(this slide has no funscript)")

    def test_the_pace_rides_with_the_rows_that_step_the_set(self, qtbot):
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert "portrait_clip_seconds_up" in posted
        assert "robot_hand_cycle_shape" not in posted

    def test_a_slideshow_on_a_sessions_funestra_carries_the_clip_seconds_too(self, qtbot):
        slideshow = self._window(qtbot).slideshow

        rows = slideshow_hud_model("portrait", slideshow, HudPlacement()).rows

        assert ("portrait_clip_seconds_down", "4s", "portrait_clip_seconds_up") in [
            tuple(button.command or button.icon for button in row[1:4]) for row in rows]

    def test_the_transport_is_drawn_once(self, qtbot):
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert posted.count("portrait_prev") == 1
        assert "genau_prev_clip" not in posted
        assert "main_lock" not in posted
        assert "genau_trash_clip" not in posted

    def test_a_press_on_the_clip_seconds_pair_paces_the_slideshow(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")

        window.press("portrait_clip_seconds_up")
        assert window.slideshow.dwell_s == 4 + STEP_S

        window.press("portrait_clip_seconds_down")
        assert window.slideshow.dwell_s == 4

    @pytest.mark.parametrize(("at", "press"), [(MAX_S, "portrait_clip_seconds_up"),
                                               (MIN_S, "portrait_clip_seconds_down")])
    def test_the_clip_seconds_pair_stops_at_its_ends(self, qtbot, at, press):
        window = self._window(qtbot, pace=SlideshowPace(at))
        window.wear_the_hud("portrait")

        window.press(press)

        assert window.slideshow.dwell_s == at

    def test_a_hosted_side_verb_still_goes_out_on_the_sessions_channel(self, qtbot, tmp_path):
        window = self._window(qtbot)
        channel = tmp_path / "dashboard_cmd.txt"
        window.wear_the_hud("portrait", HudWear(dashboard_cmd_file=channel))

        window.press("portrait_next")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_next"]

    def test_a_press_on_the_transport_still_reaches_the_slideshow(self, qtbot):
        window = self._window(qtbot)
        window.wear_the_hud("portrait")
        before = window.slideshow._set.playlist.index

        window.press("portrait_next")
        window.slideshow.tick()

        assert window.slideshow._set.playlist.index != before

    def test_the_hud_is_rebuilt_on_its_resting_beat(self, qtbot):
        now = [0.0]
        window = self._window(qtbot, clock=lambda: now[0])
        window.wear_the_hud("portrait")
        window._motion.active = True
        first = window._hud_model()

        now[0] = 0.15
        assert window._hud_model() is first

        now[0] = 0.35
        assert window._hud_model() is not first


class TestTheTrashOverAFavorite:
    @staticmethod
    def _window(qtbot, tmp_path, *, hosted: bool, favorite_ids=frozenset({"id-one"})):
        unfavorited, deleted = [], []
        window = _dressed(qtbot, [("scene one.png", "image", "id-one"),
                                  ("scene two.png", "image", "id-two")],
                          hud=HudFacts(favorite_ids=set(favorite_ids)),
                          actions=SlideshowActions(unfavorite=unfavorited.append,
                                                   delete=deleted.append),
                          dashboard_cmd_file=tmp_path / "dashboard_cmd.txt" if hosted else None)
        return window, unfavorited, deleted

    @staticmethod
    def _trash(model):
        return next(button for row in model.rows for button in row
                    if button.command == "portrait_trash")

    @pytest.mark.parametrize("hosted", [True, False])
    def test_a_favorite_on_screen_wears_unfavorite_where_the_trash_stands(
            self, qtbot, tmp_path, hosted):
        window, _unfavorited, _deleted = self._window(qtbot, tmp_path, hosted=hosted)

        model = window._hud_model()

        assert model.facts.favorite
        assert self._trash(model).tooltip == "Unfavorite this slide and move on to the next"

    @pytest.mark.parametrize("hosted", [True, False])
    def test_an_item_that_is_no_favorite_keeps_the_trash(self, qtbot, tmp_path, hosted):
        window, _unfavorited, _deleted = self._window(qtbot, tmp_path, hosted=hosted,
                                                      favorite_ids=frozenset())

        model = window._hud_model()

        assert not model.facts.favorite
        assert self._trash(model).tooltip == TRASH_TOOLTIP

    def test_a_standalone_press_on_it_unfavorites_the_item_and_moves_on(
            self, qtbot, tmp_path, monkeypatch):
        window, unfavorited, deleted = self._window(qtbot, tmp_path, hosted=False)
        sent = []
        monkeypatch.setattr(window.slideshow.channel, "send", sent.append)

        assert window.press("portrait_trash")

        assert (unfavorited, deleted) == (["id-one"], [])
        assert NEXT in sent
        assert not window._hud_model().facts.favorite

    def test_a_hosted_press_on_it_comes_back_from_the_session_to_unfavorite_and_move_on(
            self, qtbot, tmp_path):
        window, unfavorited, deleted = self._window(qtbot, tmp_path, hosted=True)

        window.press("portrait_trash")
        (posted,) = (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split()
        assert answer(window.slideshow, posted.removeprefix("portrait_"))

        assert (unfavorited, deleted) == (["id-one"], [])
        assert not window._hud_model().facts.favorite


class TestWhereTheSlideshowsHudSits:
    @staticmethod
    def _window(qtbot, **kw):
        window = _dressed(qtbot, [("scene one.png", "image")], **kw)
        window.resize(1200, 900)
        window.show()
        return window

    def test_the_hud_moves_to_the_corner_it_is_given(self, qtbot):
        window = self._window(qtbot)

        window.set_hud_place(HudCorner.LOWER_RIGHT, False)

        x, y, bgra = _hud(window)
        width, height = window._pane._device_size()
        assert x == width - MARGIN - bgra.shape[1]
        assert y == height - MARGIN - bgra.shape[0]

    def test_a_collapsed_hud_is_the_plus_button_alone(self, qtbot):
        window = self._window(qtbot)
        wide = _hud(window)[2].shape[1]

        window.set_hud_place(HudCorner.UPPER_LEFT, True)

        assert _hud(window)[2].shape[1] < wide
        assert [button.command for _rect, button in hud_targets(window).buttons] == [
            "portrait_hud_restore"]

    def test_a_standalone_press_on_the_minus_collapses_it_here(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(qtbot, collapse=collapsed.append)

        window.press("portrait_hud_minimize")

        assert collapsed == [True]

    def test_a_click_landing_on_the_minus_is_what_collapses_it(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(qtbot, collapse=collapsed.append)
        (rect, _minus), = [(rect, button) for rect, button in hud_targets(window).buttons
                           if button.command.endswith("hud_minimize")]

        _click_at(window, rect)

        assert collapsed == [True]

    def test_a_click_on_the_plus_asks_for_the_hud_back(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(qtbot, collapse=collapsed.append)
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = hud_targets(window).buttons

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
        return _hud(window)[2]

    def test_a_click_on_the_minus_leaves_the_plus_without_its_tooltip(self, qtbot):
        window = self._window(qtbot, collapse=lambda minimized: window.set_hud_place(
            HudCorner.UPPER_LEFT, minimized))
        (rect, _minus), = [(rect, button) for rect, button in hud_targets(window).buttons
                           if button.command.endswith("hud_minimize")]
        _point_at(window, rect)

        _click_at(window, rect)

        assert np.array_equal(_hud(window)[2], self._a_plus_nobody_has_pointed_at(qtbot))

    def test_the_plus_drops_its_tooltip_when_the_pointer_leaves_the_window(self, qtbot):
        window = self._window(qtbot)
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = hud_targets(window).buttons
        _point_at(window, rect)
        assert not np.array_equal(_hud(window)[2], self._a_plus_nobody_has_pointed_at(qtbot))

        QApplication.sendEvent(window._pane._window, QEvent(QEvent.Type.Leave))

        assert np.array_equal(_hud(window)[2], self._a_plus_nobody_has_pointed_at(qtbot))


class TestACornerTheHudIsNotIn:
    @staticmethod
    def _window(qtbot, **kw):
        return TestWhereTheSlideshowsHudSits._window(qtbot, **kw)

    def test_a_click_there_opens_the_hud_there(self, qtbot):
        opened: list[HudCorner] = []
        window = self._window(qtbot, open_in=opened.append)
        _hud(window)
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
        _hud(window)
        width, height = window._pane._device_size()

        window._pane.motion(QPointF(width - 3, height - 3), held=False)
        window._pane.tick()

        assert CORNER_PLUS_OVERLAY_ID in window._pane._engine.overlays

    def test_the_pointer_leaving_the_window_takes_the_plus_down(self, qtbot):
        window = self._window(qtbot)
        window.set_hud_place(HudCorner.LOWER_RIGHT, False)
        _hud(window)
        _width, height = window._pane._device_size()
        window._pane.motion(QPointF(3, height - 3), held=False)
        window._pane.tick()

        QApplication.sendEvent(window._pane._window, QEvent(QEvent.Type.Leave))
        window._pane.tick()

        assert CORNER_PLUS_OVERLAY_ID not in window._pane._engine.overlays


def _middle_of(window, rect) -> QPointF:
    left, top, _bgra = _hud(window)
    return QPointF(left + rect[0] + rect[2] / 2, top + rect[1] + rect[3] / 2)


def _point_at(window, rect) -> None:
    window._pane.motion(_middle_of(window, rect), held=False)


def _click_at(window, rect) -> None:
    window._pane.press(_middle_of(window, rect))
    window._pane.release()


def test_an_image_still_being_generated_is_drawn_on_the_map_without_its_frame_bytes(qtbot):
    window = _window(qtbot, [("scene one.png", "image", "id-one")])
    window.slideshow.note_generating("id-run", b"\x89PNG frame bytes")
    window.slideshow.slideshow_step(1)
    window.slideshow.tick()

    corner = slideshow_hud_model("portrait", window.slideshow).corner

    assert (corner.path, corner.thumb) == ("", "")


class _Core:
    def __init__(self, place, *, screen=None, minimized: bool = False) -> None:
        self._place, self._screen, self._minimized = place, screen, minimized

    def isVisible(self) -> bool:
        return True

    def isMinimized(self) -> bool:
        return self._minimized

    def frameGeometry(self):
        return self._place

    def screen(self):
        return self._screen


def _core_as(qtbot, *, over: bool, minimized: bool = False, **dressed):
    core = {}
    window = _dressed(qtbot, actions=SlideshowActions(core_window=lambda: core["window"]),
                      **dressed)
    place = window.frameGeometry()
    core["window"] = _Core(place if over else place.translated(place.width() + 50, 0),
                           screen=window.screen(), minimized=minimized)
    window.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)
    return window


class TestTheQueueOnTheOneHud:
    def test_what_is_in_flight_is_a_block_of_the_hud(self, qtbot):
        window = _dressed(qtbot)
        window.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)

        assert [line.key for line in window._hud_model().foot.lines] == ["j1"], (
            "a slideshow covers the lower strip, and a slideshow is when the user keeps adding "
            "to the queue, so what is in flight rides on the HUD the slideshow already wears "
            "rather than on a plate of its own over the same image")

    def test_a_slideshow_on_another_monitor_than_core_leaves_the_job_queue_to_core(
            self, qtbot):
        window = _core_as(qtbot, over=False)

        assert window._hud_model().foot is None

    def test_a_slideshow_over_core_hangs_the_job_queue_at_its_foot(self, qtbot):
        window = _core_as(qtbot, over=True)

        assert [line.key for line in window._hud_model().foot.lines] == ["j1"], (
            "a slideshow covers Core's Job Queue just when the user keeps adding to it, so the HUD the "
            "slideshow already wears carries the queue")

    def test_a_slideshow_beside_a_minimized_core_hangs_the_job_queue_at_its_foot(
            self, qtbot):
        window = _core_as(qtbot, over=False, minimized=True)

        assert [line.key for line in window._hud_model().foot.lines] == ["j1"]

    def test_a_slideshow_over_a_sessions_region_leaves_the_job_queue_to_core_beside_it(
            self, qtbot, tmp_path):
        window = _core_as(qtbot, over=True, dashboard_cmd_file=tmp_path / "dashboard_cmd.txt")

        assert window._hud_model().foot is None

    def test_a_hud_over_an_idle_job_queue_shows_it_saying_so(self, qtbot):
        window = _dressed(qtbot)
        window.set_queue([], 0)

        foot = window._hud_model().foot
        assert foot.empty_note == EMPTY_QUEUE_TEXT

    def test_the_hud_keeps_one_size_as_jobs_come_and_go(self, qtbot):
        covering_core = _core_as(qtbot, over=True)
        sizes = set()
        for items in ([], [_inflight("j1", job_kind="Image", typical_seconds=30)],
                      [_inflight(f"j{index}", typical_seconds=30) for index in range(7)]):
            covering_core.set_queue(items, 0)
            sizes.add(_hud(covering_core)[2].shape)

        assert len(sizes) == 1

    def test_core_coming_into_view_takes_only_the_job_queue_off_the_huds_bottom(self, qtbot):
        with_queue = _hud(_core_as(qtbot, over=True))[2]
        without_queue = _hud(_core_as(qtbot, over=False))[2]

        assert without_queue.shape[1] == with_queue.shape[1], (
            "he lets the HUD change size only by its bottom section appearing or disappearing "
            "(2026-11-16), so its width stays as it was")
        assert without_queue.shape[0] < with_queue.shape[0]
        assert (without_queue[:-8] == with_queue[:without_queue.shape[0] - 8]).all()

    def test_a_press_on_the_block_reaches_the_queue_through_the_hud(self, qtbot):
        stopped = []
        window = _dressed(qtbot)
        window.set_queue([_inflight("j1", cancel=lambda: stopped.append("j1"),
                                       typical_seconds=30)], 0)
        hud_targets(window)
        x, y, width, height = window.queue_foot.pointer.where(f"{CANCEL}|j1")

        window.press(f"foot_press|{x + width // 2}|{y + height // 2}")

        assert stopped == ["j1"]

    def test_a_click_landing_on_the_block_is_placed_against_its_rows(self, qtbot):
        opened = []
        window = _dressed(qtbot)
        window.set_queue([_inflight("j1", reveal=lambda: opened.append("j1"),
                                       typical_seconds=30)], 0)
        foot = hud_targets(window).foot
        row = window.queue_foot.pointer.where(f"{OPEN}|j1")
        rect = (foot[0] + row[0], foot[1] + row[1], row[2], row[3])

        _click_at(window, rect)

        assert opened == ["j1"]

    def test_the_wheel_over_the_block_scrolls_the_line(self, qtbot):
        window = _dressed(qtbot)
        window.set_queue([_inflight(f"j{index}", typical_seconds=30) for index in range(7)], 0)
        hud_targets(window)
        x, y, width, height = window.queue_foot.pointer.where(f"{OPEN}|j2")

        window.press(f"foot_wheel|-1|{x + width // 2}|{y + height // 2}")

        assert next(line.key for line in window._hud_model().foot.drawn) == "j1"


class TestTheRowOnTheOneHud:
    def _window(self, qtbot, items, **kw):
        return _dressed(qtbot, items, engine=FakeEngine(duration_ms=60_000), **kw)

    def test_a_slideshow_of_a_video_draws_the_scrubber_on_the_hud(self, qtbot):
        window = self._window(qtbot, [("scene one.mp4", "video")])

        assert hud_targets(window).row is not None

    def test_a_slideshow_of_an_image_keeps_the_scrubber_on_the_hud(self, qtbot):
        window = self._window(qtbot, [("scene one.png", "image")])
        window._pane._engine.showing_image = True

        assert hud_targets(window).row is not None

    def _press_the_middle_of_the_track(self, window):
        row = hud_targets(window).row
        x, y, _width, height = row.rect
        track_x0, track_x1 = row.track
        left, top, _bgra = _hud(window)
        window._pane.press(QPointF(left + x + (track_x0 + track_x1) // 2,
                                   top + y + height - SCRUBBER_HEIGHT // 2))

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

        assert engine.image_seeks == [pytest.approx(4_000, abs=100)]

    def test_the_hud_follows_the_video_along_the_track(self, qtbot):
        window = self._window(qtbot, [("scene one.mp4", "video")])
        before = _hud(window)[2]

        window._pane._engine.position_ms = 30_000

        assert _hud(window)[2] is not before

    def _track_fill(self, window, fraction: float):
        row = hud_targets(window).row
        x, y, _width, height = row.rect
        track_x0, track_x1 = row.track
        bgra = _hud(window)[2]
        return tuple(bgra[y + height - SCRUBBER_HEIGHT // 2,
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
        slow = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(0, 2_000, 500))]
        fast = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(2_000, 4_001, 125))]
        window = self._slideshow_of(qtbot, tmp_path, "scene one.mp4", slow + fast)
        window._pane.tick()

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
    @staticmethod
    def _slideshow_over_a_region(qtbot, tmp_path, items, **kw):
        window = _window(qtbot, items, **kw)
        window.resize(900, 700)
        with qtbot.waitExposed(window):
            window.show()
        window.wear_the_hud("portrait", HudWear(dashboard_cmd_file=tmp_path / "dashboard_cmd.txt"))
        window._pane.tick()
        return window

    def test_its_versions_button_steps_the_image_on_screen(self, qtbot, tmp_path):
        enhanced, original = str(tmp_path / "e1.png"), str(tmp_path / "src.png")
        window = self._slideshow_over_a_region(qtbot, tmp_path, [(enhanced, "image", "id-a")])
        window.slideshow.set_versions({enhanced: [(enhanced, "image", "Enhanced"), (original, "image", "Base")]})
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

        qtbot.waitUntil(lambda: is_closed(window))
        assert asked == ["the room's pause"] * 2
