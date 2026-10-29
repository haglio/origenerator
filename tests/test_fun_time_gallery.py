"""The gallery inside a Fun Time session: no OSR2 anywhere, vertical layout.

Fun Time's Main Funestra owns the OSR2 for the whole session, so a hosted
Origenerator must offer no way to reach the device — no toggle, no motion, no
console — and its layout folds to fit the Random Favs Browser's upright rect.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from funestra.console import OSR2_PARKED, OSR2_RETRACTED
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMovie, QPixmap
from PyQt6.QtWidgets import QLabel, QSplitter, QWidget

from origenerator import gallery
from origenerator.db import Database
from origenerator.fun_time_mode import FunTimeSession, Rect
from origenerator.gallery.collection import RECENTS_KEY
from origenerator.gallery.sides import SEPARATE, TOGETHER
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.gui.notice_overlay import NOTICE, WARNING
from origenerator.gui.panes import PaneSplitter
from origenerator.gui.slideshow_panel import slideshow_hud_model
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.commands import CollectionCommand, SurfaceCommand
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import part_table
from tests.marked_words import words
from tests.slideshow_hud_support import (
    engine_of,
    funestra_of,
    hud_button_names,
    open_both_sides,
    speaker_on_screen,
)
from tests.test_gallery_view import (  # the in-memory Database stand-in, and a row for it
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


def _session(tmp_path=None):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=None, paused_file=None, status_file=None,
        dashboard_cmd_file=None,
    )


def _as_items(rows):
    """The fixture's rows as a slideshow's items — a tuple passed through, a row
    stood in for by a tuple named after it — where a test hands the director a
    library of ready-made items rather than files to resolve."""
    return [row if isinstance(row, tuple)
            else (f"{row['prompt_id']}.png", "image", row["prompt_id"],
                  row.get("thumbnail_path"))
            for row in rows]


def _fun_time_view(qtbot, rows=()):
    view = GalleryView(FakeDB(list(rows)), fun_time=_session())
    qtbot.addWidget(view)
    return view


def _lit(model, action: str) -> bool:
    """Whether the button posting *action* is drawn lit on the slideshow's panel."""
    return next(button.lit for row in model.rows for button in row
                if button.command == action)


def test_fun_time_gallery_builds_no_shared_appliance_switches(qtbot):
    """The room's audio and its microphone are the session's, not this app's:
    the Main Funestra owns the sound and Fun Time owns the mic (it hears this
    app's spoken commands too and posts them on the channel), so a second
    switch for either would be a switch over something this window does not
    hold."""
    view = _fun_time_view(qtbot)
    assert view._bank.radio is None
    assert view._bank.mic is None
    view.set_radio_enabled(True)   # a stale standalone session key must not crash
    assert view.radio_enabled() is False


def test_fun_time_gallery_builds_no_osr2_surface(qtbot):
    view = _fun_time_view(qtbot)
    assert view._osr2_motion is None
    assert view._osr2_driver is None
    assert view.osr2_control.isEnabled() is False
    assert view.osr2_control.state() == OSR2_PARKED
    assert view._motion_panel is None


def test_fun_time_gallery_ignores_the_motion_keys(qtbot):
    # Space and friends belong to Fun Time's own hotkeys while hosted; nothing
    # here may swallow them, let alone drive the device.
    view = _fun_time_view(qtbot)
    view.show()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_J,
                      Qt.KeyboardModifier.NoModifier)
    assert view.eventFilter(view, event) is False


def test_fun_time_gallery_carries_the_standalone_osr2_state_through(qtbot):
    """Hosted, the device is the session's, so the state the standalone app was
    left in cannot be put on -- and is handed back untouched on the way out
    rather than saved over, since both runs keep the one state file."""
    view = _fun_time_view(qtbot)

    view.restore_osr2_state(OSR2_RETRACTED)

    assert view.osr2_control.state() == OSR2_PARKED
    assert view.osr2_state() == OSR2_RETRACTED


def test_fun_time_gallery_stacks_the_generate_tabs_over_the_browser(qtbot):
    # The RFB rect is an upright column, so the side-by-side panes fold into one
    # vertical stack: generate tabs on top, the tree-and-browser row under them,
    # the queue across the foot.
    view = _fun_time_view(qtbot)
    stack = view._arrangement.stack
    assert isinstance(stack, QSplitter)
    assert stack.orientation() == Qt.Orientation.Vertical
    assert stack.count() == 3
    # Top floor: the info-pane wrapper (tabs + the find bar).
    assert stack.widget(0).findChild(type(view._info_tabs)) is view._info_tabs
    # Middle floor: the tree beside the browser.
    assert stack.widget(1) is view._arrangement.panes
    assert view._arrangement.panes.count() == 2
    assert view._arrangement.panes.widget(1) is view._arrangement.folder_panes
    # The lowest row: the queue, spanning the tree's width too.
    assert stack.widget(2) is view._queue


def test_fun_time_gallery_gives_the_lower_corner_to_the_queue(qtbot):
    """The tree stops above the queue rather than running the rect's full
    height, so the corner under it is the queue — where standalone has it."""
    view = _fun_time_view(qtbot)
    view.resize(600, 900)
    with qtbot.waitExposed(view):
        view.show()
    toc = view._arrangement.panes.widget(0)
    corner = view._queue.mapTo(view, view._queue.rect().bottomLeft())
    tree_foot = toc.mapTo(view, toc.rect().bottomLeft())
    assert tree_foot.y() < corner.y()  # the tree ends before the rect does
    assert view._queue.mapTo(view, view._queue.rect().topLeft()).x() <= (
        toc.mapTo(view, toc.rect().topLeft()).x()
    )  # and the queue reaches the left edge the tree used to own


def test_fun_time_gallery_has_no_collapse_toggle_on_its_left_pane(qtbot):
    """No chevron for the tree.  It sat beside the back/forward chevrons and
    read as a third one of those, and folding the tree away bought a column
    this narrow very little — the divider still drags shut for anyone who
    wants the room."""
    view = _fun_time_view(qtbot)
    assert not hasattr(view, "_toc_toggle")
    assert view._arrangement.panes.isCollapsible(0)


def test_fun_time_gallery_draws_neither_separate_nor_together_over_its_folder_list(qtbot):
    view = _fun_time_view(qtbot)
    with qtbot.waitExposed(view):
        view.show()

    assert not view._tree.separate_button.isVisible()
    assert not view._tree.together_button.isVisible()
    assert view._tree._splitter.mapTo(view._tree, QPoint()).y() == 0


