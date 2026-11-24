from __future__ import annotations

import json

import numpy as np
import pytest
from funestra.funestra_verbs import NEXT
from funestra.hud_controls import TRASH_ICON
from funestra.hud_corners import CORNER_PLUS_OVERLAY_ID
from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.hud_placement import HudCorner
from funestra.satellite_hud import MARGIN, parse_hud
from funestra.scrubber_bar import SCRUBBER_HEIGHT
from funestra.testing import FakeEngine
from PySide6.QtCore import QRect

from origenerator.gui.hud_queue import CANCEL, OPEN
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.on_its_own_funestra import HudWear
from origenerator.gui.osr2_controls import Osr2Controls
from origenerator.gui.slideshow_hud import HudPlacement, slideshow_hud_model
from origenerator.gui.slideshow_pace import MAX_S, MIN_S, STEP_S, SlideshowPace
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.slideshow import in_order
from origenerator.slideshow_buttons import answer
from tests.motion_doubles import FakeMotion
from tests.own_funestra_support import VIEWPORT, standalone
from tests.slideshow_hud_support import button_on_screen, hud_targets


def _inflight(key="j1", status="queued", cancel=None, **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "started_at", "typical_seconds")}
    return InFlightItem(key=key, caption="Alpha Workflow › a paper kite",
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), cancel=cancel, **kw)


def _window(items=(("scene one.png", "image"), ("scene two.png", "image")), **kw):
    return standalone(list(items), shuffle=in_order, **kw)


def _dressed(items=(("scene one.png", "image"), ("scene two.png", "image")),
             shape="portrait", **kw):
    wear = {name: kw.pop(name) for name in ("collapse", "open_in") if name in kw}
    window = _window(items, **kw)
    window.wear_the_hud(shape, HudWear(**wear))
    return window


def _published(window):
    return parse_hud(window.program.channel.hud_file.read_text(encoding="utf-8"))


def _hud(window):
    window.tick_the_funestra()
    return window.engine.overlays[HUD_OVERLAY_ID]


def _lit_order(model) -> list[str]:
    return [button.command for row in model.rows for button in row
            if button.command in ("portrait_shuffle", "portrait_latest") and button.lit]


def test_the_hud_lights_the_order_the_slideshow_is_playing_in(qtbot):
    for order_label, lit in (("Latest", ["portrait_latest"]),
                             ("Shuffle", ["portrait_shuffle"])):
        window = _window([("scene one.png", "image")], hud=HudFacts(order_label=order_label))

        assert _lit_order(slideshow_hud_model("portrait", window.slideshow)) == lit, order_label


def test_the_title_names_the_one_kind_of_item_kept_when_images_or_videos_are_left_out(qtbot):
    window = _window([("scene one.png", "image", "id-one"),
                      ("scene two.mp4", "video", "id-two")])
    every = slideshow_hud_model("portrait", window.slideshow).title

    window.slideshow.set_media((True, False))
    images_only = slideshow_hud_model("portrait", window.slideshow).title
    window.slideshow.set_media((False, True))
    videos_only = slideshow_hud_model("portrait", window.slideshow).title

    assert (images_only, videos_only) == (f"{every} · Images", f"{every} · Videos")


def test_the_hud_carries_what_is_being_made_of_the_item_on_screen(qtbot):
    window = _window([("scene one.png", "image", "id-one")])

    window.slideshow.note_enhancing({"id-one": "running"})

    assert slideshow_hud_model("portrait", window.slideshow).item_note == "Enhancing…"


def test_a_slideshow_wears_its_hud_the_moment_it_is_dressed(qtbot):
    window = _dressed()

    (x, y, _bgra) = _hud(window)

    assert (x, y) == (MARGIN, MARGIN)


def test_an_undressed_slideshow_wears_nothing(qtbot):
    window = _window()

    window.tick_the_funestra()

    assert HUD_OVERLAY_ID not in window.engine.overlays


def test_a_slideshow_whose_funestra_is_not_open_yet_still_has_its_hud_ready(qtbot):
    window = _window([("scene one.mp4", "video")])
    window.wear_the_hud("portrait")

    assert _published(window) is not None


def test_a_slideshow_with_nothing_to_map_has_no_hud(qtbot, monkeypatch):
    slideshow = _window().slideshow
    monkeypatch.setattr(slideshow, "hud_map", lambda: None)

    assert slideshow_hud_model("portrait", slideshow) is None


