from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

from funestra.hud_title import F_MODE_LABEL
from funestra.main_hud import OSR2_PARKED, OSR2_RETRACTED
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMovie, QPixmap
from PyQt6.QtWidgets import QLabel, QSplitter, QWidget

from origenerator import gallery
from origenerator.db import Database
from origenerator.fun_time_mode import FunTimeSession, Rect
from origenerator.gallery.collection import LATEST_KEY
from origenerator.gallery.shapes import SEPARATE, TOGETHER
from origenerator.generation_state import GenerationSource
from origenerator.gui.gallery_view import GalleryView, Shared
from origenerator.gui.generate_pane import GeneratePane
from origenerator.gui.generate_tab import GenerateTab
from origenerator.gui.message import INFO, WARNING
from origenerator.gui.pane_arrangement import TOC_OPENING_WIDTH
from origenerator.gui.panes import PaneSplitter
from origenerator.gui.slideshow_hud import slideshow_hud_model
from origenerator.gui.slideshow_pace import STEP_S as PACE_STEP_S
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.commands import CollectionCommand, SurfaceCommand
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import part_table
from tests.gallery_view_support import (
    MODE_VERBS,
    FakeDB,
    _FakeRadio,
    _image,
    _keys_are_the_gallerys,
    _press_escape,
    _reroll_client,
    _row,
    _SignalMotion,
    _will_move_on,
)
from tests.marked_words import words
from tests.slideshow_hud_support import (
    engine_of,
    funestra_of,
    hud_button_names,
    open_both_shapes,
    speaker_on_screen,
)


class _NoOsr2Word:
    def set_has_osr2(self, has_it):
        pass


def _session(tmp_path=None):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=None, paused_file=None, status_file=None,
        dashboard_cmd_file=None,
    )


def _as_items(rows):
    return [row if isinstance(row, tuple)
            else (f"{row['prompt_id']}.png", "image", row["prompt_id"],
                  row.get("thumbnail_path"))
            for row in rows]


def _a_gallery_showing(webp):
    class _Showing(GalleryView):
        def animated_preview(self, row):
            return str(webp)

    return _Showing


def _fun_time_view(qtbot, rows=()):
    view = GalleryView(FakeDB(list(rows)), fun_time=_session())
    qtbot.addWidget(view)
    return view


def _lit(model, action: str) -> bool:
    return next(button.lit for row in model.rows for button in row
                if button.command == action)


def test_fun_time_gallery_builds_no_shared_appliance_switches(qtbot):
    view = _fun_time_view(qtbot)
    assert view._buttons.radio is None, (
        "the room's sound is the Main Funestra's and its microphone Fun Time's: a second switch for "
        "either would be a switch over something this window does not hold")
    assert view._buttons.mic is None
    view.set_radio_enabled(True)
    assert view.radio_enabled() is False


def test_fun_time_gallery_builds_no_osr2_surface(qtbot):
    view = _fun_time_view(qtbot)
    assert view._osr2_motion is None, (
        "Fun Time's Main Funestra owns the OSR2 for the whole session, so a hosted Origenerator "
        "must offer no way to reach the device")
    assert view._osr2_driver is None
    assert view.osr2_control.isEnabled() is False
    assert view.osr2_control.state() == OSR2_PARKED
    assert view._osr2_controls is None


def test_fun_time_gallery_ignores_the_motion_keys(qtbot):
    view = _fun_time_view(qtbot)
    view.show()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_J,
                      Qt.KeyboardModifier.NoModifier)
    assert view.eventFilter(view, event) is False, (
        "Space and friends belong to Fun Time's own hotkeys while hosted; nothing here may "
        "swallow them")


def test_fun_time_gallery_does_not_put_the_standalone_osr2_state_on_but_hands_it_back_untouched(qtbot):
    view = _fun_time_view(qtbot)

    view.restore_osr2_state(OSR2_RETRACTED)

    assert view.osr2_control.state() == OSR2_PARKED, (
        "hosted, the device is the session's, so the state the standalone app was left in "
        "cannot be put on")
    assert view.osr2_state() == OSR2_RETRACTED, (
        "handed back untouched on the way out rather than saved over, since both runs keep the "
        "one state file")


def test_fun_time_gallery_stacks_the_generate_tabs_over_the_gallery_pane(qtbot):
    view = _fun_time_view(qtbot)
    stack = view._arrangement.stack
    assert isinstance(stack, QSplitter)
    assert stack.orientation() == Qt.Orientation.Vertical
    assert stack.count() == 3
    assert stack.widget(0).findChild(type(view._generate_pane)) is view._generate_pane
    assert stack.widget(1) is view._arrangement.panes
    assert view._arrangement.panes.count() == 2
    assert view._arrangement.panes.widget(1) is view._arrangement.folder_panes
    assert stack.widget(2) is view._queue


def test_fun_time_gallery_gives_the_lower_corner_to_the_queue(qtbot):
    view = _fun_time_view(qtbot)
    view.resize(600, 900)
    with qtbot.waitExposed(view):
        view.show()
    toc = view._arrangement.panes.widget(0)
    corner = view._queue.mapTo(view, view._queue.rect().bottomLeft())
    tree_foot = toc.mapTo(view, toc.rect().bottomLeft())
    assert tree_foot.y() < corner.y()
    assert view._queue.mapTo(view, view._queue.rect().topLeft()).x() <= (
        toc.mapTo(view, toc.rect().topLeft()).x()
    )


def test_fun_time_gallery_has_no_collapse_toggle_on_its_left_pane(qtbot):
    view = _fun_time_view(qtbot)
    assert not hasattr(view, "_toc_toggle")


def test_fun_time_gallery_opens_its_toc_at_the_width_a_window_of_its_own_starts_from(qtbot):
    view = _fun_time_view(qtbot)
    view.resize(900, 1400)
    with qtbot.waitExposed(view):
        view.show()

    assert view._arrangement.panes.widget(0).width() == TOC_OPENING_WIDTH


def test_fun_time_gallery_draws_neither_separate_nor_together_over_its_folder_list(qtbot):
    view = _fun_time_view(qtbot)
    with qtbot.waitExposed(view):
        view.show()

    assert not view._tree.separate_button.isVisible()
    assert not view._tree.together_button.isVisible()
    assert view._tree._splitter.mapTo(view._tree, QPoint()).y() == 0


def test_standalone_gallery_keeps_its_panes_side_by_side(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert view._arrangement.panes.count() == 2
    assert view._arrangement.panes.widget(0) is view._arrangement.left_column
    assert view._arrangement.panes.widget(1).findChild(type(view._generate_pane)) is view._generate_pane
    assert view._arrangement.folder_panes.count() == 2


def test_a_headset_gallery_keeps_the_standalone_panes_side_by_side(qtbot):
    view = GalleryView(FakeDB([]), fun_time=replace(
        _session(), frames_file=Path("frame.bin"), input_file=Path("input.txt")))
    qtbot.addWidget(view)

    assert view._arrangement.stack is None, (
        "the headset got the upright fold, which is the Random Favs Browser's rect asking for it")
    assert view._arrangement.panes.widget(0) is view._arrangement.left_column
    assert view._arrangement.folder_panes.count() == 2


def _row_of(item) -> dict:
    return {"prompt_id": item[2], "output_files": "[]", "thumbnail_path": item[3]}


def _items_of(rows) -> list:
    return [(row["thumbnail_path"], "image", row["prompt_id"], row["thumbnail_path"])
            for row in rows]


class _Slides(NamedTuple):
    name: str
    width: int
    height: int
    count: int = 1


def _open_slideshow(view, monkeypatch, tmp_path, slides):
    name, width, height, count = slides
    still = tmp_path / f"{name}.png"
    Image.new("RGB", (width, height)).save(still)
    items = [(str(still), "image", f"id-{name}-{n}", str(still))
             for n in range(count)]
    monkeypatch.setattr(view, "rows_to_play",
                        lambda: [{"prompt_id": item[2], "workflow_name": "sdxl_t2i",
                                  "params_json": json.dumps({"width": width, "height": height})}
                                 for item in items])
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: list(items))
    monkeypatch.setattr(view, "slideshow_subject", lambda: name)
    view._slideshows.start()