def test_standalone_gallery_keeps_its_panes_side_by_side(qtbot):
    """Standalone the folder column and the info pane sit beside each other,
    with the tree inside that column rather than out on the window's edge."""
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert view._arrangement.panes.count() == 2
    assert view._arrangement.panes.widget(0) is view._arrangement.left_column
    # The second pane is the info-pane wrapper (tabs + the find bar).
    assert view._arrangement.panes.widget(1).findChild(type(view._info_tabs)) is view._info_tabs
    assert view._arrangement.folder_panes.count() == 2  # the tree, then the browser


def test_a_headset_gallery_keeps_the_standalone_panes_side_by_side(qtbot):
    """The upright stack is the Random Favs Browser's rect asking for it."""
    view = GalleryView(FakeDB([]), fun_time=replace(
        _session(), frames_file=Path("frame.bin"), input_file=Path("input.txt")))
    qtbot.addWidget(view)

    assert view._arrangement.stack is None, "the headset got the upright fold"
    assert view._arrangement.panes.widget(0) is view._arrangement.left_column
    assert view._arrangement.folder_panes.count() == 2  # the tree, then the browser


def _row_of(item) -> dict:
    """An item tuple as the library row it was built from.

    Rows and items are different things — a slideshow is built from items and armed
    with the versions read off rows — so the stubs hand over each in its own
    shape rather than one standing in for both.
    """
    return {"prompt_id": item[2], "output_files": "[]", "thumbnail_path": item[3]}


def _items_of(rows) -> list:
    return [(row["thumbnail_path"], "image", row["prompt_id"], row["thumbnail_path"])
            for row in rows]


def _open_slideshow(view, monkeypatch, tmp_path, name, width, height, count=1):
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
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    slideshow = view._slideshows._region_slideshows["portrait"]
    assert slideshow is not None and slideshow.shown.isVisible()
    assert slideshow.shown.windowTitle() == "Origenerator Portrait"
    assert slideshow.shown.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert slideshow.shown.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    geo = slideshow.shown.geometry()
    assert (geo.width(), geo.height()) == (1440, 1870)
    qtbot.addWidget(slideshow.shown)


def test_both_regions_can_hold_a_slideshow_at_once(qtbot, tmp_path, monkeypatch):
    # The whole point of sending slideshows to the satellite regions: the main
    # window stays usable while up to two slideshows run.
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    portrait = view._slideshows._region_slideshows["portrait"]
    landscape = view._slideshows._region_slideshows["landscape"]
    assert portrait is not None and portrait.shown.isVisible()
    assert landscape is not None and landscape.shown.isVisible()
    assert portrait is not landscape
    for slideshow in (portrait, landscape):
        qtbot.addWidget(slideshow.shown)


def test_a_slideshow_in_a_session_begins_on_the_one_item_picked(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
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
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    slideshow = view._slideshows._region_slideshows["landscape"]
    qtbot.addWidget(slideshow.shown)

    assert _press_escape(view) is True

    channel = tmp_path / "dashboard_cmd.txt"
    assert channel.read_text(encoding="utf-8").split() == ["omnipause_toggle"]
    assert slideshow.is_showing()


def test_a_new_slideshow_replaces_the_regions_current_occupant(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "first", 100, 200)
    first = view._slideshows._region_slideshows["portrait"]
    _open_slideshow(view, monkeypatch, tmp_path, "second", 90, 200)
    second = view._slideshows._region_slideshows["portrait"]
    assert second is not first
    assert not first.shown.isVisible()
    assert second.shown.isVisible()
    for slideshow in (first, second):
        qtbot.addWidget(slideshow.shown)


def test_a_preview_double_click_lands_its_slideshow_on_the_matching_region(qtbot, tmp_path):
    """A double-click on a tab's preview opens the folder as a slideshow — hosted,
    that slideshow lands on the region its media belongs to rather than taking over
    whichever monitor the click happened on."""
    view = _fun_time_view(qtbot)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)

    slideshow = view._slideshows.open_on_preview((str(wide), "image"), None)

    qtbot.addWidget(slideshow.shown)
    assert view.region_slideshow("landscape") is slideshow
    assert slideshow.shown.windowTitle() == "Origenerator Landscape"


def test_a_region_slideshow_is_muted_like_every_satellite(qtbot, tmp_path):
    # Standalone, the slideshow is the deliberate foreground and plays sound; on a
    # satellite region the session's Main Funestra owns the room's audio, and the
    # satellites are silent by design — so the hosted slideshow is too.
    view = _fun_time_view(qtbot)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)

    slideshow = view._slideshows.open_on_preview((str(wide), "image"), None)

    qtbot.addWidget(slideshow.shown)
    assert engine_of(slideshow.shown).muted is True


def _a_region_slideshow_beside_the_gallerys_radio(qtbot, tmp_path):
    radio = _FakeRadio()
    view = GalleryView(FakeDB([]), fun_time=_session(), radio=radio)
    qtbot.addWidget(view)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)
    slideshow = view._slideshows.open_on_preview((str(wide), "image"), None)
    qtbot.addWidget(slideshow.shown)
    engine_of(slideshow.shown)
    slideshow.shown._pane.tick()
    return view, slideshow, radio


def test_a_region_slideshow_plays_none_of_the_gallerys_radio(qtbot, tmp_path):
    # Hosted, each Satellite Funestra plays the stations the session deals it.
    _view, _slideshow, radio = _a_region_slideshow_beside_the_gallerys_radio(qtbot, tmp_path)

    assert radio.held == []


def test_a_region_slideshows_volume_is_not_what_a_standing_one_opens_at(qtbot, tmp_path):
    view, slideshow, _radio = _a_region_slideshow_beside_the_gallerys_radio(qtbot, tmp_path)

    slideshow.shown._pane.press(QPointF(speaker_on_screen(slideshow.shown._pane)))

    assert view._slideshows.remembered()["volume"] is None


def test_a_presented_slideshow_takes_the_keyboard(qtbot):
    # The slideshow must answer its own keys the moment it opens — left unfocused,
    # its arrows land in the main window and the view reads as dead.  The
    # offscreen platform cannot express real activation, so the contract is
    # pinned at the seam: presenting raises and activates the window.

    view = _fun_time_view(qtbot)
    stub = QWidget()
    qtbot.addWidget(stub)
    calls: list[str] = []
    stub.raise_ = lambda: calls.append("raise")
    stub.activateWindow = lambda: calls.append("activate")
    # Presenting mutes the window, holds its slideshow mid-freeze, and dresses it
    # in the Funestras' HUD, as a real SlideshowView answers.
    stub.set_audio_muted = lambda muted: None
    stub.slideshow = SimpleNamespace(set_paused=lambda paused: None)
    stub.wear_the_hud = lambda side, **how: None  # told whose panel it wears, and where
    view._slideshows._present_surface(stub, "portrait")
    assert calls == ["raise", "activate"]