def test_the_hud_names_the_item_the_way_this_app_names_it(qtbot):
    window = _dressed([("scene one.png", "image", "id-one")], actions=SlideshowActions(
        name_of=lambda prompt_id: f"Example folder / {prompt_id}"))

    assert slideshow_hud_model("portrait", window.slideshow).item_name == "Example folder / id-one"


def test_a_hud_with_no_one_to_name_its_items_names_none(qtbot):
    window = _dressed([("scene one.png", "image", "id-one")])

    assert slideshow_hud_model("portrait", window.slideshow).item_name == ""


def test_each_item_in_the_nav_map_carries_the_name_the_gallery_gives_it(qtbot):
    window = _dressed([("scene one.png", "image", "id-one"), ("scene two.png", "image", "id-two")],
                      actions=SlideshowActions(name_of=lambda prompt_id: f"A3F {prompt_id}"))
    model = slideshow_hud_model("portrait", window.slideshow)

    cells = [model.corner, *model.seeds, *model.actions]

    assert {cell.name for cell in cells} <= {"A3F id-one", "A3F id-two"}
    assert model.corner.name == "A3F id-one"


class TestTheOneHudASlideshowWears:
    @staticmethod
    def _window(**kwargs):
        return _window(motion=FakeMotion(), **kwargs)

    def test_the_slideshow_floats_no_second_hud(self, qtbot):
        assert self._window().slideshow.findChildren(Osr2Controls) == [], (
            "the OSR2 is driven from Core's own OSR2 part; a second set of controls under the "
            "slideshow said the status twice, and the two disagreed")

    def _model(self):
        window = self._window()
        return slideshow_hud_model("portrait", window.slideshow, HudPlacement(drives_the_osr2=True))

    @pytest.mark.parametrize("hosted", [True, False])
    def test_no_slideshow_hud_carries_the_osr2_part(self, qtbot, hosted):
        window = self._window()

        model = slideshow_hud_model("portrait", window.slideshow,
                                    HudPlacement(hosted=hosted, drives_the_osr2=True))

        assert (model.osr2, model.osr2_rows, model.osr2_controls, model.drive,
                model.max_intensity) == ("", (), (), None, None), (
            "his decision: the slideshow's OSR2 part was redundant with the one in Core")

    def test_the_window_driving_the_device_is_the_funestra_skip_ahead_can_act_on(self, qtbot):
        def skip_ahead(model):
            return next(button for row in model.rows for button in row
                        if button.command == "portrait_funscript_jump")

        driving = skip_ahead(self._model())
        idle = skip_ahead(slideshow_hud_model("portrait", self._window().slideshow))

        assert driving.tooltip.endswith("(this slide has no funscript)")
        assert idle.tooltip.endswith(
            "(this Funestra doesn't have the OSR2 and this slide has no funscript)")

    def test_a_window_wearing_the_hud_over_the_device_lets_skip_ahead_act(self, qtbot):
        window = self._window()
        window.wear_the_hud("portrait")

        (jump,) = [button for row in _published(window).rows for button in row
                   if button.command == "portrait_funscript_jump"]

        assert jump.tooltip.endswith("(this slide has no funscript)")

    def test_the_pace_rides_with_the_rows_that_step_the_set(self, qtbot):
        posted = [button.command for row in self._model().rows for button in row]

        assert "portrait_clip_seconds_up" in posted
        assert "robot_hand_cycle_shape" not in posted

    def test_a_slideshow_on_a_sessions_funestra_carries_the_clip_seconds_too(self, qtbot):
        slideshow = self._window().slideshow

        rows = slideshow_hud_model("portrait", slideshow, HudPlacement()).rows

        assert ("portrait_clip_seconds_down", "4s", "portrait_clip_seconds_up") in [
            tuple(button.command or button.icon for button in row[1:4]) for row in rows]

    def test_the_transport_is_drawn_once(self, qtbot):
        posted = [button.command for row in self._model().rows for button in row]

        assert posted.count("portrait_prev") == 1
        assert "genau_prev_clip" not in posted
        assert "main_lock" not in posted
        assert "genau_trash_clip" not in posted

    def test_a_press_on_the_clip_seconds_pair_paces_the_slideshow(self, qtbot):
        window = self._window()
        window.wear_the_hud("portrait")

        window.press("portrait_clip_seconds_up")
        assert window.slideshow.dwell_s == 4 + STEP_S

        window.press("portrait_clip_seconds_down")
        assert window.slideshow.dwell_s == 4

    @pytest.mark.parametrize(("at", "press"), [(MAX_S, "portrait_clip_seconds_up"),
                                               (MIN_S, "portrait_clip_seconds_down")])
    def test_the_clip_seconds_pair_stops_at_its_ends(self, qtbot, at, press):
        window = self._window(pace=SlideshowPace(at))
        window.wear_the_hud("portrait")

        window.press(press)

        assert window.slideshow.dwell_s == at

    def test_a_press_on_the_transport_still_reaches_the_slideshow(self, qtbot):
        window = self._window()
        window.wear_the_hud("portrait")
        before = window.slideshow._set.playlist.index

        window.press("portrait_next")
        window.slideshow.tick()

        assert window.slideshow._set.playlist.index != before