def test_slideshow_lands_in_the_region_matching_its_orientation(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    slideshow = view._slideshows._region_slideshows["portrait"]
    assert slideshow is not None
    assert slideshow.shown.isVisible()
    assert slideshow.shown.windowTitle() == "Origenerator Portrait"
    assert slideshow.shown.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert slideshow.shown.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    geo = slideshow.shown.geometry()
    assert (geo.width(), geo.height()) == (1440, 1870)
    qtbot.addWidget(slideshow.shown)


def test_both_regions_can_hold_a_slideshow_at_once(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("wide", 200, 100))
    portrait = view._slideshows._region_slideshows["portrait"]
    landscape = view._slideshows._region_slideshows["landscape"]
    assert portrait is not None, (
        "the point of sending slideshows to the satellite regions: the main window stays usable "
        "while up to two slideshows run")
    assert portrait.shown.isVisible()
    assert landscape is not None, (
        "the point of sending slideshows to the satellite regions: the main window stays usable "
        "while up to two slideshows run")
    assert landscape.shown.isVisible()
    assert portrait is not landscape
    for slideshow in (portrait, landscape):
        qtbot.addWidget(slideshow.shown)


def _both_regions_playing(view, qtbot, monkeypatch, tmp_path):
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("wide", 200, 100))
    slideshows = view._slideshows._region_slideshows
    for slideshow in slideshows.values():
        qtbot.addWidget(slideshow.shown)
    return slideshows["portrait"], slideshows["landscape"]


def test_each_regions_clip_seconds_step_without_the_others(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    portrait, landscape = _both_regions_playing(view, qtbot, monkeypatch, tmp_path)
    before = landscape.dwell_s

    portrait.step_dwell(2)

    assert portrait.dwell_s == before + 2 * PACE_STEP_S
    assert landscape.dwell_s == before


def test_a_regions_clip_seconds_open_at_standalones_and_leave_it_as_it_was(
        qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    view._pace.set_seconds(9)
    portrait, landscape = _both_regions_playing(view, qtbot, monkeypatch, tmp_path)

    portrait.step_dwell(1)
    landscape.step_dwell(-1)

    assert (portrait.dwell_s, landscape.dwell_s) == (10, 8)
    assert view._pace.seconds == 9


def test_the_next_slideshow_on_a_region_opens_at_the_clip_seconds_set_there(
        qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("first", 100, 200))
    first = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(first.shown)
    first.step_dwell(3)

    _open_slideshow(view, monkeypatch, tmp_path, _Slides("second", 90, 200))

    second = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(second.shown)
    assert second.dwell_s == first.dwell_s


def test_a_slideshow_in_a_session_begins_on_the_one_item_picked(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    last = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(last.shown)
    closed_on = last._set.playlist.current().prompt_id
    last.close()
    picked = next(f"id-tall-{n}" for n in range(3) if f"id-tall-{n}" != closed_on)
    monkeypatch.setattr(view, "selected_prompt_ids", lambda: [picked])

    view._slideshows.start()

    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    assert slideshow._set.playlist.current().prompt_id == picked


def test_esc_reaching_a_gallery_in_a_session_asks_the_session_for_omnipause(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _keys_are_the_gallerys(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("wide", 200, 100))
    slideshow = view._slideshows._region_slideshows["landscape"]
    qtbot.addWidget(slideshow.shown)

    assert _press_escape(view) is True

    channel = tmp_path / "dashboard_cmd.txt"
    assert channel.read_text(encoding="utf-8").split() == ["omnipause_toggle"]
    assert slideshow.is_showing()


def test_a_new_slideshow_replaces_the_regions_current_occupant(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("first", 100, 200))
    first = view._slideshows._region_slideshows["portrait"]
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("second", 90, 200))
    second = view._slideshows._region_slideshows["portrait"]
    assert second is not first
    assert not first.shown.isVisible()
    assert second.shown.isVisible()
    for slideshow in (first, second):
        qtbot.addWidget(slideshow.shown)


def test_a_preview_double_click_lands_its_slideshow_on_the_matching_region(qtbot, tmp_path):
    view = _fun_time_view(qtbot)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)

    slideshow = view._slideshows.open_on_preview((str(wide), "image"), None)

    qtbot.addWidget(slideshow.shown)
    assert view.region_slideshow("landscape") is slideshow
    assert slideshow.shown.windowTitle() == "Origenerator Landscape"


def test_a_region_slideshow_is_muted_like_every_satellite(qtbot, tmp_path):
    view = _fun_time_view(qtbot)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)

    slideshow = view._slideshows.open_on_preview((str(wide), "image"), None)

    qtbot.addWidget(slideshow.shown)
    assert engine_of(slideshow.shown).muted is True, (
        "on a satellite region the session's Main Funestra owns the room's audio, and the "
        "Satellites are silent by design")


def _a_region_slideshow_beside_the_gallerys_radio(qtbot, tmp_path):
    radio = _FakeRadio()
    view = GalleryView(FakeDB([]), fun_time=_session(), shared=Shared(radio=radio))
    qtbot.addWidget(view)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)
    slideshow = view._slideshows.open_on_preview((str(wide), "image"), None)
    qtbot.addWidget(slideshow.shown)
    engine_of(slideshow.shown)
    slideshow.shown._pane.tick()
    return view, slideshow, radio


def test_a_region_slideshow_plays_none_of_the_gallerys_radio(qtbot, tmp_path):
    _view, _slideshow, radio = _a_region_slideshow_beside_the_gallerys_radio(qtbot, tmp_path)

    assert radio.held == [], (
        "hosted, each Satellite Funestra plays the stations the session deals it")


def test_a_region_slideshows_volume_is_not_what_a_standing_one_opens_at(qtbot, tmp_path):
    view, slideshow, _radio = _a_region_slideshow_beside_the_gallerys_radio(qtbot, tmp_path)

    slideshow.shown._pane.press(QPointF(speaker_on_screen(slideshow.shown._pane)))

    assert view._slideshows.remembered()["volume"] is None


def test_a_presented_slideshow_takes_the_keyboard(qtbot):
    # Qt's offscreen platform cannot express real activation, so the contract is pinned at the seam: presenting raises and activates the window.

    view = _fun_time_view(qtbot)
    stub = QWidget()
    qtbot.addWidget(stub)
    calls: list[str] = []
    stub.raise_ = lambda: calls.append("raise")
    stub.activateWindow = lambda: calls.append("activate")
    stub.set_audio_muted = lambda muted: None
    stub.slideshow = SimpleNamespace(set_paused=lambda paused: None, transport=_NoOsr2Word())
    stub.wear_the_hud = lambda shape, wear: None
    view._slideshows._present_surface(stub, "portrait")
    assert calls == ["raise", "activate"], (
        "left unfocused, a slideshow's arrows land in Core and it reads as dead")