def test_a_preview_double_click_opens_the_slideshow_on_a_region(qtbot, tmp_path):
    # End to end from the gesture: the info-pane preview's double-click, hosted,
    # lands the slideshow it opens on the region matching the media.
    view = _fun_time_view(qtbot)
    view.show()
    panel = view._info_tabs.current_config_panel()
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)
    panel._preview.show_media(str(wide), "image")

    qtbot.mouseDClick(panel._preview, Qt.MouseButton.LeftButton,
                      pos=QPoint(panel._preview.width() // 2,
                                 panel._preview.height() // 2))

    slideshow = view.region_slideshow("landscape")
    assert slideshow is not None and slideshow.shown.isVisible()
    geo = slideshow.shown.geometry()
    assert (geo.width(), geo.height()) == (1707, 1440)
    qtbot.addWidget(slideshow.shown)


def test_a_presented_slideshow_wears_the_funestras_own_hud(qtbot, tmp_path, monkeypatch):
    """The slideshow covers the Satellite Funestra's HUD, so it wears the Funestras'
    own — the same panel from the same shared code: mode pair, transport, and
    the nav map speaking the set as a seed family.  The view's own furnishings
    come off; the map says all of it."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    names = hud_button_names(slideshow.shown)
    # The mode pair is on it — the way back to kino mode from atop a slideshow.
    assert [n for n in names if n in MODE_VERBS] == [
        "satellites_kino_activate", "origenerator_activate"]
    # The transport controls are the Funestras' own set.
    assert {"prev", "next", "lock", "trash"} <= set(names)
    # The window a Funestra's minimize parks is not this slideshow's, so the panel
    # declares no such button rather than drawing one whose press goes nowhere.
    assert "minimize" not in names

    # A transport press posts on the session's channel, exactly as a Funestra's
    # HUD posts it.
    slideshow.shown.press("portrait_next")
    posted = (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split()
    assert posted == ["portrait_next"]


def test_a_click_on_a_hosted_slideshow_asks_the_room_for_omnipause(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
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
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
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
    """Four portrait pictures — two of one configuration under two seeds, a
    third of the first seed under an edited prompt, and a stranger — and a
    video animated from the first of them."""
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    rows = [_image("g1", "a red fox", 50, 1), _image("g2", "a red fox", 50, 2),
            _image("g3", "a red fox at dawn", 50, 1), _image("g4", "a blue car", 30, 9),
            _row("v1", "wan22_i2v",
                 {"positive_prompt": "the fox runs", "noise_seed": 5,
                  "input_image": "sdxl_t2i_g1.png"},
                 "wan22_i2v_v1.mp4", act="alpha")]
    for row in rows:
        row["thumbnail_path"] = str(tall)
        if row["workflow_name"] == "sdxl_t2i":
            row["params_json"] = json.dumps(
                {**json.loads(row["params_json"]), "width": 720, "height": 1280})
    return rows


def _open_the_fox_slideshow(qtbot, view, monkeypatch, rows):
    """The fox library as a portrait slideshow, standing on the first fox."""
    view.refresh()      # the pictures are indexed, as they are once the app is up
    monkeypatch.setattr(view, "rows_to_play", lambda: rows)
    monkeypatch.setattr(view._slideshows, "items_of", _as_items)
    monkeypatch.setattr(view, "slideshow_subject", lambda: "the fox folder")
    view._slideshows.start()
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    slideshow.show_item("g1.png")
    return slideshow


def test_the_huds_map_is_the_gamma_around_the_slide_on_screen(qtbot, tmp_path, monkeypatch):
    """The slide in the corner; the same configuration under its other seed
    running right; its own seed under another configuration running down,
    named by that folder, and then the video animated from it, named for its
    act, with the picture's own row named as that video's source; the corner
    lit and no loop — the Funestras' map, drawn against this app's library of
    that side's shape."""
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    slideshow = _open_the_fox_slideshow(qtbot, view, monkeypatch, rows)

    model = slideshow_hud_model("portrait", slideshow)

    assert model.corner.path == "g1.png"
    assert [cell.path for cell in model.seeds] == ["g2.png"]
    a_configuration, an_act = model.actions
    assert (a_configuration.path, an_act.path) == ("g3.png", "v1.png")
    assert an_act.label == "alpha"
    assert a_configuration.label and a_configuration.label != "alpha"   # its folder
    assert model.current_action == "Source image"
    assert (model.seed_count, model.action_count) == (2, 3)
    assert model.playing == ("corner", 0) and model.active_loop == ""
    assert model.title == "Unlocked · Shuffle"
    # And the mode pair leads the panel, with this mode lit: the way back to
    # the Funestra under the slideshow.
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
    """The column can name a generation outside the set a slideshow opened with —
    a video of this picture, which lives in a folder of its own — and a
    click on it plays it, spliced in after the slide on screen."""
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view, "rows_to_play", lambda: rows[:2])   # the fox folder alone
    monkeypatch.setattr(view._slideshows, "items_of", _as_items)
    monkeypatch.setattr(view, "slideshow_subject", lambda: "the fox folder")
    view._slideshows.start()
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    slideshow.show_item("g1.png")

    slideshow.show_item("v1.png")

    assert slideshow._set.playlist.current()[2] == "v1"
    assert slideshow.hud_map().corner.path == "v1.png"    # and the map re-homed on it


def test_a_hud_map_click_jumps_the_slideshow_to_that_item(qtbot, tmp_path, monkeypatch):
    """A thumbnail click switches a Funestra to that clip; on a slideshow it jumps the
    set to that item — and the double-click's lock holds it there."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    still_b = tmp_path / "b.png"
    Image.new("RGB", (100, 200)).save(still_b)
    items = [(str(tmp_path / "tall.png"), "image", "id-a", str(tmp_path / "tall.png")),
             (str(still_b), "image", "id-b", str(still_b))]
    Image.new("RGB", (100, 200)).save(tmp_path / "tall.png")
    monkeypatch.setattr(view, "rows_to_play",
                        lambda: [{"prompt_id": item[2], "workflow_name": item[2]}
                                 for item in items])
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: list(items))
    monkeypatch.setattr(view, "slideshow_subject", lambda: "a folder")
    view._slideshows.start()
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    slideshow.show_item(str(still_b), lock=True)

    assert slideshow._set.playlist.current()[0] == str(still_b)
    assert slideshow.locked


def test_a_recents_slideshow_plays_latest_not_shuffled(qtbot, tmp_path, monkeypatch):
    """Recents is the Funestras' Latest: the collection lists newest first and its
    slideshow plays that order, where every other set shuffles — and the
    slideshow's HUD title says which."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_current_collection_key", lambda: RECENTS_KEY)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    assert slideshow._set.playlist.order == [0, 1, 2]  # the listing's own order, unshuffled
    assert slideshow.hud_order_label == "Latest"


def test_f_mode_on_a_slideshow_narrows_the_set_to_the_favorites(qtbot, tmp_path, monkeypatch):
    """The Funestras' F-mode, meaning on a slideshow what it means on a Funestra:
    narrow to the favorites — the favorited items, the same ones the
    Favorites collection lists — and widen back on the second press."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    slideshow.shown.press("portrait_fmode")

    assert slideshow.hud_favorites_filter is True
    assert slideshow.pass_size() == 1  # narrowed to the one favorite
    model = slideshow_hud_model("portrait", slideshow)
    assert _lit(model, "portrait_fmode") and "F-Mode" in model.title

    slideshow.shown.press("portrait_fmode")
    assert slideshow.pass_size() == 3  # widened back
    # The star readout lights exactly on the favorite item.  (Every fixture
    # item shares one file, so land on it by position, not by path.)
    slideshow._set.playlist.jump_to(1)
    assert slideshow.hud_is_favorite is True
    slideshow._set.playlist.jump_to(0)
    assert slideshow.hud_is_favorite is False


def test_a_hosted_slideshow_keeps_up_with_its_own_folder(qtbot, tmp_path, monkeypatch):
    """A slideshow plays on a satellite region while the main window goes on being
    used, so by the time an auto-generated item lands the browser is usually
    elsewhere — and both regions may be playing different folders.  Each slideshow
    is fed from the location IT opened at, not from the view on screen."""
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    portrait = view.region_slideshow("portrait")
    qtbot.addWidget(portrait.shown)
    # The slideshow opened from a folder; the browser has since moved off it.
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

    assert portrait.pass_size() == before + 1


def test_a_landing_reaches_only_the_slideshow_playing_its_folder(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
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

    assert portrait.pass_size() == counts[0]        # not its folder
    assert landscape.pass_size() == counts[1] + 1   # its folder


def test_a_spoken_side_and_collection_plays_it_on_that_region(qtbot, tmp_path, monkeypatch):
    """"landscape latest": that collection's landscape items, on the landscape
    region — a slideshow STARTED by voice, with nothing up beforehand and the
    browser left wherever it was.  Latest plays newest-first, and its HUD says
    so, exactly as the collection's own slideshow button opens it."""
    view = _fun_time_view(qtbot)
    still = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(still)
    rows = [{"prompt_id": "new-1", "thumbnail_path": str(still)}]
    monkeypatch.setattr(view._browser, "rows_for_collection",
                        lambda key: rows if key == "__recents__::landscape" else [])
    monkeypatch.setattr(view._slideshows, "items_of",
                        lambda r: [(str(still), "image", row["prompt_id"], str(still))
                                   for row in r])

    view._voice.on_command(CollectionCommand("__recents__", "landscape"))

    slideshow = view.region_slideshow("landscape")
    assert slideshow is not None and slideshow.shown.isVisible()
    assert slideshow.hud_order_label == "Latest"   # the HUD says which order it plays
    assert view.region_slideshow("portrait") is None  # the other region is untouched
    qtbot.addWidget(slideshow.shown)


def test_the_maps_loop_button_loops_the_seed_row_and_the_next_press_ends_it(
        qtbot, tmp_path, monkeypatch):
    """The seed-loop button plays the row round and round: the pass becomes
    the row, the button lights, and the line says so in the satellite's own
    words — dropping "Unlocked", exactly as a looping satellite's does, since a
    set playing through holds nothing.  The press that ends it puts the slideshow
    back to browsing what it opened with, the slide on screen kept."""
    rows = _fox_library(tmp_path)
    view = GalleryView(FakeDB(rows), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    slideshow = _open_the_fox_slideshow(qtbot, view, monkeypatch, rows)

    slideshow.shown.press("portrait_seed_loop")

    assert [item[2] for item in slideshow._set.playlist.items] == ["g1", "g2"]
    model = slideshow_hud_model("portrait", slideshow)
    assert model.active_loop == "seed"
    # A seed loop lights the row it is playing, which is what that row's
    # button says about it; an act filter would light every row it keeps.
    assert model.filter_query == model.current_action == "Source image"
    assert model.title.startswith("Looping seeds")
    assert "Unlocked" not in model.title
    assert words(slideshow.shown._note) == "Looping seeds: 2"

    slideshow.shown.press("portrait_no_loop")

    assert slideshow.shown.isVisible()                      # the region is not handed back
    assert slideshow.pass_size() == 5                 # it browses its set again
    assert slideshow._set.playlist.current()[2] == "g1"
    dropped = slideshow_hud_model("portrait", slideshow)
    assert dropped.active_loop == ""
    assert "Looping" not in dropped.title


def test_more_seeds_widens_the_row_to_the_nearest_configurations_and_loops_it(
        qtbot, tmp_path, monkeypatch):
    """The expand mark: the row grows past the exact configuration to the
    nearest others of the same model, and that wider row is what loops."""
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
    """A region browsing its whole library is what a satellite does with no loop
    on, so its HUD must read that way: the loop button dark, the map unframed,
    and the line naming the order rather than a loop.  It said "Looping seeds"
    over the base state, which is the one place there is no loop at all."""
    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(4)]
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in base]
                                     if key == "__all__::portrait" else []))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)

    open_both_sides(view)

    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    model = slideshow_hud_model("portrait", slideshow)
    assert model.active_loop == ""
    assert model.title == "Unlocked · Shuffle"