class TestTheTrashOverAFavorite:
    @staticmethod
    def _window(favorites=frozenset({"id-one"})):
        library_favorites, unfavorited, deleted = set(favorites), [], []

        def unfavorite(prompt_id):
            unfavorited.append(prompt_id)
            library_favorites.discard(prompt_id)

        window = _dressed([("scene one.png", "image", "id-one"),
                           ("scene two.png", "image", "id-two")],
                          actions=SlideshowActions(is_favorite=library_favorites.__contains__,
                                                   unfavorite=unfavorite,
                                                   delete=deleted.append))
        return window, unfavorited, deleted

    @staticmethod
    def _model(window, hosted: bool):
        return (slideshow_hud_model("portrait", window.slideshow) if hosted
                else _published(window))

    @staticmethod
    def _trash(model):
        return next(button for row in model.rows for button in row
                    if button.command == "portrait_trash")

    @pytest.mark.parametrize("hosted", [True, False])
    def test_a_favorite_on_screen_wears_unfavorite_where_the_trash_stands(self, qtbot, hosted):
        window, _unfavorited, _deleted = self._window()

        model = self._model(window, hosted)

        assert model.facts.favorite
        assert self._trash(model).tooltip == "Unfavorite this slide and move on to the next"

    @pytest.mark.parametrize("hosted", [True, False])
    def test_an_item_that_is_no_favorite_keeps_the_trash(self, qtbot, hosted):
        window, _unfavorited, _deleted = self._window(favorites=frozenset())

        model = self._model(window, hosted)

        assert not model.facts.favorite
        assert (self._trash(model).icon, self._trash(model).danger) == (TRASH_ICON, True)

    def test_a_standalone_press_on_it_unfavorites_the_item_and_moves_on(self, qtbot):
        window, unfavorited, deleted = self._window()

        assert window.press("portrait_trash")

        assert (unfavorited, deleted) == (["id-one"], [])
        assert NEXT in window.program.sent
        assert not _published(window).facts.favorite

    def test_a_press_on_it_coming_back_from_a_session_unfavorites_and_moves_on(self, qtbot):
        window, unfavorited, deleted = self._window()

        assert answer(window.slideshow, "trash")

        assert (unfavorited, deleted) == (["id-one"], [])
        assert not slideshow_hud_model("portrait", window.slideshow).facts.favorite


def _middle_of(window, rect) -> tuple[int, int]:
    left, top, _bgra = _hud(window)
    return round(left + rect[0] + rect[2] / 2), round(top + rect[1] + rect[3] / 2)


def _point_at(window, at: tuple[int, int]) -> None:
    window.funestra.motion(*at, held=False, viewport=(window.width(), window.height()))
    window.tick_the_funestra()


def _the_pointer_leaves(window) -> None:
    window.funestra.leave()
    window.tick_the_funestra()