def test_a_preview_double_click_opens_the_slideshow_on_a_region(qtbot, tmp_path):
    view = _fun_time_view(qtbot)
    view.show()
    tab = view._generate_pane.current_generate_tab()
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)
    tab._viewport.show_media(str(wide), "image")

    qtbot.mouseDClick(tab._viewport, Qt.MouseButton.LeftButton,
                      pos=QPoint(tab._viewport.width() // 2,
                                 tab._viewport.height() // 2))

    slideshow = view.region_slideshow("landscape")
    assert slideshow is not None
    assert slideshow.shown.isVisible()
    geo = slideshow.shown.geometry()
    assert (geo.width(), geo.height()) == (1707, 1440)
    qtbot.addWidget(slideshow.shown)


def test_a_presented_slideshow_wears_the_funestras_own_hud(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    names = hud_button_names(slideshow.shown)
    assert [n for n in names if n in MODE_VERBS] == [
        "satellites_kino_activate", "origenerator_activate"]
    assert {"prev", "next", "lock", "trash"} <= set(names)
    assert "minimize" not in names, (
        "the window a Funestra's minimize parks is not this slideshow's")

    slideshow.shown.press("portrait_next")
    posted = (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split()
    assert posted == ["portrait_next"]


def test_a_click_on_a_hosted_slideshow_asks_the_room_for_omnipause(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    channel = tmp_path / "dashboard_cmd.txt"
    funestra_of(slideshow.shown)

    slideshow.shown._pane.press(QPointF(slideshow.shown._pane.width() / 2, slideshow.shown._pane.height() / 2))

    qtbot.waitUntil(lambda: channel.exists() and channel.read_text(
        encoding="utf-8").split() == ["omnipause_toggle"])
    assert slideshow.shown._paused is False


def test_a_spoken_pause_slideshow_asks_the_room_for_omnipause_and_play_slideshow_asks_it_back(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    qtbot.addWidget(view.region_slideshow("portrait").shown)
    channel = tmp_path / "dashboard_cmd.txt"

    assert view.run_spoken_command("portrait pause slideshow")
    assert channel.read_text(encoding="utf-8").split() == ["omnipause_toggle"]

    view.set_room_paused(True)
    assert view.run_spoken_command("portrait play slideshow")
    assert channel.read_text(encoding="utf-8").split() == ["omnipause_toggle", "omnipause_toggle"]


def _session_with_dashboard(tmp_path):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=None, paused_file=None, status_file=None,
        dashboard_cmd_file=tmp_path / "dashboard_cmd.txt",
    )


def _fox_library(tmp_path):
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    rows = [_image("g1", "a red fox", 50, 1), _image("g2", "a red fox", 50, 2),
            _image("g3", "a red fox at dawn", 50, 1), _image("g4", "a blue car", 30, 9),
            _row("v1", "wan22_i2v",
                 {"positive_prompt": "the fox runs", "noise_seed": 5,
                  "input_image": "sdxl_t2i_g1.png"},
                 "wan22_i2v_v1.mp4", video_actions=json.dumps(["alpha"]))]
    for row in rows:
        row["thumbnail_path"] = str(tall)
        if row["workflow_name"] == "sdxl_t2i":
            row["params_json"] = json.dumps(
                {**json.loads(row["params_json"]), "width": 720, "height": 1280})
    return rows


def _open_the_fox_slideshow(qtbot, view, monkeypatch, rows):
    view.refresh()
    monkeypatch.setattr(view, "rows_to_play", lambda: rows)
    monkeypatch.setattr(view._slideshows, "items_of", _as_items)
    monkeypatch.setattr(view, "slideshow_subject", lambda: "the fox folder")
    view._slideshows.start()
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    slideshow.show_item("g1.png")
    return slideshow


def test_the_huds_map_is_the_gamma_around_the_slide_on_screen(qtbot, tmp_path, monkeypatch):
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    slideshow = _open_the_fox_slideshow(qtbot, view, monkeypatch, rows)

    model = slideshow_hud_model("portrait", slideshow)

    assert model.corner.path == "g1.png"
    assert [cell.path for cell in model.seeds] == ["g2.png"]
    a_configuration, an_action = model.actions
    assert (a_configuration.path, an_action.path) == ("g3.png", "v1.png")
    assert (a_configuration.label, an_action.label) == ("", "alpha")
    assert model.current_action == "Source image"
    assert (model.seed_count, model.action_count) == (2, 3)
    assert model.playing == ("corner", 0)
    assert model.active_loop == ""
    assert model.title == "Unlocked · Shuffle"
    assert [(button.command, button.lit) for button in model.rows[0]] == [
        ("satellites_kino_activate", False), ("origenerator_activate", True)]
    assert model.locked is False

    slideshow.slideshow_toggle_lock()
    assert slideshow_hud_model("portrait", slideshow).locked is True


def test_the_map_re_homes_on_whatever_the_slideshow_moves_to(qtbot, tmp_path, monkeypatch):
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    slideshow = _open_the_fox_slideshow(qtbot, view, monkeypatch, rows)

    slideshow.show_item("g4.png")

    model = slideshow_hud_model("portrait", slideshow)
    assert model.corner.path == "g4.png"
    assert (model.seeds, model.actions) == ((), ())


def test_a_map_click_on_a_cell_the_set_never_held_plays_it_all_the_same(qtbot, tmp_path, monkeypatch):
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view, "rows_to_play", lambda: rows[:2])
    monkeypatch.setattr(view._slideshows, "items_of", _as_items)
    monkeypatch.setattr(view, "slideshow_subject", lambda: "the fox folder")
    view._slideshows.start()
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    slideshow.show_item("g1.png")

    slideshow.show_item("v1.png")

    assert slideshow._set.playlist.current()[2] == "v1"
    assert slideshow.hud_map().corner.path == "v1.png"


def test_a_hud_map_click_jumps_the_slideshow_to_that_item(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    still_b = tmp_path / "b.png"
    Image.new("RGB", (100, 200)).save(still_b)
    items = [(str(tmp_path / "tall.png"), "image", "id-a", str(tmp_path / "tall.png")),
             (str(still_b), "image", "id-b", str(still_b))]
    Image.new("RGB", (100, 200)).save(tmp_path / "tall.png")
    monkeypatch.setattr(view, "rows_to_play",
                        lambda: [{"prompt_id": item[2], "workflow_name": item[2],
                                  "thumbnail_path": item[3]} for item in items])
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: list(items))
    monkeypatch.setattr(view, "slideshow_subject", lambda: "a folder")
    view._slideshows.start()
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    slideshow.show_item(str(still_b), lock=True)

    assert slideshow._set.playlist.current()[0] == str(still_b)
    assert slideshow.locked


def test_a_latest_slideshow_plays_newest_first_not_shuffled(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_current_collection_key", lambda: LATEST_KEY)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    assert slideshow._set.playlist.order == [0, 1, 2]
    assert slideshow.hud_order_label == "Latest"


def test_f_mode_on_a_slideshow_narrows_the_set_to_the_favorites(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    slideshow.shown.press("portrait_fmode")

    assert slideshow.hud_favorites_filter is True
    assert slideshow.pass_size() == 1
    model = slideshow_hud_model("portrait", slideshow)
    assert _lit(model, "portrait_fmode")
    assert F_MODE_LABEL in model.title

    slideshow.shown.press("portrait_fmode")
    assert slideshow.pass_size() == 3
    slideshow._set.playlist.jump_to(1)
    assert slideshow.hud_is_favorite is True, (
        "every item of this fixture shares one file, so the slideshow is stepped to the "
        "favorite by its position and not by its path")
    slideshow._set.playlist.jump_to(0)
    assert slideshow.hud_is_favorite is False


def test_a_hosted_slideshow_keeps_up_with_its_own_folder(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    portrait = view.region_slideshow("portrait")
    qtbot.addWidget(portrait.shown)
    view._slideshows._live_slideshows = [(portrait, "folder-a")]
    landed = {"prompt_id": "new-1"}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: [landed] if key == "folder-a" else [])
    still = tmp_path / "new.png"
    Image.new("RGB", (100, 200)).save(still)
    monkeypatch.setattr(view._slideshows, "items_of",
                        lambda rows: [(str(still), "image", "new-1", str(still))])
    before = portrait.pass_size()

    view._slideshows.note_finished(landed)

    assert portrait.pass_size() == before + 1, (
        "each slideshow is fed from the folder it opened at: by the time a Populate item lands "
        "the Gallery pane has usually moved on, and the two regions may be playing different "
        "folders")


def test_a_landing_reaches_only_the_slideshow_playing_its_folder(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("wide", 200, 100))
    portrait, landscape = view.region_slideshow("portrait"), view.region_slideshow("landscape")
    for slideshow in (portrait, landscape):
        qtbot.addWidget(slideshow.shown)
    view._slideshows._live_slideshows = [(portrait, "folder-a"), (landscape, "folder-b")]
    landed = {"prompt_id": "new-1"}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: [landed] if key == "folder-b" else [])
    still = tmp_path / "new.png"
    Image.new("RGB", (200, 100)).save(still)
    monkeypatch.setattr(view._slideshows, "items_of",
                        lambda rows: [(str(still), "image", "new-1", str(still))])
    counts = [portrait.pass_size(), landscape.pass_size()]

    view._slideshows.note_finished(landed)

    assert portrait.pass_size() == counts[0]
    assert landscape.pass_size() == counts[1] + 1


def test_a_spoken_side_and_collection_plays_it_on_that_region(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    still = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(still)
    rows = [{"prompt_id": "new-1", "thumbnail_path": str(still)}]
    monkeypatch.setattr(view._library, "rows_at",
                        lambda key: rows if key == "__recents__::landscape" else [])
    monkeypatch.setattr(view._slideshows, "items_of",
                        lambda r: [(str(still), "image", row["prompt_id"], str(still))
                                   for row in r])

    view._voice.on_command(CollectionCommand("__recents__", "landscape"))

    slideshow = view.region_slideshow("landscape")
    assert slideshow is not None
    assert slideshow.shown.isVisible()
    assert slideshow.hud_order_label == "Latest"
    assert view.region_slideshow("portrait") is None
    qtbot.addWidget(slideshow.shown)


def test_the_maps_loop_button_loops_the_seed_row_and_the_next_press_ends_it(
        qtbot, tmp_path, monkeypatch):
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    slideshow = _open_the_fox_slideshow(qtbot, view, monkeypatch, rows)

    slideshow.shown.press("portrait_seed_loop")

    assert [item[2] for item in slideshow._set.playlist.items] == ["g1", "g2"]
    model = slideshow_hud_model("portrait", slideshow)
    assert model.active_loop == "seed"
    assert model.filter_query == model.current_action == "Source image", (
        "a seed loop lights the row it is playing, which is what that row's button says about "
        "it; an action filter would light every row it keeps")
    assert model.title.startswith("Looping seeds")
    assert "Unlocked" not in model.title, (
        "a set playing through holds nothing, so the line drops Unlocked, exactly as a looping "
        "Satellite's does")
    assert words(slideshow.shown._note) == "Looping seeds: 2"

    slideshow.shown.press("portrait_no_loop")

    assert slideshow.shown.isVisible()
    assert slideshow.pass_size() == 4, "one of g1 and the video made from it, and the other three"
    assert slideshow._set.playlist.current()[2] == "g1"
    dropped = slideshow_hud_model("portrait", slideshow)
    assert dropped.active_loop == ""
    assert "Looping" not in dropped.title


def test_more_seeds_widens_the_row_to_the_nearest_configurations_and_loops_it(
        qtbot, tmp_path, monkeypatch):
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    slideshow = _open_the_fox_slideshow(qtbot, view, monkeypatch, rows)

    slideshow.shown.press("portrait_more_seeds")

    model = slideshow_hud_model("portrait", slideshow)
    assert [cell.path for cell in model.seeds] == ["g2.png", "g3.png", "g4.png"]
    assert model.active_loop == "seed"
    assert [item[2] for item in slideshow._set.playlist.items] == ["g1", "g2", "g3", "g4"]
    assert words(slideshow.shown._note) == "More seeds"


def test_the_base_state_is_not_a_loop_and_says_so(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(4)]
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in base]
                                     if key == "__all__::portrait" else []))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)

    open_both_shapes(view)

    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    model = slideshow_hud_model("portrait", slideshow)
    assert model.active_loop == "", (
        "a region browsing its whole library is what a Satellite does with no loop on, so its "
        "HUD must read that way")
    assert model.title == "Unlocked · Shuffle"


def test_a_region_the_session_wants_never_stays_empty(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(4)]
    library = {"rows": []}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in library["rows"]]
                                     if key == "__all__::portrait" else []))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)

    open_both_shapes(view)
    assert view.region_slideshow("portrait") is None

    library["rows"] = base
    view.refresh()
    slideshow = view.region_slideshow("portrait")
    assert slideshow is not None, (
        "not a dead end: the session's open can arrive before the first refresh has read the "
        "library, the launch racing the boot, so a region asked for too early is filled on the "
        "next refresh")
    qtbot.addWidget(slideshow.shown)

    slideshow.close()
    later = view.region_slideshow("portrait")
    assert later is not None, (
        "the Funestra under a region is blacked for the whole mode, so a region left empty is a "
        "black rectangle, not a fallback")
    assert later is not slideshow
    qtbot.addWidget(later.shown)

    view.close_the_slideshows()
    assert view.region_slideshow("portrait") is None