def test_a_region_the_session_wants_never_stays_empty(qtbot, tmp_path, monkeypatch):
    """The Funestra under a region is blacked for the whole mode, so a region left
    empty is a black rectangle — not a fallback.  Two ways it can be left empty
    and both are answered: the slideshow covering it ends, and the base state was
    asked for before the tree it reads had been built (the session's open
    races this app's boot)."""
    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(4)]
    library = {"rows": []}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in library["rows"]]
                                     if key == "__all__::portrait" else []))
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)

    open_both_sides(view)          # asked for too early: nothing to play yet
    assert view.region_slideshow("portrait") is None

    library["rows"] = base
    view.refresh()                   # the tree exists now, and so does the slideshow
    slideshow = view.region_slideshow("portrait")
    assert slideshow is not None
    qtbot.addWidget(slideshow.shown)

    slideshow.close()                     # and it comes back under whatever ends
    later = view.region_slideshow("portrait")
    assert later is not None and later is not slideshow
    qtbot.addWidget(later.shown)

    view.close_the_slideshows()         # until the session says it is done with them
    assert view.region_slideshow("portrait") is None


def test_a_spoken_favorites_is_the_slideshows_own_f_mode(qtbot, tmp_path, monkeypatch):
    """On a Funestra "favorites" is F-mode — narrow what is playing to them — so
    on a slideshow it is the same switch, the one its HUD already draws.  Opening
    the collection as a fresh slideshow would answer a word the HUD has a button for with
    something else entirely."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)

    view._voice.on_command(CollectionCommand("__starred__", "portrait"))
    assert slideshow.hud_favorites_filter is True
    assert slideshow.pass_size() == 1     # narrowed to the one favorite

    view._voice.on_command(CollectionCommand("__starred__", "portrait"))
    assert slideshow.hud_favorites_filter is False          # and the word widens it back


def test_a_spoken_fix_names_which_region_it_means(qtbot, tmp_path, monkeypatch):
    """"landscape fix teeth": hosted, two slideshows run and NEITHER is the active
    window, so the side word is the only thing that says which picture."""
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    portrait, landscape = view.region_slideshow("portrait"), view.region_slideshow("landscape")
    for slideshow in (portrait, landscape):
        qtbot.addWidget(slideshow.shown)
    fixed = []
    monkeypatch.setattr(
        view, "fix_parts",
        lambda prompt_id, parts: (prompt_id,
                                  "fixing " + " ".join(p.name for p in parts),
                                  NOTICE))
    for slideshow in (portrait, landscape):
        monkeypatch.setattr(slideshow, "note_voice_run",
                            lambda pid, msg, *, kind, s=slideshow: fixed.append((s, pid, msg)))
    teeth = next(p for p in part_table() if p.name == "teeth")

    # A fix names one or more parts, so the command carries them as a set.
    view._voice.on_command(SurfaceCommand([teeth], "landscape"))

    assert [entry[0] for entry in fixed] == [landscape]
    assert fixed[0][2] == "fixing teeth"


def test_a_lock_on_a_hosted_slideshow_opens_its_generate_tab(qtbot, tmp_path, monkeypatch):
    """Locking an item on a slideshow answers in the core window too — the way the
    RFB opens a tab for a locked video, the item arrives as a generate tab
    ready to work on.  Releasing the hold (the second toggle) asks nothing."""
    # _open_slideshow names its items id-<name>-<n>, so the row under the one
    # on screen is id-tall-0.
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    opened, navigated = [], []
    monkeypatch.setattr(view._info_tabs, "load_selection",
                        lambda row, images, **kw: opened.append(row["prompt_id"]))
    # Landing on the item is what opens its tab, so the link is spied on rather
    # than swallowed: it has to run for the tab to come of it.
    real_link = view.follow_link

    def follow(prompt_id):
        navigated.append(prompt_id)
        real_link(prompt_id)

    monkeypatch.setattr(view, "follow_link", follow)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    # The item held, not a sibling of it: every seed of one set of settings shares a
    # settings folder, so a tab picked by folder came up on the wrong picture.
    assert opened == ["id-tall-0"]
    assert navigated == ["id-tall-0"]  # and the browser went there too

    slideshow.slideshow_toggle_lock()  # release: no second tab
    assert len(opened) == 1


def test_a_lock_on_a_hosted_slideshow_asks_the_room_to_show_this_app_once(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([_image("id-tall-0", "a cat", 50, 1)]),
                       fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
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
    """The lock-opens-a-tab answer is the hosting session's convention; the
    standalone app's fullscreen slideshow keeps its lock to itself."""
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    opened = []
    monkeypatch.setattr(view._info_tabs, "load_selection",
                        lambda row, images, **kw: opened.append(row["prompt_id"]))
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    slideshow = view._slideshows.showing
    funestra_of(slideshow.shown)

    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    assert slideshow.hud_is_favorite
    assert opened == []