class TestWhereTheSlideshowsHudSits:
    @staticmethod
    def _window(**kw):
        return _dressed([("scene one.png", "image")], **kw)

    def test_the_hud_moves_to_the_corner_it_is_given(self, qtbot):
        window = self._window()

        window.set_hud_place(HudCorner.LOWER_RIGHT, False)

        x, y, bgra = _hud(window)
        assert x == window.width() - MARGIN - bgra.shape[1]
        assert y == window.height() - MARGIN - bgra.shape[0]

    def test_a_collapsed_hud_is_the_plus_button_alone(self, qtbot):
        window = self._window()
        wide = _hud(window)[2].shape[1]

        window.set_hud_place(HudCorner.UPPER_LEFT, True)

        assert _hud(window)[2].shape[1] < wide
        assert [button.command for _rect, button in hud_targets(window).buttons] == [
            "portrait_hud_restore"]

    def test_a_standalone_press_on_the_minus_collapses_it_here(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(collapse=collapsed.append)

        window.press("portrait_hud_minimize")

        assert collapsed == [True]

    def test_a_click_landing_on_the_minus_is_what_collapses_it(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(collapse=collapsed.append)

        window.click(button_on_screen(window, "portrait_hud_minimize"))

        assert collapsed == [True]

    def test_a_click_on_the_plus_asks_for_the_hud_back(self, qtbot):
        collapsed: list[bool] = []
        window = self._window(collapse=collapsed.append)
        window.set_hud_place(HudCorner.UPPER_LEFT, True)

        window.click(button_on_screen(window, "portrait_hud_restore"))

        assert collapsed == [False]

    def _a_plus_nobody_has_pointed_at(self):
        window = self._window()
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        return _hud(window)[2]

    def test_a_click_on_the_minus_leaves_the_plus_without_its_tooltip(self, qtbot):
        window = self._window(collapse=lambda minimized: window.set_hud_place(
            HudCorner.UPPER_LEFT, minimized))
        minus = button_on_screen(window, "portrait_hud_minimize")
        _point_at(window, minus)

        window.click(minus)

        assert np.array_equal(_hud(window)[2], self._a_plus_nobody_has_pointed_at())

    def test_the_plus_drops_its_tooltip_when_the_pointer_leaves_the_window(self, qtbot):
        window = self._window()
        window.set_hud_place(HudCorner.UPPER_LEFT, True)
        _point_at(window, button_on_screen(window, "portrait_hud_restore"))
        assert not np.array_equal(_hud(window)[2], self._a_plus_nobody_has_pointed_at())

        _the_pointer_leaves(window)

        assert np.array_equal(_hud(window)[2], self._a_plus_nobody_has_pointed_at())


class TestACornerTheHudIsNotIn:
    @staticmethod
    def _window(**kw):
        return TestWhereTheSlideshowsHudSits._window(**kw)

    def test_a_click_there_opens_the_hud_there(self, qtbot):
        opened: list[HudCorner] = []
        window = self._window(open_in=opened.append)
        _hud(window)

        window.click((window.width() - 3, window.height() - 3))

        assert opened == [HudCorner.LOWER_RIGHT]

    def test_the_pointer_there_shows_the_plus(self, qtbot):
        window = self._window()
        _hud(window)

        _point_at(window, (window.width() - 3, window.height() - 3))

        assert CORNER_PLUS_OVERLAY_ID in window.engine.overlays

    def test_the_pointer_leaving_the_window_takes_the_plus_down(self, qtbot):
        window = self._window()
        window.set_hud_place(HudCorner.LOWER_RIGHT, False)
        _hud(window)
        _point_at(window, (3, window.height() - 3))

        _the_pointer_leaves(window)

        assert CORNER_PLUS_OVERLAY_ID not in window.engine.overlays


def test_an_image_still_being_generated_is_drawn_on_the_map_without_its_frame_bytes(qtbot):
    window = _window([("scene one.png", "image", "id-one")])
    window.slideshow.note_generating("id-run", b"\x89PNG frame bytes")
    window.slideshow.slideshow_step(1)
    window.slideshow.tick()

    corner = slideshow_hud_model("portrait", window.slideshow).corner

    assert (corner.path, corner.thumb) == ("", "")


class _Core:
    def __init__(self, place, *, minimized: bool = False) -> None:
        self._place, self._minimized = place, minimized

    def isVisible(self) -> bool:
        return True

    def isMinimized(self) -> bool:
        return self._minimized

    def frameGeometry(self):
        return self._place


def _core_as(*, over: bool, minimized: bool = False, **dressed):
    place = QRect(0, 0, *VIEWPORT)
    core = _Core(place if over else place.translated(place.width() + 50, 0), minimized=minimized)
    window = _dressed(actions=SlideshowActions(core_window=lambda: core), **dressed)
    assert window.over_the_funestra.frameGeometry() == place
    window.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)
    return window


def _queue_keys(window) -> list[str]:
    return [line.key for line in window.queue_foot.section().lines]


class TestTheQueueOnTheOneHud:
    def test_what_is_in_flight_is_a_block_of_the_hud(self, qtbot):
        window = _dressed()
        window.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)

        assert _queue_keys(window) == ["j1"], (
            "a slideshow covers the lower strip, and a slideshow is when the user keeps adding "
            "to the queue, so what is in flight rides on the HUD the slideshow already wears "
            "rather than on a plate of its own over the same image")
        assert _published(window).foot is not None

    def test_a_slideshow_on_another_monitor_than_core_leaves_the_job_queue_to_core(
            self, qtbot):
        window = _core_as(over=False)

        assert window.queue_foot.section() is None
        assert _published(window).foot is None

    def test_a_slideshow_over_core_hangs_the_job_queue_at_its_foot(self, qtbot):
        window = _core_as(over=True)

        assert _queue_keys(window) == ["j1"], (
            "a slideshow covers Core's Job Queue just when the user keeps adding to it, so the HUD the "
            "slideshow already wears carries the queue")

    def test_a_slideshow_beside_a_minimized_core_hangs_the_job_queue_at_its_foot(
            self, qtbot):
        window = _core_as(over=False, minimized=True)

        assert _queue_keys(window) == ["j1"]

    def test_a_hud_over_an_idle_job_queue_leaves_it_off(self, qtbot):
        window = _dressed()
        window.set_queue([], 0)

        assert _published(window).foot is None, (
            "he wants the Job Queue gone rather than showing its empty line (2026-11-17)")

    def test_another_apps_backlog_alone_still_shows_the_job_queue(self, qtbot):
        window = _dressed()
        window.set_queue([], 3)

        assert _published(window).foot is not None

    def test_the_hud_keeps_one_size_as_jobs_come_and_go(self, qtbot):
        covering_core = _core_as(over=True)
        sizes = set()
        for items in ([_inflight("j1", job_kind="Image", typical_seconds=30)],
                      [_inflight(f"j{index}", typical_seconds=30) for index in range(7)]):
            covering_core.set_queue(items, 0)
            sizes.add(_hud(covering_core)[2].shape)

        assert len(sizes) == 1

    def test_core_coming_into_view_takes_only_the_job_queue_off_the_huds_bottom(self, qtbot):
        with_queue = _hud(_core_as(over=True))[2]
        without_queue = _hud(_core_as(over=False))[2]

        assert without_queue.shape[1] == with_queue.shape[1], (
            "he lets the HUD change size only by its bottom section appearing or disappearing "
            "(2026-11-16), so its width stays as it was")
        assert without_queue.shape[0] < with_queue.shape[0]
        assert (without_queue[:-8] == with_queue[:without_queue.shape[0] - 8]).all()

    def test_a_press_on_the_block_reaches_the_queue_through_the_hud(self, qtbot):
        stopped = []
        window = _dressed()
        window.set_queue([_inflight("j1", cancel=lambda: stopped.append("j1"),
                                    typical_seconds=30)], 0)
        x, y, width, height = window.queue_foot.pointer.where(f"{CANCEL}|j1")

        window.press(f"foot_press|{x + width // 2}|{y + height // 2}")

        assert stopped == ["j1"]

    def test_a_click_landing_on_the_block_is_placed_against_its_rows(self, qtbot):
        opened = []
        window = _dressed()
        window.set_queue([_inflight("j1", reveal=lambda: opened.append("j1"),
                                    typical_seconds=30)], 0)
        foot = hud_targets(window).foot
        row = window.queue_foot.pointer.where(f"{OPEN}|j1")

        window.click(_middle_of(window, (foot[0] + row[0], foot[1] + row[1], row[2], row[3])))

        assert opened == ["j1"]

    def test_the_wheel_over_the_block_scrolls_the_line(self, qtbot):
        window = _dressed()
        window.set_queue([_inflight(f"j{index}", typical_seconds=30) for index in range(7)], 0)
        x, y, width, height = window.queue_foot.pointer.where(f"{OPEN}|j2")

        window.press(f"foot_wheel|-1|{x + width // 2}|{y + height // 2}")

        assert next(line.key for line in window.queue_foot.section().drawn) == "j1"