def test_a_spoken_favorites_is_the_slideshows_own_f_mode(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)

    view._voice.on_command(CollectionCommand("__starred__", "portrait"))
    assert slideshow.hud_favorites_filter is True, (
        "on a Funestra the word favorites is F-mode, which the HUD has a button for; opening "
        "the collection as a fresh slideshow would answer it with something else entirely")
    assert slideshow.pass_size() == 1

    view._voice.on_command(CollectionCommand("__starred__", "portrait"))
    assert slideshow.hud_favorites_filter is False


def test_a_spoken_fix_names_which_region_it_means(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("wide", 200, 100))
    portrait, landscape = view.region_slideshow("portrait"), view.region_slideshow("landscape")
    for slideshow in (portrait, landscape):
        qtbot.addWidget(slideshow.shown)
    fixed = []
    monkeypatch.setattr(
        view, "fix_parts",
        lambda prompt_id, parts: (prompt_id,
                                  "fixing " + " ".join(p.name for p in parts),
                                  INFO))
    for slideshow in (portrait, landscape):
        monkeypatch.setattr(slideshow, "note_voice_run",
                            lambda pid, msg, *, kind, s=slideshow: fixed.append((s, pid, msg)))
    teeth = next(p for p in part_table() if p.name == "teeth")

    view._voice.on_command(SurfaceCommand([teeth], "landscape"))

    assert [entry[0] for entry in fixed] == [landscape], (
        "hosted, two slideshows run and neither is the active window, so the shape word is the "
        "only thing that says which image")
    assert fixed[0][2] == "fixing teeth"


def test_a_lock_on_a_hosted_slideshow_opens_its_generate_tab(qtbot, tmp_path, monkeypatch):
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    opened, navigated = [], []
    monkeypatch.setattr(view._generate_pane, "load_selection",
                        lambda row, images, **kw: opened.append(row["prompt_id"]))
    real_link = view.follow_link

    def follow(prompt_id):
        navigated.append(prompt_id)
        real_link(prompt_id)

    monkeypatch.setattr(view, "follow_link", follow)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    assert opened == ["id-tall-0"], (
        "the item held, not a sibling of it: every seed of one set of settings shares a "
        "settings folder, so a tab picked by folder came up on the wrong image")
    assert navigated == ["id-tall-0"], (
        "landing on the item is what opens its tab, so the test spies on the link rather than "
        "swallowing it")

    slideshow.slideshow_toggle_lock()
    assert len(opened) == 1