def test_closing_the_gallery_closes_the_slideshow_it_opened(qtbot, tmp_path, monkeypatch):
    """A slideshow is a window of its own: a gallery let go with one up would leave
    it on the monitor, answering to nobody."""
    view = GalleryView(FakeDB([_image("id-tall-0", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    slideshow = view._slideshows.showing

    view.close()

    assert not slideshow.shown.isVisible()
    assert view._slideshows._live_slideshows == []


def test_reset_on_a_slideshow_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    """The Funestras' reset, on a slideshow: F-mode drops, a held lock releases, and
    the first item comes back on screen — the side's defaults, not a dead
    button drawn for sameness."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)

    slideshow.shown.press("portrait_fmode")
    slideshow._set.playlist.jump_to(1)
    slideshow.slideshow_toggle_lock()
    assert slideshow.hud_favorites_filter is True

    slideshow.shown.press("portrait_reset")

    assert slideshow.hud_favorites_filter is False
    assert slideshow.pass_size() == 3           # widened back to the whole set
    assert slideshow._set.playlist.index == 0       # back at the top of the pass
    assert slideshow.locked is False            # the hold released with everything else


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
    """The base state of origenerator mode: each region shuffling every item of
    its own orientation, the way each Satellite Funestra shuffles the whole
    library of its own.

    It opened on the Latest collection before this — a recent slice rather than the
    library — and on a black screen before that.
    """
    view = _fun_time_view(qtbot)
    library = _a_library_of_each_shape(view, tmp_path, monkeypatch)

    open_both_sides(view)

    for side in ("portrait", "landscape"):
        slideshow = view.region_slideshow(side)
        assert slideshow is not None and slideshow.shown.isVisible()
        assert slideshow.hud_order_label == "Shuffle"
        assert [str(item.path) for item in slideshow._set.playlist.items] == \
            [library[f"__all__::{side}"][0]["thumbnail_path"]]
        qtbot.addWidget(slideshow.shown)
    # And each remembers WHERE it plays from, so what lands in the library
    # reaches a region sitting in its base state.
    assert sorted(where for _slideshow, where in view._slideshows._live_slideshows) == [
        "__all__::landscape", "__all__::portrait"]


def test_a_video_asked_for_in_origenerator_mode_is_made_while_both_regions_play(
        qtbot, tmp_path, monkeypatch):
    client = _reroll_client()
    view = GalleryView(Database(tmp_path / "test.db"), fun_time=_session(), client=client)
    qtbot.addWidget(view)
    _a_library_of_each_shape(view, tmp_path, monkeypatch)
    open_both_sides(view)
    for side in ("portrait", "landscape"):
        qtbot.addWidget(view.region_slideshow(side).shown)

    i2v = WORKFLOW_REGISTRY["wan22_i2v"]
    video = view._jobs.start_prepared("k", i2v, i2v.default_params())

    assert [call.args[1] for call in client.submit_job.call_args_list] == [video]


def test_a_key_can_name_a_place_and_a_shape_at_once(qtbot, tmp_path):
    """``__all__::portrait`` is the whole library narrowed to one shape, and it
    stays re-askable: the base state holds the key rather than the rows, so a
    region asked again after a generation lands sees the new item too."""
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
    # And the two halves are the whole of it — there is no un-sided All to ask.
    assert set(portrait) | set(landscape) == {"p-1", "l-1"}


def test_reset_puts_a_region_back_on_the_library_not_on_its_own_folder(
        qtbot, tmp_path, monkeypatch):
    """Reset means on a slideshow what it means on a Funestra: the narrowing comes off
    and the side goes back to browsing its whole library.  A slideshow started on
    one folder therefore leaves that folder — restarting it would be the one
    thing reset is not."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(5)]
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in base]
                                     if key == "__all__::portrait" else []))
    _open_slideshow(view, monkeypatch, tmp_path, "folder", 100, 200, count=2)
    # _open_slideshow stubs the items for the folder it opened; from here the
    # rows the library hands back are the items.
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    assert slideshow.pass_size() == 2      # the folder it was started on
    view._slideshows._live_slideshows = [(slideshow, "folder-a")]

    slideshow.shown.press("portrait_reset")

    assert slideshow.pass_size() == len(base)   # the library of its shape
    assert slideshow.hud_order_label == "Shuffle"
    # And it is fed from the library now, not from the folder it left.
    assert [where for _slideshow, where in view._slideshows._live_slideshows] == ["__all__::portrait"]


def test_latest_on_a_hosted_slideshows_panel_plays_its_side_newest_first(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    newest_first = [(str(tall), "image", f"new-{n}", str(tall)) for n in range(4)]
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: ([_row_of(item) for item in newest_first]
                                     if key == "__recents__::portrait" else []))
    _open_slideshow(view, monkeypatch, tmp_path, "folder", 100, 200, count=2)
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
    """Standalone there is no base state to go back to, so reset is the slideshow's
    own: F-mode off, the hold released, the top of its set on screen."""
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    slideshow._set.playlist.jump_to(1)
    slideshow.slideshow_toggle_lock()

    slideshow.slideshow_reset()

    assert slideshow._set.playlist.index == 0
    assert slideshow.locked is False
    assert slideshow.pass_size() == 3


def _a_looping_clip(tmp_path):
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


def _moving_pictures(view):
    return [label for label in view.findChildren(QLabel)
            if label.movie() is not None
            and label.movie().state() == QMovie.MovieState.Running]


def test_omnipause_leaves_nothing_moving_anywhere_in_the_window(qtbot, tmp_path):
    """Swept rather than listed: after the freeze, no movie under this window is
    running — the grid tiles, the collections, a tab's history strip, the "Animated
    in" strip, the info pane's own animated still.

    Written this way because the listed version was wrong three times over: the
    tiles were wired to OmniPause and the other three kinds of looping preview
    were not, so a frozen room went on playing and nothing in the suite noticed.
    A sweep cannot miss the fourth one, and it fails the moment someone adds a
    fifth that does not go through looping_preview.
    """
    rows, webp = _a_looping_clip(tmp_path)
    view = _fun_time_view(qtbot, rows)
    view.animated_preview = lambda row: str(webp)
    view.refresh()
    view._tree.setCurrentItem(view._tree_view.leaf_by_id["v-1"])
    assert _moving_pictures(view), "nothing was moving, so the sweep would prove nothing"

    view.set_room_paused(True)

    assert _moving_pictures(view) == []

    view.set_room_paused(False)
    assert _moving_pictures(view)


def test_omnipause_reaches_a_slideshow_the_region_map_does_not_answer_for(
        qtbot, tmp_path, monkeypatch):
    """The freeze is fanned out over the slideshows this window has OPEN, not over
    the ones the region map calls visible.

    A slideshow the session has covered or parked is still a slideshow, and one that went
    on advancing through a frozen room is the room not being frozen.  The map
    answers ``None`` for anything it does not consider visible, so reading the
    freeze off it left exactly those slideshows running.
    """
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows._live_slideshows[0][0]
    qtbot.addWidget(slideshow.shown)
    monkeypatch.setattr(view, "region_slideshow", lambda side: None)

    view.set_room_paused(True)

    assert slideshow.shown._paused is True
    assert not _will_move_on(slideshow)


def test_a_frozen_slideshow_does_not_walk_past_an_unplayable_clip(qtbot, tmp_path, monkeypatch):
    """Stepping past a clip that will not play is right while the slideshow is
    running and wrong while the room is held: a slideshow hunting through its set for
    something playable is the room moving during OmniPause."""
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    view.set_room_paused(True)
    at = slideshow._set.playlist.index

    engine_of(slideshow.shown).idle = True
    slideshow.shown._pane.tick()

    assert slideshow._set.playlist.index == at


def test_a_portrait_picture_stands_beside_the_form_when_hosted(qtbot):
    """In the RFB's upright column a portrait picture stacked over the settings
    pushes every prompt field off the foot, so the two go side by side —
    settings left, picture right, the order they are read in."""
    panel = GenerateConfigPanel(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(panel)
    assert panel._media_split.orientation() == Qt.Orientation.Vertical

    panel._preview._pixmap = QPixmap(400, 900)   # taller than it is wide
    panel._reflow_for_the_media()

    assert panel._media_split.orientation() == Qt.Orientation.Horizontal
    assert panel._media_split.indexOf(panel._settings_pane) == 0    # settings lead
    assert panel._media_split.indexOf(panel._preview_pane) == 1


def test_a_landscape_picture_stays_stacked_when_hosted(qtbot):
    """A wide picture beside a form gets a column too narrow to show it, and the
    form loses the width its prompt fields need."""
    panel = GenerateConfigPanel(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(panel)

    panel._preview._pixmap = QPixmap(1200, 700)
    panel._reflow_for_the_media()

    assert panel._media_split.orientation() == Qt.Orientation.Vertical
    assert panel._media_split.indexOf(panel._preview_pane) == 0


def test_a_panel_taken_into_a_session_stands_its_portrait_picture_beside_the_form(qtbot):
    panel = GenerateConfigPanel(None, FakeDB([]))
    qtbot.addWidget(panel)
    panel._preview._pixmap = QPixmap(400, 900)
    panel._reflow_for_the_media()

    panel.become_hosted(_session())

    assert panel._media_split.orientation() == Qt.Orientation.Horizontal
    assert panel._media_split.indexOf(panel._settings_pane) == 0


def test_a_panel_handed_back_from_a_session_stacks_its_portrait_picture_over_the_form(qtbot):
    panel = GenerateConfigPanel(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(panel)
    panel._preview._pixmap = QPixmap(400, 900)
    panel._reflow_for_the_media()

    panel.become_standalone()
    panel.refresh_media_layout()

    assert panel._media_split.orientation() == Qt.Orientation.Vertical
    assert panel._media_split.indexOf(panel._preview_pane) == 0


def test_a_picture_back_from_beside_the_form_takes_the_larger_share_again(qtbot):
    """A landscape picture after a portrait one in the same tab came back with
    a third of the column where a fresh tab gives it two thirds, and so did
    every portrait tab a session handed back."""
    panel = GenerateConfigPanel(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(panel)
    panel.resize(600, 1000)
    panel._preview._pixmap = QPixmap(1200, 700)
    panel.show()
    qtbot.wait(1)

    panel._preview._pixmap = QPixmap(400, 900)
    panel._reflow_for_the_media()
    panel._preview._pixmap = QPixmap(1200, 700)
    panel._reflow_for_the_media()
    qtbot.wait(1)

    picture, settings = panel._media_split.sizes()
    assert picture > settings


def test_tabs_taken_into_a_session_lay_out_the_tabs_they_have_and_the_ones_opened_after(qtbot):
    tabs = InfoPaneTabs(None, FakeDB([]))
    qtbot.addWidget(tabs)
    first = tabs.currentWidget()
    first._preview._pixmap = QPixmap(400, 900)

    tabs.become_hosted(_session())
    later = tabs._add_subtab()
    later._preview._pixmap = QPixmap(400, 900)
    later.refresh_media_layout()

    assert first._media_split.orientation() == Qt.Orientation.Horizontal
    assert later._media_split.orientation() == Qt.Orientation.Horizontal


def test_tabs_handed_back_from_a_session_stack_the_tabs_they_have_and_the_ones_opened_after(qtbot):
    tabs = InfoPaneTabs(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tabs)
    first = tabs.currentWidget()
    first._preview._pixmap = QPixmap(400, 900)
    first.refresh_media_layout()

    tabs.become_standalone()
    later = tabs._add_subtab()
    later._preview._pixmap = QPixmap(400, 900)
    later.refresh_media_layout()

    assert first._media_split.orientation() == Qt.Orientation.Vertical
    assert later._media_split.orientation() == Qt.Orientation.Vertical


def test_a_gallery_taken_into_a_session_stands_as_a_hosted_one_is_built(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    view.become_hosted(_session())

    built = _fun_time_view(qtbot)
    assert (view._bank.radio, view._bank.mic) == (None, None)
    assert (view._osr2_motion, view._osr2_driver, view._motion_panel) == (None, None, None)
    assert not view.osr2_control.isEnabled() and not built.osr2_control.isEnabled()
    assert view._motion_pane.isHidden()
    stack = view._arrangement.stack
    assert stack.orientation() == Qt.Orientation.Vertical
    assert stack.count() == built._arrangement.stack.count() == 3
    assert stack.widget(0).findChild(type(view._info_tabs)) is view._info_tabs
    assert stack.widget(1) is view._arrangement.panes
    assert stack.widget(2) is view._queue
    assert view._arrangement.panes.count() == built._arrangement.panes.count()
    assert view._arrangement.panes.widget(1) is view._arrangement.folder_panes
    assert view._arrangement.folder_panes.count() == built._arrangement.folder_panes.count()


def test_a_gallery_driving_the_device_lets_go_of_it_as_a_session_takes_it_over(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), osr2_motion=motion)
    qtbot.addWidget(view)
    view.osr2_control.setChecked(True)
    assert motion.active

    view.become_hosted(_session())

    assert not motion.active
    assert motion.calls[-1] == ("stop",)


def test_a_gallery_a_session_never_took_over_stands_off_the_device_all_the_same(qtbot):
    # The takeover can miss -- a window still booting when the room opened, an
    # offer a second instance overwrote -- and a window that kept its switch
    # keeps streaming into the one device the session is driving.

    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), osr2_motion=motion)
    qtbot.addWidget(view)
    view.osr2_control.setChecked(True)

    view.osr2_control.the_session_has_it(True)

    assert not motion.active
    assert not view.osr2_control.isEnabled()
    view.toggle_osr2_drive()
    assert not motion.active


def test_a_gallery_drives_again_once_the_session_beside_it_lets_the_device_go(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), osr2_motion=motion)
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
    info_pane = arrangement.panes.widget(1)
    assert info_pane.findChild(type(view._info_tabs)) is view._info_tabs
    assert info_pane.minimumWidth() == view._info_tabs.minimumWidth() == 0
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
    hosted = view._tree.sides
    view.become_standalone()

    assert (hosted, view._tree.sides) == (SEPARATE, TOGETHER)


def test_a_gallery_handed_back_from_a_session_drives_its_own_device_again(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), osr2_motion=motion)
    qtbot.addWidget(view)
    view.become_hosted(_session())

    view.become_standalone()
    view.osr2_control.setChecked(True)

    assert motion.active
    assert view._motion_panel is not None and not view._motion_pane.isHidden()


def test_a_gallery_handed_back_from_a_session_answers_its_switch_words_itself_again(qtbot):
    radio = _FakeRadio()
    view = GalleryView(FakeDB([]), radio=radio)
    qtbot.addWidget(view)
    view.become_hosted(_session())

    view.become_standalone()
    view._voice.on_command(AppCommand.RADIO_ON)

    assert view._bank.radio.isChecked() and radio.starts == 1


def test_a_gallery_handed_back_from_a_session_opens_its_next_slideshow_over_the_monitor(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.become_hosted(_session())

    view.become_standalone()
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)

    slideshow = view._slideshows.showing
    assert slideshow is not None
    qtbot.addWidget(slideshow.shown)
    assert view.region_slideshow("portrait") is None
    assert slideshow.shown.isFullScreen()


def test_a_gallery_handed_back_from_a_frozen_session_lets_its_pictures_move_again(qtbot, tmp_path):
    rows, webp = _a_looping_clip(tmp_path)
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.animated_preview = lambda row: str(webp)
    view.refresh()
    view._tree.setCurrentItem(view._tree_view.leaf_by_id["v-1"])
    view.become_hosted(_session())
    view.set_room_paused(True)

    view.become_standalone()

    assert _moving_pictures(view)


def test_a_gallery_taken_into_a_session_stops_the_sound_device_and_mic_it_ran(qtbot):
    radio, motion = _FakeRadio(), _SignalMotion()
    view = GalleryView(FakeDB([]), radio=radio, osr2_motion=motion)
    qtbot.addWidget(view)
    view._bank.radio.setChecked(True)
    view.osr2_control.setChecked(True)
    view._bank.mic.setChecked(True)
    listener = view._voice.listener
    assert motion.active and listener.commands_on

    view.become_hosted(_session())

    assert radio.stops == 1
    assert not motion.active
    assert not listener.commands_on


def test_a_gallery_taken_into_a_session_opens_its_next_slideshow_on_a_region(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    view.become_hosted(_session())
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)

    slideshow = view.region_slideshow("portrait")
    assert slideshow is not None
    qtbot.addWidget(slideshow.shown)
    assert slideshow.shown.windowTitle() == "Origenerator Portrait"


def test_a_slideshow_up_when_the_gallery_is_taken_into_a_session_goes_on_on_its_shapes_side(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([_row(f"id-tall-{n}", "sdxl_t2i", {"width": 832, "height": 1216},
                                    f"tall{n}.png") for n in range(2)]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=2)
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view.slideshow_showing_on() == "portrait"

    view.become_hosted(_session())
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: [])
    open_both_sides(view._slideshows)

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
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100, count=2)
    qtbot.addWidget(view._slideshows.showing.shown)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=2)

    view.become_hosted(_session())
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: [])
    open_both_sides(view._slideshows)

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
    open_both_sides(view._slideshows)

    carried = {side: view.region_slideshow(side) for side in ("portrait", "landscape")}
    for slideshow in carried.values():
        qtbot.addWidget(slideshow.shown)
    assert [slide.prompt_id for slide in carried["portrait"].whole_set()] == [
        "id-tall-0", "id-tall-2"]
    assert [slide.prompt_id for slide in carried["landscape"].whole_set()] == ["id-wide-1"]