class TestTheRowOnTheOneHud:
    @staticmethod
    def _window(items, **kw):
        return _dressed(items, engine=FakeEngine(duration_ms=60_000), **kw)

    def test_a_slideshow_of_a_video_draws_the_scrubber_on_the_hud(self, qtbot):
        window = self._window([("scene one.mp4", "video")])

        assert hud_targets(window).row is not None

    def test_a_slideshow_of_an_image_keeps_the_scrubber_on_the_hud(self, qtbot):
        window = self._window([("scene one.png", "image")])
        window.engine.showing_image = True

        assert hud_targets(window).row is not None

    @staticmethod
    def _press_the_middle_of_the_track(window):
        row = hud_targets(window).row
        x, y, _width, height = row.rect
        track_x0, track_x1 = row.track
        left, top, _bgra = _hud(window)
        window.funestra.press(left + x + (track_x0 + track_x1) // 2,
                              top + y + height - SCRUBBER_HEIGHT // 2,
                              viewport=(window.width(), window.height()))

    def test_pressing_the_middle_of_the_track_runs_the_video_to_its_middle(self, qtbot):
        window = self._window([("scene one.mp4", "video")])

        self._press_the_middle_of_the_track(window)

        assert window.engine.position_ms == pytest.approx(30_000, abs=200)

    def test_pressing_the_middle_of_an_images_track_takes_its_time_back_to_the_middle(
            self, qtbot):
        window = self._window([("scene one.png", "image")])
        engine = window.engine
        engine.showing_image = True
        engine.image_time = (7_000.0, 8_000.0)

        self._press_the_middle_of_the_track(window)

        assert engine.image_seeks == [pytest.approx(4_000, abs=100)]

    def test_the_hud_follows_the_video_along_the_track(self, qtbot):
        window = self._window([("scene one.mp4", "video")])
        before = _hud(window)[2]

        window.engine.position_ms = 30_000

        assert _hud(window)[2] is not before

    @staticmethod
    def _track_fill(window, fraction: float):
        row = hud_targets(window).row
        x, y, _width, height = row.rect
        track_x0, track_x1 = row.track
        bgra = _hud(window)[2]
        return tuple(bgra[y + height - SCRUBBER_HEIGHT // 2,
                          x + round(track_x0 + (track_x1 - track_x0 - 1) * fraction)])

    @staticmethod
    def _slideshow_of(tmp_path, name, actions=None):
        video = tmp_path / name
        video.write_bytes(b"")
        if actions is not None:
            video.with_suffix(".funscript").write_text(
                json.dumps({"actions": actions}), encoding="utf-8")
        return _dressed([(str(video), "video")], engine=FakeEngine(duration_ms=4_000))

    def test_the_track_is_colored_by_the_funscript_of_the_video_on_screen(
            self, qtbot, tmp_path):
        slow = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(0, 2_000, 500))]
        fast = [{"at": at, "pos": 100 * (index % 2)}
                for index, at in enumerate(range(2_000, 4_001, 125))]
        window = self._slideshow_of(tmp_path, "scene one.mp4", slow + fast)
        window.tick_the_funestra()

        assert self._track_fill(window, 0.25) != self._track_fill(window, 0.75)

    def test_a_video_with_no_funscript_gets_the_plain_track(self, qtbot, tmp_path):
        scripted = self._slideshow_of(tmp_path, "scene one.mp4",
                                      [{"at": at, "pos": 100 * (index % 2)}
                                       for index, at in enumerate(range(0, 4_001, 125))])
        plain = self._slideshow_of(tmp_path, "scene two.mp4")
        scripted.tick_the_funestra()
        plain.tick_the_funestra()

        assert self._track_fill(plain, 0.5) != self._track_fill(scripted, 0.5)