def test_a_lock_on_a_hosted_slideshow_asks_the_room_to_show_this_app_once(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([_image("id-tall-0", "a cat", 50, 1)]),
                       fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    slideshow.slideshow_toggle_lock()
    slideshow.tick()
    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    told = tmp_path / "dashboard_cmd.txt"
    lines = told.read_text(encoding="utf-8").split() if told.exists() else []
    assert lines.count("origenerator_activate") == 1


def test_a_standalone_slideshow_lock_opens_no_tab(qtbot, tmp_path, monkeypatch):
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    opened = []
    monkeypatch.setattr(view._generate_pane, "load_selection",
                        lambda row, images, **kw: opened.append(row["prompt_id"]))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    slideshow = view._slideshows.showing
    funestra_of(slideshow.shown)

    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    assert slideshow.hud_is_favorite
    assert opened == []


def test_closing_the_gallery_closes_the_slideshow_it_opened(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([_image("id-tall-0", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))
    slideshow = view._slideshows.showing

    view.close()

    assert not slideshow.shown.isVisible()
    assert view._slideshows._live_slideshows == []


def test_reset_on_a_slideshow_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    slideshow.shown.press("portrait_fmode")
    slideshow._set.playlist.jump_to(1)
    slideshow.slideshow_toggle_lock()
    assert slideshow.hud_favorites_filter is True

    slideshow.shown.press("portrait_reset")

    assert slideshow.hud_favorites_filter is False
    assert slideshow.pass_size() == 3
    assert slideshow._set.playlist.index == 0
    assert slideshow.locked is False


def _a_library_of_each_shape(view, tmp_path, monkeypatch) -> dict:
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    library = {
        "__all__::portrait": [{"prompt_id": "p-1", "thumbnail_path": str(tall)}],
        "__all__::landscape": [{"prompt_id": "l-1", "thumbnail_path": str(wide)}],
    }
    monkeypatch.setattr(view._slideshows, "rows_at", lambda key: library.get(key, []))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    return library


def test_the_regions_open_on_the_whole_library_of_their_own_shape(
        qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    library = _a_library_of_each_shape(view, tmp_path, monkeypatch)

    open_both_shapes(view)

    for shape in ("portrait", "landscape"):
        slideshow = view.region_slideshow(shape)
        assert slideshow is not None
        assert slideshow.shown.isVisible()
        assert slideshow.hud_order_label == "Shuffle"
        assert [str(item.path) for item in slideshow._set.playlist.items] == \
            [library[f"__all__::{shape}"][0]["thumbnail_path"]]
        qtbot.addWidget(slideshow.shown)
    assert sorted(where for _slideshow, where in view._slideshows._live_slideshows) == [
        "__all__::landscape", "__all__::portrait"]


def test_a_video_asked_for_in_origenerator_mode_is_made_while_both_regions_play(
        qtbot, tmp_path, monkeypatch):
    client = _reroll_client()
    view = GalleryView(Database(tmp_path / "test.db"), fun_time=_session(), client=client)
    qtbot.addWidget(view)
    _a_library_of_each_shape(view, tmp_path, monkeypatch)
    open_both_shapes(view)
    for shape in ("portrait", "landscape"):
        qtbot.addWidget(view.region_slideshow(shape).shown)

    i2v = WORKFLOW_REGISTRY["wan22_i2v"]
    video = view._jobs.start_prepared("k", i2v, i2v.default_params())

    assert [call.args[1] for call in client.submit_job.call_args_list] == [video]


def _mine_and_another_sites(tmp_path) -> list[dict]:
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    size = {"width": 720, "height": 1280}
    return [
        _row("mine", "sdxl_t2i", {"positive_prompt": "a", "seed": 1, **size},
             "sdxl_t2i_mine.png", thumbnail_path=str(tall)),
        _row("theirs", "outside picture:a-site", {"positive_prompt": "b", "seed": 2, **size},
             "theirs.png", thumbnail_path=str(tall), source=GenerationSource.OUTSIDE,
             workflow_version="outside"),
    ]


def test_a_regions_library_leaves_out_what_other_sites_made(qtbot, tmp_path):
    view = _fun_time_view(qtbot, _mine_and_another_sites(tmp_path))
    view.refresh()

    played = view._slideshows.rows_at("__all__::portrait")

    assert [row["prompt_id"] for row in played] == ["mine"]


def test_a_regions_latest_leaves_out_what_other_sites_made(qtbot, tmp_path):
    view = _fun_time_view(qtbot, _mine_and_another_sites(tmp_path))
    view.refresh()

    played = view._slideshows.rows_at(f"{LATEST_KEY}::portrait")

    assert [row["prompt_id"] for row in played] == ["mine"]


def test_the_gallery_goes_on_showing_what_other_sites_made(qtbot, tmp_path):
    view = _fun_time_view(qtbot, _mine_and_another_sites(tmp_path))
    view.refresh()

    latest = view._gallery_pane.rows_for_collection(f"{LATEST_KEY}::portrait")
    everything = gallery.rows_under(view.group_for_key("__all__::portrait"))

    assert sorted(row["prompt_id"] for row in latest) == ["mine", "theirs"]
    assert sorted(row["prompt_id"] for row in everything) == ["mine", "theirs"]


def test_a_key_can_name_a_place_and_a_shape_at_once(qtbot, tmp_path):
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    rows = [
        _row("p-1", "sdxl_t2i", {"positive_prompt": "a", "seed": 1,
                                  "width": 720, "height": 1280},
             "sdxl_t2i_p1.png", thumbnail_path=str(tall)),
        _row("l-1", "sdxl_t2i", {"positive_prompt": "b", "seed": 2,
                                  "width": 1280, "height": 720},
             "sdxl_t2i_l1.png", thumbnail_path=str(wide)),
    ]
    view = _fun_time_view(qtbot, rows)
    view.refresh()

    portrait = [row["prompt_id"] for row in view._slideshows.rows_at("__all__::portrait")]
    landscape = [row["prompt_id"] for row in view._slideshows.rows_at("__all__::landscape")]
    assert portrait == ["p-1"]
    assert landscape == ["l-1"]
    assert set(portrait) | set(landscape) == {"p-1", "l-1"}


def test_reset_puts_a_region_back_on_the_library_not_on_its_own_folder(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(5)]
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in base]
                                     if key == "__all__::portrait" else []))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("folder", 100, 200, count=2))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    assert slideshow.pass_size() == 2
    view._slideshows._live_slideshows = [(slideshow, "folder-a")]

    slideshow.shown.press("portrait_reset")

    assert slideshow.pass_size() == len(base)
    assert slideshow.hud_order_label == "Shuffle"
    assert [where for _slideshow, where in view._slideshows._live_slideshows] == ["__all__::portrait"]


def test_latest_on_a_hosted_slideshows_hud_plays_its_side_newest_first(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    newest_first = [(str(tall), "image", f"new-{n}", str(tall)) for n in range(4)]
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in newest_first]
                                     if key == "__recents__::portrait" else []))
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("folder", 100, 200, count=2))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)

    slideshow.shown.press("portrait_latest")

    playlist = slideshow._set.playlist
    assert [playlist.items[index][2] for index in playlist.order] == [
        "new-0", "new-1", "new-2", "new-3"]
    assert _lit(slideshow_hud_model("portrait", slideshow), "portrait_latest")
    assert not _lit(slideshow_hud_model("portrait", slideshow), "portrait_shuffle")
    assert not (tmp_path / "dashboard_cmd.txt").exists()