def test_a_gallery_taken_into_a_session_leaves_its_spoken_motion_words_to_the_session(qtbot):
    motion = _SignalMotion()
    view = GalleryView(FakeDB([]), osr2_motion=motion)
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
    """Inside a session the borders between the panes could not be moved, and
    the pointer still turned into a resize arrow over them. Held, a border takes
    no drag and keeps the ordinary pointer (tests/test_panes.py)."""
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


def test_a_tab_opened_in_a_session_holds_its_border_still(qtbot):
    view = _fun_time_view(qtbot)

    opened = view._info_tabs._add_subtab()

    assert not opened._media_split.handle(1).isEnabled()


def test_a_gallery_taken_into_a_session_stands_its_open_portrait_tab_beside_the_form(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    tab = view._info_tabs.current_config_panel()
    tab._preview._pixmap = QPixmap(400, 900)

    view.become_hosted(_session())

    assert tab._media_split.orientation() == Qt.Orientation.Horizontal


def test_a_gallery_handed_back_from_a_session_stacks_its_open_portrait_tab_again(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    tab = view._info_tabs.current_config_panel()
    tab._preview._pixmap = QPixmap(400, 900)
    view.become_hosted(_session())

    view.become_standalone()

    assert tab._media_split.orientation() == Qt.Orientation.Vertical


def test_standalone_never_stands_them_side_by_side(qtbot):
    """The pane is wide there; stacking is right at any shape."""
    panel = GenerateConfigPanel(None, FakeDB([]))
    qtbot.addWidget(panel)

    panel._preview._pixmap = QPixmap(400, 900)
    panel._reflow_for_the_media()

    assert panel._media_split.orientation() == Qt.Orientation.Vertical


def test_a_tab_coming_to_the_front_lays_out_for_its_own_picture(qtbot):
    """The shape belongs to the tab, so switching to one holding a landscape
    picture stands the panes back up — without waiting for something else to
    nudge the splitter, which is all that used to bring them back."""
    tabs = InfoPaneTabs(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tabs)
    portrait_tab = tabs.currentWidget()
    portrait_tab._preview._pixmap = QPixmap(400, 900)
    portrait_tab.refresh_media_layout()
    assert portrait_tab._media_split.orientation() == Qt.Orientation.Horizontal

    # A second tab holding a landscape picture; switching to it stands it up.
    tabs._add_subtab()
    landscape_tab = tabs.currentWidget()
    landscape_tab._preview._pixmap = QPixmap(1200, 700)
    tabs.setCurrentWidget(portrait_tab)
    tabs.setCurrentWidget(landscape_tab)

    assert landscape_tab._media_split.orientation() == Qt.Orientation.Vertical


def _hud_label_for(view):
    """What the slideshows' HUD calls each item, as the director hands it over."""
    worn = {}

    class _Slideshow:
        def wear_the_hud(self, side, **furnishings):
            worn.update(furnishings)

    view._slideshows._wear_the_hud(_Slideshow(), "landscape")
    return worn["label_for"]


def test_the_slideshows_hud_names_the_item_the_way_this_app_does(qtbot):
    """By the name its tile in the browser and its tab both wear, never the
    disk's "image / ComfyUI_00123_", a media type and a counter that appear
    nowhere in this UI."""
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
    """The two filters a slideshow has are the two switches its HUD carries: F-mode
    over the favorites, and beside it the switch keeping only the pictures the
    slideshow has enhanced.  A press lands on the slideshow itself, hosted like standalone
    — it is the slideshow's own narrowing, not the session's — and the title
    names the cut beside the rest."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_enhanced_ids_of", lambda rows: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    names = hud_button_names(slideshow.shown)
    assert names.index("enhanced") == names.index("fmode") + 1

    slideshow.shown.press("portrait_enhanced")

    assert slideshow.hud_enhanced_mode is True
    assert slideshow.pass_size() == 1          # narrowed to the one enhanced
    model = slideshow_hud_model("portrait", slideshow)
    assert _lit(model, "portrait_enhanced") and "Enhanceds" in model.title
    # Nothing went out on the session's channel: the switch is the slideshow's own.
    assert not (tmp_path / "dashboard_cmd.txt").exists()

    slideshow.shown.press("portrait_enhanced")
    assert slideshow.pass_size() == 3          # widened back


def test_a_spoken_enhanced_only_narrows_the_named_regions_slideshow(qtbot, tmp_path, monkeypatch):
    """Hosted, the session hears "portrait enhanced only" and hands the words
    over; they turn that region's own switch, and "portrait clear filter" turns
    it — and F-mode — back off, which is what the phrase means on a satellite."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_enhanced_ids_of", lambda rows: {"id-tall-1"})
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id-tall-1", "id-tall-2"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)

    assert view.run_spoken_command("portrait enhanced only")
    assert slideshow.hud_enhanced_mode is True
    assert slideshow.pass_size() == 1

    assert view.run_spoken_command("portrait favorites")
    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_mode) == (True, True)

    assert view.run_spoken_command("portrait clear filter")
    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_mode) == (False, False)
    assert slideshow.pass_size() == 3


def test_a_regions_reset_drops_the_enhanced_switch_with_the_rest(qtbot, tmp_path, monkeypatch):
    """Reset puts the side back how it started, and the new switch is one more
    thing it drops — a reset that left the slideshow narrowed would not be one."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view._slideshows, "_enhanced_ids_of", lambda rows: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    slideshow = view._slideshows._region_slideshows["portrait"]
    qtbot.addWidget(slideshow.shown)
    slideshow.toggle_enhanced_mode()
    assert slideshow.hud_enhanced_mode is True

    slideshow.slideshow_reset()

    assert slideshow.hud_enhanced_mode is False