class TestTheButtonsOnTheHud:
    def test_its_versions_button_steps_the_image_on_screen(self, qtbot, tmp_path):
        enhanced, original = str(tmp_path / "e1.png"), str(tmp_path / "src.png")
        window = _dressed([(enhanced, "image", "id-a")])
        window.slideshow.set_versions(
            {enhanced: [(enhanced, "image", "Enhanced"), (original, "image", "Base")]})
        window.tick_the_funestra()

        window.click(button_on_screen(window, "portrait_cycle_version"))

        assert str(window.engine.on_screen) == original

    def test_its_speed_buttons_change_how_fast_it_plays(self, qtbot):
        window = _dressed([("scene one.mp4", "video")])
        window.tick_the_funestra()
        before = window.funestra.playback.speed

        window.click(button_on_screen(window, "portrait_speed_up"))

        assert window.funestra.playback.speed > before

    def test_a_double_click_on_its_image_leaves_the_room_as_it_was(self, qtbot):
        asked = []
        window = _dressed([("scene one.png", "image")], actions=SlideshowActions(
            omnipause=lambda: asked.append("the room's pause")))
        window.tick_the_funestra()

        window.double_click((window.width() * 3 // 4, window.height() * 3 // 4))

        assert not window.is_up()
        assert asked == ["the room's pause"] * 2