def test_reset_stays_local_when_a_slideshow_holds_no_region(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    slideshow._set.playlist.jump_to(1)
    slideshow.slideshow_toggle_lock()

    slideshow.slideshow_reset()

    assert slideshow._set.playlist.index == 0
    assert slideshow.locked is False
    assert slideshow.pass_size() == 3


def _a_looping_video(tmp_path):
    webp = tmp_path / "loop.webp"
    frames = [Image.new("RGB", (64, 32), shade) for shade in ((10, 10, 10), (220, 220, 220))]
    frames[0].save(webp, save_all=True, append_images=frames[1:], duration=100, loop=0)
    still = tmp_path / "still.png"
    Image.new("RGB", (64, 32)).save(still)
    rows = [_row("v-1", "wan22_i2v",
                 {"positive_prompt": "a clip", "seed": 1,
                  "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors"},
                 "wan22_i2v_v1.mp4", thumbnail_path=str(still))]
    return rows, webp


def _moving_thumbnails(view):
    return [label for label in view.findChildren(QLabel)
            if label.movie() is not None
            and label.movie().state() == QMovie.MovieState.Running]


def test_omnipause_leaves_nothing_moving_anywhere_in_the_window(qtbot, tmp_path):
    rows, webp = _a_looping_video(tmp_path)
    view = _a_gallery_showing(webp)(FakeDB(rows), fun_time=_session())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._tree_view.leaf_by_id["v-1"])
    assert _moving_thumbnails(view), "nothing was moving, so the sweep would prove nothing"

    view.set_room_paused(True)

    assert _moving_thumbnails(view) == [], (
        "swept rather than listed: a list of what moves has been wrong before, and a sweep "
        "cannot miss the next thing that is added")

    view.set_room_paused(False)
    assert _moving_thumbnails(view)


def test_omnipause_reaches_a_slideshow_the_region_map_does_not_answer_for(
        qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows._live_slideshows[0][0]
    qtbot.addWidget(slideshow.shown)
    monkeypatch.setattr(view, "region_slideshow", lambda shape: None)

    view.set_room_paused(True)

    assert slideshow.shown._paused is True, (
        "the freeze goes out to every slideshow this window has open, not only to the ones the "
        "region map calls visible")
    assert not _will_move_on(slideshow)


def test_a_frozen_slideshow_does_not_walk_past_an_unplayable_video(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    view.set_room_paused(True)
    at = slideshow._set.playlist.index

    engine_of(slideshow.shown).idle = True
    slideshow.shown._pane.tick()

    assert slideshow._set.playlist.index == at


def test_a_portrait_image_stands_beside_the_form_when_hosted(qtbot):
    tab = GenerateTab(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tab)
    assert tab._media_split.orientation() == Qt.Orientation.Vertical

    tab._viewport._pixmap = QPixmap(400, 900)
    tab._reflow_for_the_media()

    assert tab._media_split.orientation() == Qt.Orientation.Horizontal, (
        "stacked in the Random Favs Browser's upright region, a portrait preview pushes every prompt "
        "field off the foot")
    assert tab._media_split.indexOf(tab._settings_pane) == 0, (
        "settings left, image right: the order they are read in")
    assert tab._media_split.indexOf(tab._viewport_pane) == 1


def test_a_landscape_image_stays_stacked_when_hosted(qtbot):
    tab = GenerateTab(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tab)

    tab._viewport._pixmap = QPixmap(1200, 700)
    tab._reflow_for_the_media()

    assert tab._media_split.orientation() == Qt.Orientation.Vertical, (
        "a wide image beside a form gets a column too narrow to show it, and the form loses "
        "the width its prompt fields need")
    assert tab._media_split.indexOf(tab._viewport_pane) == 0


def test_a_panel_taken_into_a_session_stands_its_portrait_image_beside_the_form(qtbot):
    tab = GenerateTab(None, FakeDB([]))
    qtbot.addWidget(tab)
    tab._viewport._pixmap = QPixmap(400, 900)
    tab._reflow_for_the_media()

    tab.become_hosted(_session())

    assert tab._media_split.orientation() == Qt.Orientation.Horizontal
    assert tab._media_split.indexOf(tab._settings_pane) == 0


def test_a_panel_handed_back_from_a_session_stacks_its_portrait_image_over_the_form(qtbot):
    tab = GenerateTab(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tab)
    tab._viewport._pixmap = QPixmap(400, 900)
    tab._reflow_for_the_media()

    tab.become_standalone()
    tab.refresh_media_layout()

    assert tab._media_split.orientation() == Qt.Orientation.Vertical
    assert tab._media_split.indexOf(tab._viewport_pane) == 0


def test_an_image_back_from_beside_the_form_takes_the_larger_share_again(qtbot):
    tab = GenerateTab(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tab)
    tab.resize(600, 1000)
    tab._viewport._pixmap = QPixmap(1200, 700)
    tab.show()
    qtbot.wait(1)

    tab._viewport._pixmap = QPixmap(400, 900)
    tab._reflow_for_the_media()
    tab._viewport._pixmap = QPixmap(1200, 700)
    tab._reflow_for_the_media()
    qtbot.wait(1)

    media, settings = tab._media_split.sizes()
    assert media > settings, (
        "a landscape image after a portrait one in the same tab came back with a third of the "
        "column, where a fresh tab gives it two thirds")


def test_tabs_taken_into_a_session_lay_out_the_tabs_they_have_and_the_ones_opened_after(qtbot):
    tabs = GeneratePane(None, FakeDB([]))
    qtbot.addWidget(tabs)
    first = tabs.currentWidget()
    first._viewport._pixmap = QPixmap(400, 900)

    tabs.become_hosted(_session())
    later = tabs._add_subtab()
    later._viewport._pixmap = QPixmap(400, 900)
    later.refresh_media_layout()

    assert first._media_split.orientation() == Qt.Orientation.Horizontal
    assert later._media_split.orientation() == Qt.Orientation.Horizontal


def test_tabs_handed_back_from_a_session_stack_the_tabs_they_have_and_the_ones_opened_after(qtbot):
    tabs = GeneratePane(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tabs)
    first = tabs.currentWidget()
    first._viewport._pixmap = QPixmap(400, 900)
    first.refresh_media_layout()

    tabs.become_standalone()
    later = tabs._add_subtab()
    later._viewport._pixmap = QPixmap(400, 900)
    later.refresh_media_layout()

    assert first._media_split.orientation() == Qt.Orientation.Vertical
    assert later._media_split.orientation() == Qt.Orientation.Vertical


def test_a_gallery_taken_into_a_session_stands_as_a_hosted_one_is_built(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    view.become_hosted(_session())

    built = _fun_time_view(qtbot)
    assert (view._buttons.radio, view._buttons.mic) == (None, None)
    assert (view._osr2_motion, view._osr2_driver, view._osr2_controls) == (None, None, None)
    assert not view.osr2_control.isEnabled()
    assert not built.osr2_control.isEnabled()
    assert view._motion_pane.isHidden()
    stack = view._arrangement.stack
    assert stack.orientation() == Qt.Orientation.Vertical
    assert stack.count() == built._arrangement.stack.count() == 3
    assert stack.widget(0).findChild(type(view._generate_pane)) is view._generate_pane
    assert stack.widget(1) is view._arrangement.panes
    assert stack.widget(2) is view._queue
    assert view._arrangement.panes.count() == built._arrangement.panes.count()
    assert view._arrangement.panes.widget(1) is view._arrangement.folder_panes
    assert view._arrangement.folder_panes.count() == built._arrangement.folder_panes.count()


def test_a_gallery_driving_the_device_lets_go_of_it_as_a_session_takes_it_over(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), shared=Shared(osr2_motion=motion))
    qtbot.addWidget(view)
    view.osr2_control.setChecked(True)
    assert motion.active

    view.become_hosted(_session())

    assert not motion.active
    assert motion.calls[-1] == ("stop",)


def test_a_gallery_a_session_never_took_over_stands_off_the_device_all_the_same(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), shared=Shared(osr2_motion=motion))
    qtbot.addWidget(view)
    view.osr2_control.setChecked(True)

    view.osr2_control.the_session_has_it(True)

    assert not motion.active, (
        "the takeover can miss, and a window that kept its switch keeps streaming into the one "
        "device the session is driving")
    assert not view.osr2_control.isEnabled()
    view.toggle_osr2_drive()
    assert not motion.active


def test_a_gallery_drives_again_once_the_session_beside_it_lets_the_device_go(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), shared=Shared(osr2_motion=motion))
    qtbot.addWidget(view)
    view.osr2_control.the_session_has_it(True)

    view.osr2_control.the_session_has_it(False)
    view.toggle_osr2_drive()

    assert motion.active


def test_a_gallery_handed_back_from_a_session_stands_as_a_standalone_one_is_built(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    built = GalleryView(FakeDB([]))
    qtbot.addWidget(built)
    view.become_hosted(_session())

    view.become_standalone()

    arrangement = view._arrangement
    assert arrangement.stack is None
    assert arrangement.panes.count() == built._arrangement.panes.count() == 2
    assert arrangement.panes.widget(0) is arrangement.left_column
    generate_pane = arrangement.panes.widget(1)
    assert generate_pane.findChild(type(view._generate_pane)) is view._generate_pane
    assert generate_pane.minimumWidth() == view._generate_pane.minimumWidth() == 0
    assert arrangement.left_column.widget(0) is arrangement.folder_panes
    assert arrangement.left_column.widget(1) is view._queue
    assert arrangement.folder_panes.count() == built._arrangement.folder_panes.count() == 2


def test_a_gallery_taken_into_a_session_hides_separate_and_together_until_handed_back(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    buttons = (view._tree.separate_button, view._tree.together_button)

    view.become_hosted(_session())
    hosted = [button.isVisibleTo(view) for button in buttons]
    view.become_standalone()

    assert hosted == [False, False]
    assert [button.isVisibleTo(view) for button in buttons] == [True, True]


def test_a_gallery_handed_back_from_a_session_draws_the_toc_as_it_was_left(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view._tree.together_button.click()

    view.become_hosted(_session())
    hosted = view._tree.shapes
    view.become_standalone()

    assert (hosted, view._tree.shapes) == (SEPARATE, TOGETHER)


def test_a_gallery_handed_back_from_a_session_drives_its_own_device_again(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), shared=Shared(osr2_motion=motion))
    qtbot.addWidget(view)
    view.become_hosted(_session())

    view.become_standalone()
    view.osr2_control.setChecked(True)

    assert motion.active
    assert view._osr2_controls is not None
    assert not view._motion_pane.isHidden()


def test_a_gallery_handed_back_from_a_session_answers_its_switch_words_itself_again(qtbot):
    radio = _FakeRadio()
    view = GalleryView(FakeDB([]), shared=Shared(radio=radio))
    qtbot.addWidget(view)
    view.become_hosted(_session())

    view.become_standalone()
    view._voice.on_command(AppCommand.RADIO_ON)

    assert view._buttons.radio.isChecked()
    assert radio.starts == 1


def test_a_gallery_handed_back_from_a_session_opens_its_next_slideshow_over_the_monitor(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.become_hosted(_session())

    view.become_standalone()
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))

    slideshow = view._slideshows.showing
    assert slideshow is not None
    qtbot.addWidget(slideshow.shown)
    assert view.region_slideshow("portrait") is None
    assert slideshow.shown.isFullScreen()


def test_a_gallery_handed_back_from_a_frozen_session_lets_its_thumbnails_move_again(qtbot, tmp_path):
    rows, webp = _a_looping_video(tmp_path)
    view = _a_gallery_showing(webp)(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._tree_view.leaf_by_id["v-1"])
    view.become_hosted(_session())
    view.set_room_paused(True)

    view.become_standalone()

    assert _moving_thumbnails(view)


def test_a_gallery_taken_into_a_session_stops_the_sound_device_and_mic_it_ran(qtbot):
    radio, motion = _FakeRadio(), _SignalMotion()
    view = GalleryView(FakeDB([]), shared=Shared(radio=radio, osr2_motion=motion))
    qtbot.addWidget(view)
    view._buttons.radio.setChecked(True)
    view.osr2_control.setChecked(True)
    view._buttons.mic.setChecked(True)
    listener = view._voice.listener
    assert motion.active
    assert listener.commands_on

    view.become_hosted(_session())

    assert radio.stops == 1
    assert not motion.active
    assert not listener.commands_on


def test_a_gallery_taken_into_a_session_opens_its_next_slideshow_on_a_region(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    view.become_hosted(_session())
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200))

    slideshow = view.region_slideshow("portrait")
    assert slideshow is not None
    qtbot.addWidget(slideshow.shown)
    assert slideshow.shown.windowTitle() == "Origenerator Portrait"


def test_a_slideshow_up_when_the_gallery_is_taken_into_a_session_goes_on_on_its_shapes_side(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([_row(f"id-tall-{n}", "sdxl_t2i", {"width": 832, "height": 1216},
                                    f"tall{n}.png") for n in range(2)]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=2))
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view.slideshow_showing_on() == "portrait"

    view.become_hosted(_session())
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: [])
    open_both_shapes(view._slideshows)

    carried = view.region_slideshow("portrait")
    assert carried is not None
    qtbot.addWidget(carried.shown)
    assert [slide.prompt_id for slide in carried.whole_set()] == ["id-tall-0", "id-tall-1"]
    assert view.region_slideshow("landscape") is None


def test_a_slideshow_moved_onto_a_set_of_the_other_shape_goes_on_as_that_set_in_a_session(
        qtbot, tmp_path, monkeypatch):
    sizes = {"wide": {"width": 1216, "height": 832}, "tall": {"width": 832, "height": 1216}}
    view = GalleryView(FakeDB([_row(f"id-{name}-{n}", "sdxl_t2i", size, f"{name}{n}.png")
                               for name, size in sizes.items() for n in range(2)]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("wide", 200, 100, count=2))
    qtbot.addWidget(view._slideshows.showing.shown)
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=2))

    view.become_hosted(_session())
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: [])
    open_both_shapes(view._slideshows)

    carried = view.region_slideshow("portrait")
    assert carried is not None
    qtbot.addWidget(carried.shown)
    assert [slide.prompt_id for slide in carried.whole_set()] == ["id-tall-0", "id-tall-1"]
    assert carried.state().current in {"id-tall-0", "id-tall-1"}
    assert view.region_slideshow("landscape") is None


def test_a_slideshow_of_both_shapes_taken_into_a_session_goes_on_on_both_satellites(
        qtbot, tmp_path, monkeypatch):
    shapes = {"tall": ({"width": 832, "height": 1216}, (100, 200)),
              "wide": ({"width": 1216, "height": 832}, (200, 100))}
    rows, items = [], []
    for n, name in enumerate(("tall", "wide", "tall")):
        params, size = shapes[name]
        still = tmp_path / f"{name}{n}.png"
        Image.new("RGB", size).save(still)
        rows.append(_row(f"id-{name}-{n}", "sdxl_t2i", params, f"{name}{n}.png"))
        items.append((str(still), "image", f"id-{name}-{n}", str(still)))
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "rows_to_play", lambda: rows)
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: list(items))
    monkeypatch.setattr(view, "slideshow_subject", lambda: "a list of both shapes")
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view.slideshow_showing_on() == "both"

    view.become_hosted(_session())
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: [])
    open_both_shapes(view._slideshows)

    carried = {shape: view.region_slideshow(shape) for shape in ("portrait", "landscape")}
    for slideshow in carried.values():
        qtbot.addWidget(slideshow.shown)
    assert [slide.prompt_id for slide in carried["portrait"].whole_set()] == [
        "id-tall-0", "id-tall-2"]
    assert [slide.prompt_id for slide in carried["landscape"].whole_set()] == ["id-wide-1"]


def test_a_gallery_taken_into_a_session_leaves_its_spoken_motion_words_to_the_session(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), shared=Shared(osr2_motion=motion))
    qtbot.addWidget(view)

    view.become_hosted(_session())
    view._voice.on_command(AppCommand.SPEED_UP)

    assert [call for call in motion.calls if isinstance(call, tuple) and call[0] == "speed"] == []


def test_a_gallery_taken_into_a_session_answers_its_switch_words_as_the_sessions(qtbot, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    answers = []
    monkeypatch.setattr(view._slideshows, "answer",
                        lambda line, kind=None: answers.append((line, kind)))

    view.become_hosted(_session())
    for word in (AppCommand.RADIO_ON, AppCommand.DRIVE_ON, AppCommand.MIC_OFF):
        view._voice.on_command(word)

    assert answers == [(f"{name} is the session's here", WARNING)
                       for name in ("Origenerator Radio", "OSR2", "the mic")]


def test_the_drive_word_says_so_while_a_session_beside_this_one_has_the_device(
        qtbot, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    answers = []
    monkeypatch.setattr(view._slideshows, "answer",
                        lambda line, kind=None: answers.append((line, kind)))

    view.osr2_control.the_session_has_it(True)
    view._voice.on_command(AppCommand.DRIVE_ON)

    assert answers == [("OSR2 can't be switched here", WARNING)]


def _thick_borders(view):
    return [splitter.handle(index) for splitter in view.findChildren(PaneSplitter)
            for index in range(1, splitter.count())]


def test_a_hosted_gallery_holds_every_thick_border_still(qtbot):
    view = _fun_time_view(qtbot)

    borders = _thick_borders(view)
    assert borders
    assert not any(border.isEnabled() for border in borders)


def test_a_gallery_taken_into_a_session_holds_its_borders_until_handed_back(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert all(border.isEnabled() for border in _thick_borders(view))

    view.become_hosted(_session())
    assert not any(border.isEnabled() for border in _thick_borders(view))

    view.become_standalone()
    assert all(border.isEnabled() for border in _thick_borders(view))


def test_a_hosted_gallery_holds_its_borders_through_the_headset_and_back(qtbot):
    view = _fun_time_view(qtbot)
    in_a_headset = replace(_session(), frames_file=Path("frame.bin"),
                           input_file=Path("input.txt"))

    view.wear_the_room(in_a_headset)
    assert not any(border.isEnabled() for border in _thick_borders(view))

    view.wear_the_room(_session())
    assert not any(border.isEnabled() for border in _thick_borders(view))


def test_a_tab_opened_in_a_session_holds_its_border_still(qtbot):
    view = _fun_time_view(qtbot)

    opened = view._generate_pane._add_subtab()

    assert not opened._media_split.handle(1).isEnabled()


def test_a_gallery_taken_into_a_session_stands_its_open_portrait_tab_beside_the_form(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    tab = view._generate_pane.current_generate_tab()
    tab._viewport._pixmap = QPixmap(400, 900)

    view.become_hosted(_session())

    assert tab._media_split.orientation() == Qt.Orientation.Horizontal


def test_a_gallery_handed_back_from_a_session_stacks_its_open_portrait_tab_again(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    tab = view._generate_pane.current_generate_tab()
    tab._viewport._pixmap = QPixmap(400, 900)
    view.become_hosted(_session())

    view.become_standalone()

    assert tab._media_split.orientation() == Qt.Orientation.Vertical


def test_standalone_never_stands_them_side_by_side(qtbot):
    tab = GenerateTab(None, FakeDB([]))
    qtbot.addWidget(tab)

    tab._viewport._pixmap = QPixmap(400, 900)
    tab._reflow_for_the_media()

    assert tab._media_split.orientation() == Qt.Orientation.Vertical, (
        "the pane is wide there, so stacking is right at any shape")


def test_a_tab_coming_to_the_front_lays_out_for_its_own_image(qtbot):
    tabs = GeneratePane(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tabs)
    portrait_tab = tabs.currentWidget()
    portrait_tab._viewport._pixmap = QPixmap(400, 900)
    portrait_tab.refresh_media_layout()
    assert portrait_tab._media_split.orientation() == Qt.Orientation.Horizontal

    tabs._add_subtab()
    landscape_tab = tabs.currentWidget()
    landscape_tab._viewport._pixmap = QPixmap(1200, 700)
    tabs.setCurrentWidget(portrait_tab)
    tabs.setCurrentWidget(landscape_tab)

    assert landscape_tab._media_split.orientation() == Qt.Orientation.Vertical, (
        "the shape belongs to the tab, so switching to one holding a landscape image stands the "
        "panes back up")


def _hud_label_for(view):
    worn = {}

    class _Slideshow:
        def wear_the_hud(self, shape, wear):
            worn.update(vars(wear))

    view._slideshows._wear_the_hud(_Slideshow(), "landscape")
    return worn["label_for"]


def test_the_slideshows_hud_names_the_item_the_way_this_app_does(qtbot):
    row = _image("p1", "a cat", 50, 1)
    view = _fun_time_view(qtbot, rows=[row])
    view.refresh()

    assert _hud_label_for(view)("p1") == (
        f"{gallery.folder_id(gallery.settings_folder_key(row))} 000")


def test_an_item_no_row_claims_is_named_nothing_at_all(qtbot):
    view = _fun_time_view(qtbot)
    view.refresh()
    assert _hud_label_for(view)("nobody") == ""
    assert _hud_label_for(view)("") == ""


def test_a_hosted_slideshows_hud_carries_the_enhanced_switch_beside_f_mode(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_enhanced_ids_of", lambda rows: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    names = hud_button_names(slideshow.shown)
    assert names.index("enhanced") == names.index("fmode") + 1

    slideshow.shown.press("portrait_enhanced")

    assert slideshow.hud_enhanced_mode is True
    assert slideshow.pass_size() == 1
    model = slideshow_hud_model("portrait", slideshow)
    assert _lit(model, "portrait_enhanced")
    assert "Enhanceds" in model.title
    assert not (tmp_path / "dashboard_cmd.txt").exists()

    slideshow.shown.press("portrait_enhanced")
    assert slideshow.pass_size() == 3


def test_a_spoken_enhanced_only_narrows_the_named_regions_slideshow(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_enhanced_ids_of", lambda rows: {"id-tall-1"})
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1", "id-tall-2"})
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)

    assert view.run_spoken_command("portrait enhanced only")
    assert slideshow.hud_enhanced_mode is True, (
        "hosted, a named shape takes that region's slideshow, since two run at once and neither "
        "is the active window")
    assert slideshow.pass_size() == 1

    assert view.run_spoken_command("portrait favorites")
    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_mode) == (True, True)

    assert view.run_spoken_command("portrait clear filter")
    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_mode) == (True, True)
    assert slideshow.pass_size() == 1


def test_a_regions_reset_drops_the_enhanced_switch_with_the_rest(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_enhanced_ids_of", lambda rows: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, _Slides("tall", 100, 200, count=3))
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    slideshow.toggle_enhanced_mode()
    assert slideshow.hud_enhanced_mode is True

    slideshow.slideshow_reset()

    assert slideshow.hud_enhanced_mode is False
