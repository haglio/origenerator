from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

import pytest
from funestra.hud_placement import HudCorner
from funestra.hud_title import LATEST_LABEL
from PIL import Image
from PyQt6.QtCore import QRect, Qt

from origenerator import gallery, library_views
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    FolderCollection,
)
from origenerator.gallery.shapes import BOTH
from origenerator.generation_state import GenerationSource
from origenerator.gui import slideshow_director as module
from origenerator.gui.message import FAVORITE, INFO, WARNING
from origenerator.gui.slideshow_director import (
    Carrying,
    DirectorSources,
    DirectorSurroundings,
    SlideshowDirector,
)
from origenerator.gui.slideshow_pace import DEFAULT_S as DEFAULT_PACE_S
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_wiring import Listing
from origenerator.item_actions import ItemActions, actions_of, columns, stored
from origenerator.item_names import ItemNames
from origenerator.item_shape import shaped_key
from origenerator.library_views import LibrarySnapshot
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.slideshow import Slide, SlideshowFilters, SlideshowState
from origenerator.video_records import FiledLoops
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.slideshow_commands import SlideshowCommand
from tests.slideshow_hud_support import open_both_shapes

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
ALL_PORTRAIT = shaped_key(gallery.ALL_KEY, PORTRAIT)
_HELD_ON_G1 = SlideshowState(order=("g2", "g1"), current="g1", locked=True)
ALL_LANDSCAPE = shaped_key(gallery.ALL_KEY, LANDSCAPE)
LATEST_PORTRAIT = shaped_key(LATEST_KEY, PORTRAIT)
LATEST_LANDSCAPE = shaped_key(LATEST_KEY, LANDSCAPE)
PORTRAIT_MONITOR = QRect(2560, 0, 1440, 2560)
LANDSCAPE_MONITOR = QRect(0, 0, 2560, 1440)
HIS_TWO_MONITORS = [SimpleNamespace(geometry=lambda: LANDSCAPE_MONITOR),
                    SimpleNamespace(geometry=lambda: PORTRAIT_MONITOR)]
TALL = {"width": 832, "height": 1216}
WIDE = {"width": 1216, "height": 832}


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeSlideshow:
    def __init__(self, items=(), *, actions=None, pace=None, hud=None, versions=None, **kwargs):
        self.items = list(items)
        self.actions = actions
        self.pace = pace
        self.hud = hud
        self.shown = FakeSessionsFunestra()
        self.opened_with = kwargs
        self.open_requested = FakeSignal()
        self.closed = FakeSignal()
        self.media_changed = FakeSignal()
        self.added = []
        self.generating = []
        self.enhanced = []
        self.enhancing = None
        self.in_flight = None
        self.said = []
        self.said_kinds = []
        self.runs_said = []
        self.versions = versions
        self.resumed = None
        self.taken_up = None
        self.filters = SlideshowFilters()
        self.retuned = None
        self.reordered = None
        self.kept_the_slide = None
        self.dwell_s = 0
        self.paused = None
        self.closes = 0
        self.visible = True
        self.ids = set()
        self.hud_favorites_filter = False
        self.hud_enhanced_mode = self.hud_originals_mode = False
        self.enhanced_items, self.original_items = [], []
        self.steps = []
        self.culled = 0
        self.favoritable = True
        self.favorites = 0
        self.released = []
        self.versions_deleted = []
        self.pause_raises = False
        self.state_at_close = SlideshowState()
        self.played = []
        self.leads = 0
        self.follows = 0
        self.versions_added = []
        self.hud_order_label = ""
        self.locked_on = None
        self.shown_locked = []
        self.done = []
        self.has_osr2 = None
        self.transport = self

    def holds(self, prompt_id):
        return prompt_id in self.ids

    def state(self):
        return self.state_at_close

    def whole_set(self):
        return [Slide.of(item) for item in self.items]

    def is_showing(self):
        return self.visible

    def play(self, playing):
        self.items = list(playing.items)
        self.hud = playing.hud
        self.versions = playing.versions
        self.played.append(list(playing.items))
        self.played_with = {"start": playing.start, "shuffle": playing.shuffle}

    def set_versions(self, versions):
        self.versions = versions

    def resume(self, state, *, opened_on_it=False):
        self.resumed = state
        self.resumed_on_its_slide = opened_on_it

    def take_up(self, filters, *, keep_the_slide=False):
        self.taken_up = (filters, keep_the_slide)
        self.filters = filters
        self.hud_favorites_filter = filters.favorites
        self.hud_enhanced_mode = filters.enhanced

    def retune(self, items, *, enhanced_ids):
        self.retuned = (list(items), set(enhanced_ids))

    def reorder(self, items, *, latest, enhanced_ids, keep_slide=False):
        self.reordered = (list(items), latest, set(enhanced_ids))
        self.kept_the_slide = keep_slide

    def note_added(self, slide, *, favorite, enhanced):
        self.added.append((slide.prompt_id, favorite, enhanced))

    def note_generating(self, prompt_id, frame):
        self.generating.append((prompt_id, frame))

    def note_in_flight(self, keys):
        self.in_flight = set(keys)

    def note_enhanced(self, prompt_id, path, media_type, *, still):
        self.enhanced.append((prompt_id, media_type, still))

    def note_enhancing(self, statuses, frames=None):
        self.enhancing = dict(statuses)
        self.enhancing_frames = dict(frames or {})

    def lead_with_what_is_being_made(self):
        self.leads += 1

    def follow_what_is_being_made(self):
        self.follows += 1

    def add_versions(self, versions):
        self.versions_added.append(versions)

    def note_voice_command(self, message, *, kind=INFO):
        self.said.append(message)
        self.said_kinds.append(kind)

    def note_voice_run(self, prompt_id, message, *, kind=INFO):
        self.runs_said.append((prompt_id, message))

    def set_paused(self, paused):
        if self.pause_raises:
            raise RuntimeError("this slideshow will not freeze")
        self.paused = paused

    def set_has_osr2(self, has_it):
        self.has_osr2 = has_it

    def release_media(self, paths, *, the_item_stays=False):
        self.released.append((list(paths), the_item_stays))

    def note_versions_deleted(self, prompt_id, path, media_type, *, still, versions):
        self.versions_deleted.append((prompt_id, str(path), media_type, versions))

    def reset_in_place(self):
        self.retuned = "in place"

    def osr2_drive_target(self):
        return self.opened_with.get("drive_target")

    def toggle_favorites_filter(self):
        self.hud_favorites_filter = not self.hud_favorites_filter

    def set_favorites_filter(self, on):
        self.hud_favorites_filter = bool(on)
        return True

    def set_enhanced_mode(self, on):
        self.hud_enhanced_mode = on and bool(self.enhanced_items)
        return self.hud_enhanced_mode

    def show_originals_only(self):
        if not self.original_items:
            return False
        self.hud_enhanced_mode, self.hud_originals_mode = False, True
        return True

    def show_enhanced_and_original(self):
        narrowed = self.hud_enhanced_mode or self.hud_originals_mode
        self.hud_enhanced_mode = self.hud_originals_mode = False
        return narrowed

    @property
    def action_presses(self):
        return self

    def clear_filter(self):
        self.filters = replace(self.filters, action="")

    def pass_size(self):
        return len(self.original_items if self.hud_originals_mode else self.enhanced_items)

    def slideshow_step(self, delta):
        self.steps.append(delta)

    def cull(self):
        self.culled += 1
        self.done.append(("cull",))

    def favorite(self):
        self.favorites += 1
        self.done.append(("favorite",))
        return self.favoritable

    def set_locked(self, locked):
        self.done.append(("lock", locked))
        return locked

    def back_to_what_was_said_over(self, said_at):
        self.done.append(("back to", said_at))

    def show_locked(self, path):
        self.shown_locked.append(path)

    def close(self):
        self.closes += 1
        self.visible = False
        self.closed.emit(self)


class FakeSessionsFunestra:
    def __init__(self) -> None:
        self.queue_set = None

    def set_queue(self, items, foreign_total):
        self.queue_set = (list(items), foreign_total)


class FakeWindow:
    def __init__(self, slideshow, *, motion=None):
        self.slideshow = slideshow
        slideshow.shown = self
        self.motion = motion
        self.queue_set = None
        self.audio_muted = None
        self.window_title = None
        self.window_flags = Qt.WindowType.Widget
        self.geometry = None
        self.raised = 0
        self.activated = 0
        self.shows = 0
        self.fullscreen = 0
        self.full_screen = False
        self.minimized = False
        self.monitor = LANDSCAPE_MONITOR

    def set_queue(self, items, foreign_total):
        self.queue_set = (list(items), foreign_total)

    def set_audio_muted(self, muted):
        self.audio_muted = muted

    def showFullScreen(self):
        self.fullscreen += 1
        self.minimized = False
        self.full_screen = True

    def showNormal(self):
        self.full_screen = False

    def isFullScreen(self):
        return self.full_screen

    def isMinimized(self):
        return self.minimized

    def show(self):
        self.shows += 1

    def setWindowTitle(self, title):
        self.window_title = title

    def windowFlags(self):
        return self.window_flags

    def setWindowFlags(self, flags):
        self.window_flags = flags

    def setGeometry(self, x, y, width, height):
        self.geometry = (x, y, width, height)
        self.monitor = QRect(x, y, width, height)

    def winId(self):
        return 4242

    def screen(self):
        return SimpleNamespace(geometry=lambda: self.monitor)

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        self.activated += 1


class FakeRect:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


class FakeSession:
    dashboard_cmd_file = None

    def __init__(self, funestras=None):
        self.funestras = funestras or {}

    def region_rect(self, shape):
        return FakeRect(0 if shape == LANDSCAPE else 1920, 0, 960, 540)

    def funestra(self, shape):
        return self.funestras.get(shape)


class FakeJobQueue:
    def __init__(self):
        self.moved = []

    def move(self, key, before):
        self.moved.append((key, before))


class FakeGalleryPane:
    def __init__(self, collections=None, latest=False, searching=False):
        self.collections = collections or {}
        self.latest = latest
        self.searching = searching
        self.library = None


class FakeLibrary(LibrarySnapshot):
    def __init__(self, db, host, at=None):
        super().__init__([])
        self._db = db
        self._host = host
        self.at = {} if at is None else at
        self.asked = 0

    @property
    def rows(self):
        return list({row["prompt_id"]: row
                     for row in (*self._db.rows.values(), *self._host.rows)}.values())

    @property
    def image_index(self):
        return gallery.start_frame_index(self.rows)

    @image_index.setter
    def image_index(self, _index):
        pass

    @rows.setter
    def rows(self, _rows):
        pass

    @property
    def rows_by_id(self):
        return {row["prompt_id"]: row for row in self.rows}

    def on_the_map(self, shape):
        return LibrarySnapshot(self.rows).on_the_map(shape)

    def rows_at(self, key):
        self.asked += 1
        return list(self.at.get(key, []))


class FakeDB:
    def __init__(self, rows=(), requests=()):
        self.rows = {row["prompt_id"]: row for row in rows}
        self.requests = {record["prompt_id"]: record for record in requests}
        self.listings = 0
        self.gets = 0

    def get_request(self, prompt_id):
        return self.requests.get(prompt_id)

    def list_generations(self):
        self.listings += 1
        return list(self.rows.values())

    def get_generation(self, prompt_id):
        self.gets += 1
        return self.rows.get(prompt_id)

    def set_actions(self, prompt_id, side, labels):
        self.rows[prompt_id].update(zip(columns(side), stored(labels), strict=True))

    def folder_meta_map(self):
        return {}


class FakeHost:
    def __init__(self, *, location=None, rows=(), groups=None):
        self.location = location
        self.rows = list(rows)
        self.groups = groups or {}
        self.said = []
        self.followed = []
        self.shown = []
        self.revealed = []
        self.trashed = []
        self.favorited = []
        self.enhanced = []
        self.drive_toggles = 0
        self.reconciles = 0
        self.room_paused = []
        self.cleared_queue = 0
        self.started_now = 0
        self.cancelled_all = 0
        self.queue = ([], 0)
        self.core = object()
        self.visible = [row["prompt_id"] for row in self.rows]
        self.picked = []
        self.holding = None
        self.latest = False
        self.reread = 0

    def refresh(self):
        self.reread += 1

    def listing(self):
        return Listing(location=self.location, rows=tuple(self.rows), shown=tuple(self.visible),
                       picked=tuple(self.picked), shape=LANDSCAPE, latest=self.latest)

    def queue_now(self):
        return self.queue

    def off_thread(self, work, done):
        if self.holding is None:
            done(work())
        else:
            self.holding.append(lambda: done(work()))

    def window(self):
        return self.core

    def clear_foreign_queue(self):
        self.cleared_queue += 1

    def start_now(self):
        self.started_now += 1

    def cancel_all(self):
        self.cancelled_all += 1

    def follow_link(self, prompt_id):
        self.followed.append(prompt_id)

    def show_generation(self, prompt_id):
        self.shown.append(prompt_id)

    def reveal(self, prompt_id):
        self.revealed.append(prompt_id)
        return prompt_id in self.visible

    def trash_generation(self, prompt_id):
        self.trashed.append(prompt_id)

    def favorite_generation(self, prompt_id, favorite=True):
        if favorite:
            self.favorited.append(prompt_id)
        else:
            self.favorited.remove(prompt_id)

    def enhance_from_slideshow(self, prompt_id):
        self.enhanced.append(prompt_id)
        return True

    osr2_control = None

    def toggle_osr2_drive(self):
        self.drive_toggles += 1

    def reconcile_osr2(self):
        self.reconciles += 1

    def set_room_paused(self, paused):
        self.room_paused.append(paused)
        self.slideshows.set_room_paused(paused)

    def say(self, message):
        self.said.append(message)


def test_asking_whether_anything_can_play_stops_at_the_first_item(slideshows, monkeypatch):
    director, _host, _made = slideshows(FakeHost(rows=[_row(f"g{n}") for n in range(50)]))
    del director.items_of
    read = []

    def resolve(row, _output_dir):
        read.append(row["prompt_id"])
        return (f"{row['prompt_id']}.png", "image")

    monkeypatch.setattr(module.gallery, "resolve_preview", resolve)

    assert director.anything_to_play()
    assert read == ["g0"], (
        "reading every row's files to answer it is what made one click on the TOC redraw for "
        "seconds")


def test_asking_whether_anything_can_play_lists_no_folder_of_upscales(slideshows, monkeypatch):
    director, _host, _made = slideshows(FakeHost(rows=[_row("g0")]))
    del director.items_of
    monkeypatch.setattr(module.gallery, "resolve_preview",
                        lambda row, _places: (f"{row['prompt_id']}.png", "image"))
    scanned = []
    monkeypatch.setattr(library_views.EvolverUpscales, "scan",
                        lambda *args: scanned.append(args) or library_views.EvolverUpscales({}))

    assert director.anything_to_play()
    assert scanned == [], (
        "an upscale changes which file a slide plays, never whether there is one, and every click "
        "in the TOC asks this several times over")


def _row(prompt_id, *, workflow_name="sdxl_t2i", favorite=False, params=None,
         files=("one.png",)):
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "workflow": workflow_name,
        "starred": favorite,
        "source": "generated",
        "params": json.dumps(params or {}),
        "output_files": json.dumps([{"filename": name} for name in files]),
        "thumbnail_path": None,
    }


@pytest.fixture
def slideshows(monkeypatch):
    made = []

    def build_slideshow(items, **kwargs):
        slideshow = FakeSlideshow(items, **kwargs)
        made.append(slideshow)
        return slideshow

    def build_window(items, show, wiring):
        return FakeWindow(build_slideshow(items, **vars(show)), motion=wiring.motion)

    def build_funestra_slideshow(playing, seat, hosting):
        return build_slideshow(
            playing.items, actions=playing.actions, hud=playing.hud, versions=playing.versions,
            opening=playing.opening, start=playing.start, shuffle=playing.shuffle,
            shape=seat.shape, channel=seat.channel, frames=seat.frames,
            pace=hosting.pace, say=hosting.say)

    monkeypatch.setattr(module, "SlideshowView", build_window)
    monkeypatch.setattr(module, "FunestraSlideshow", build_funestra_slideshow)
    monkeypatch.setattr(module.SlideshowDirector, "_wear_the_hud", lambda self, view, shape: None)
    monkeypatch.setattr(module, "place_window_in_device_pixels",
                        lambda *args: None)
    monkeypatch.setattr(module, "_screens", list)

    def build(host=None, *, db=None, gallery_pane=None, fun_time=None, records=None):
        host = host or FakeHost()
        db = db or FakeDB()
        gallery_pane = gallery_pane or FakeGalleryPane()
        gallery_pane.collections.update(
            {key: gallery.rows_under(group) for key, group in host.groups.items()})
        gallery_pane.library = FakeLibrary(db, host, gallery_pane.collections)
        host.latest = gallery_pane.latest and not gallery_pane.searching
        director = SlideshowDirector(
            host,
            DirectorSources(db=db, jobs=FakeJobQueue(), names=ItemNames(db),
                            library=lambda: gallery_pane.library, listing=host.listing,
                            **({"weight_of": records.of, "learn_weights": records.learn,
                                "record_group_of": records.group_of,
                                "record_loops_of": records.loops_of}
                               if records else {})),
            DirectorSurroundings(pace=SlideshowPace(), motion=None, fun_time=fun_time))
        host.slideshows = director
        director.items_of = lambda rows: [
            (f"{r['prompt_id']}.png", "image", r["prompt_id"], None) for r in rows]
        return director, host, made
    return build


def test_a_slideshow_is_remembered_with_the_place_it_opened_from(slideshows):
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], location="workflow/a")

    assert director.showing is made[0]
    assert director._live_slideshows == [(made[0], "workflow/a")]


def test_the_last_slideshow_closing_leaves_nothing_showing(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].close()

    assert director.showing is None


def test_asking_for_a_second_slideshow_standalone_replays_the_one_already_up(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)], location="collection/a")

    again = director.open([("b.png", "image", "g2", None)], location="collection/b")

    assert made == [again]
    assert again.played == [[("b.png", "image", "g2", None)]]
    assert director._live_slideshows == [(again, "collection/b")]


def test_a_double_clicked_item_plays_its_folder_newest_first_and_says_latest(slideshows):
    host = FakeHost(rows=[_row("a2"), _row("a1")])
    host.visible = ["a2", "a1"]
    director, _host, made = slideshows(host)

    director.open_in_its_folder(("a2.png", "image"), "a2")

    (slideshow,) = made
    assert slideshow.hud.order_label == LATEST_LABEL


def test_a_double_clicked_item_s_slideshow_opens_on_it_before_the_rest_of_its_folder_is_ready(
        slideshows):
    host = FakeHost(rows=[_row("a3"), _row("a2"), _row("a1")])
    host.holding = []
    director, _host, made = slideshows(host)

    director.open_in_its_folder(("a2.png", "image"), "a2")

    assert [item[2] for item in made[0].items] == ["a2"], (
        "worked out whole before anything showed, a folder of thousands held its slideshow back "
        "for a second or more")
    (fill_in,) = host.holding
    fill_in()
    assert [item[2] for item in made[0].items] == ["a3", "a2", "a1"]
    assert made[0].played_with["start"] == 1


def test_a_double_clicked_item_plays_the_rows_the_gallery_pane_listed_without_reading_each_again(
        slideshows):
    rows = [_row("a2"), _row("a1")]
    db = FakeDB(rows)
    director, _host, made = slideshows(FakeHost(rows=rows), db=db)

    director.open_in_its_folder(("a2.png", "image"), "a2")

    assert [item[2] for item in made[0].items] == ["a2", "a1"]
    assert db.gets == 0


def test_a_double_clicked_item_s_slideshow_finds_its_files_by_listing_their_folder(
        slideshows, monkeypatch, tmp_path):
    for n in range(3):
        (tmp_path / f"g{n}.png").write_bytes(b"x")
    monkeypatch.setattr(library_views, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    rows = [_row(f"g{n}", files=(f"g{n}.png",)) for n in range(3)]
    director, _host, made = slideshows(FakeHost(rows=rows))
    del director.items_of

    def refused(asking):
        def ask(path):
            if tmp_path in path.parents:
                pytest.fail(f"asked after {path.name} alone")
            return asking(path)
        return ask

    with monkeypatch.context() as asked:
        asked.setattr(Path, "exists", refused(Path.exists))
        asked.setattr(Path, "is_file", refused(Path.is_file))
        director.open_in_its_folder((str(tmp_path / "g1.png"), "image"), "g1")

    assert [item[2] for item in made[0].items] == ["g0", "g1", "g2"]


def test_a_double_clicked_item_s_slideshow_takes_the_shape_its_rows_say_opening_no_file(
        slideshows, monkeypatch):
    rows = [_shaped("g1", TALL), _shaped("g2", TALL), _shaped("g3", WIDE)]
    director, _host, made = slideshows(FakeHost(rows=rows))
    monkeypatch.setattr(module, "region_for_items",
                        lambda items: pytest.fail("a file was opened to measure it"))

    director.open_in_its_folder(("g3.png", "image"), "g3")

    assert made[0].opened_with["shape"] == PORTRAIT


def test_a_slideshow_put_back_goes_on_taking_in_what_lands_where_it_plays(slideshows):
    landed = _row("g2")
    director, _host, made = slideshows(gallery_pane=FakeGalleryPane(collections={"collection/a": [_row("g1"), landed]}))
    director.open([("g1.png", "image", "g1", None)], location="collection/a")
    made[0].dwell_s = 4
    held = director.held_slideshow()
    made[0].close()

    again = director.put_back(held)
    director.note_finished(landed)

    assert again is not made[0]
    assert again.added == [("g2", False, False)]


def _request(prompt_id, asked_of, asked="two dogs"):
    return {"prompt_id": prompt_id, "source_prompt_id": asked_of, "heard": "", "asked": asked}


def test_a_request_landing_shows_on_a_slideshow_still_locked_on_what_it_was_asked_of(
        slideshows):
    asked_for = _row("g2")
    director, _host, made = slideshows(
        db=FakeDB([_row("g1"), asked_for], requests=[_request("g2", "g1")]))
    director.open([("g1.png", "image", "g1", None)], location="collection/a")
    made[0].locked_on = "g1"

    director.note_finished(asked_for)

    assert made[0].shown_locked == ["g2.png"]


def test_a_request_landing_leaves_a_slideshow_that_moved_off_what_it_was_asked_of(
        slideshows):
    asked_for = _row("g2")
    director, _host, made = slideshows(
        db=FakeDB([_row("g1"), asked_for], requests=[_request("g2", "g1")]))
    director.open([("g1.png", "image", "g1", None)], location="collection/a")
    made[0].locked_on = None

    director.note_finished(asked_for)

    assert made[0].shown_locked == []


def test_a_folder_s_modify_batch_landing_leaves_a_slideshow_locked_on_its_original(slideshows):
    modified = _row("g2")
    director, _host, made = slideshows(
        db=FakeDB([_row("g1"), modified], requests=[_request("g2", "g1", asked="")]))
    director.open([("g1.png", "image", "g1", None)], location="collection/a")
    made[0].locked_on = "g1"

    director.note_finished(modified)

    assert made[0].shown_locked == []


def test_a_double_click_on_an_item_no_folder_lists_still_names_its_generation(slideshows):
    host = FakeHost(rows=[_row("a1"), _row("t1")])
    host.visible = ["a1"]
    director, _host, made = slideshows(host)
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}

    director.open_on_preview(("t1.png", "image"), "t1")

    (slideshow,) = made
    assert slideshow.items == [("t1.png", "image", "t1", None)]
    assert slideshow.versions == {"t1.png": ["newer", "older"]}


def test_one_of_two_hosted_slideshows_closing_leaves_the_other_showing(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    made[1].close()

    assert director.showing is made[0]


def test_what_the_session_says_of_a_shapes_osr2_reaches_the_slideshow_there_whenever_it_opens(
        slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.tell_the_hud(PORTRAIT, "osr2", "1")

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    director.open([("b.png", "image", "g2", None)], shape=LANDSCAPE)
    assert [slideshow.has_osr2 for slideshow in made] == [True, False]

    director.tell_the_hud(PORTRAIT, "osr2", "0")

    assert made[0].has_osr2 is False


def test_a_director_taken_into_a_session_closes_its_fullscreen_slideshow_for_the_regions(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.become_hosted(FakeSession())
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    assert made[0].closes == 1
    assert director.region_slideshow(PORTRAIT) is made[1]
    assert made[1].shown.fullscreen == 0


def _shaped(prompt_id, params):
    return {**_row(prompt_id), "params_json": json.dumps(params)}


def _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, *, shape=PORTRAIT, shapes=(TALL, TALL), monitor=PORTRAIT_MONITOR,
        standing=_HELD_ON_G1):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    rows = [_shaped(f"g{n}", params) for n, params in enumerate(shapes, start=1)]
    director, _host, made = slideshows(FakeHost(rows=rows), gallery_pane=gallery_pane)
    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, shape=shape, location="collection/a")
    watched = made[0]
    watched.shown.monitor = monitor
    watched.state_at_close = standing
    watched.filters = SlideshowFilters(favorites=True)
    director.become_hosted(FakeSession())
    return director, watched


def test_a_slideshow_up_when_a_session_takes_the_window_over_opens_on_its_side_as_it_was(slideshows):
    director, watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(slideshows)

    open_both_shapes(director)

    carried = director.region_slideshow(PORTRAIT)
    assert [slide[2] for slide in carried.items] == ["g1", "g2"]
    assert carried.resumed == replace(watched.state_at_close, location="collection/a")
    assert carried.taken_up == (SlideshowFilters(favorites=True), False)
    assert [slide[2] for slide in director.region_slideshow(LANDSCAPE).items] == ["g5"]


class _TakenOver(NamedTuple):
    shape: str
    shapes: tuple
    monitor: object
    the_other: str
    its_library: list


@pytest.mark.parametrize("case", [
    _TakenOver(LANDSCAPE, (WIDE, WIDE), PORTRAIT_MONITOR, PORTRAIT, ["g4"]),
    _TakenOver(PORTRAIT, (TALL, TALL), LANDSCAPE_MONITOR, LANDSCAPE, ["g5"]),
])
def test_a_slideshow_taken_over_opens_on_the_funestra_of_its_shape_whatever_monitor_it_was_on(
        slideshows, case):
    shape, shapes, monitor, the_other, its_library = case
    carried_to = shape
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, shape=shape, shapes=shapes, monitor=monitor)

    open_both_shapes(director)

    assert ([slide[2] for slide in director.region_slideshow(carried_to).items]
            == [f"g{n}" for n in range(1, len(shapes) + 1)])
    assert [slide[2] for slide in director.region_slideshow(the_other).items] == its_library


@pytest.mark.parametrize(("shapes", "monitor", "tall", "wide"), [
    ((TALL, WIDE, TALL), LANDSCAPE_MONITOR, ["g1", "g3"], ["g2"]),
    ((WIDE, TALL, WIDE), PORTRAIT_MONITOR, ["g2"], ["g1", "g3"]),
])
def test_a_slideshow_of_both_shapes_taken_over_plays_each_shape_on_the_funestra_of_that_shape(
        slideshows, shapes, monitor, tall, wide):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, shape=BOTH, shapes=shapes, monitor=monitor)

    open_both_shapes(director)

    assert [slide[2] for slide in director.region_slideshow(PORTRAIT).items] == tall
    assert [slide[2] for slide in director.region_slideshow(LANDSCAPE).items] == wide


def test_a_slideshow_taken_over_on_an_item_of_the_other_shape_goes_on_from_the_next_of_its_own(
        slideshows):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, shape=BOTH, shapes=(TALL, WIDE, TALL), standing=SlideshowState(
            order=("g1", "g2", "g3"), current="g2", locked=True, version_index=1))

    open_both_shapes(director)

    assert director.region_slideshow(PORTRAIT).resumed == SlideshowState(
        order=("g1", "g3"), current="g3", location="collection/a")


@pytest.mark.parametrize(("shape", "monitor"), [(PORTRAIT, PORTRAIT_MONITOR),
                                                (LANDSCAPE, LANDSCAPE_MONITOR)])
def test_a_slideshow_on_its_own_opens_full_screen_on_the_monitor_of_its_shape(
        slideshows, monkeypatch, shape, monitor):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], shape=shape)

    (slideshow,) = made
    assert (slideshow.shown.geometry, slideshow.shown.fullscreen) == (monitor.getRect(), 1)


@pytest.mark.parametrize(("shapes", "monitor"), [((TALL, WIDE, TALL), PORTRAIT_MONITOR),
                                                  ((WIDE, TALL, WIDE), LANDSCAPE_MONITOR),
                                                  ((TALL, WIDE), LANDSCAPE_MONITOR)])
def test_a_slideshow_of_both_shapes_opens_on_the_monitor_most_of_its_items_fit(
        slideshows, monkeypatch, shapes, monitor):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate(shapes)]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, shape=BOTH)

    assert made[0].shown.geometry == monitor.getRect()


@pytest.mark.parametrize(("shapes", "monitor"), [((TALL, TALL, WIDE), LANDSCAPE_MONITOR),
                                                  ((WIDE, WIDE, TALL), PORTRAIT_MONITOR)])
def test_a_slideshow_of_both_shapes_opened_on_an_item_goes_to_that_items_monitor(
        slideshows, monkeypatch, shapes, monitor):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate(shapes)]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, shape=BOTH, start=2)

    assert made[0].shown.geometry == monitor.getRect()


def test_a_slideshow_of_both_shapes_coming_back_to_an_item_goes_to_that_items_monitor(
        slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate((TALL, TALL, WIDE))]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, shape=BOTH,
                  carrying=Carrying(resume=SlideshowState(order=("g0", "g1", "g2"), current="g2")))

    assert made[0].shown.geometry == LANDSCAPE_MONITOR.getRect()


def test_a_slideshow_of_the_other_shape_asked_for_while_one_is_up_moves_to_its_monitor(
        slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)

    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    (slideshow,) = made
    assert (slideshow.shown.geometry, slideshow.shown.isFullScreen()) == (
        PORTRAIT_MONITOR.getRect(), True)


def test_a_slideshow_asked_for_again_on_the_monitor_it_is_on_stays_put(slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    assert made[0].shown.fullscreen == 1


def test_a_slideshow_with_no_monitor_of_its_shape_opens_full_screen_where_it_always_did(
        slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS[:1])
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert (made[0].shown.geometry, made[0].shown.fullscreen) == (None, 1)


def test_the_slideshow_a_session_took_over_is_put_back_on_the_first_opening_only(slideshows):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(slideshows)
    open_both_shapes(director)

    director.close_the_slideshows()
    open_both_shapes(director)

    assert [slide[2] for slide in director.region_slideshow(PORTRAIT).items] == ["g4"]


def test_a_window_handed_back_before_its_regions_opened_lets_go_of_the_slideshow_it_held(slideshows):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(slideshows)

    director.become_standalone(motion=None)
    director.become_hosted(FakeSession())
    open_both_shapes(director)

    assert [slide[2] for slide in director.region_slideshow(PORTRAIT).items] == ["g4"]


def test_a_director_names_the_shape_of_a_slideshow_it_could_hand_a_session(slideshows):
    director, _host, made = slideshows()
    assert director.slideshow_showing_on() is None

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    assert director.slideshow_showing_on() == PORTRAIT

    made[0].close()
    assert director.slideshow_showing_on() is None


def test_a_director_names_both_shapes_for_a_slideshow_of_both(slideshows):
    director, _host, _made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate((TALL, WIDE))]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, shape=BOTH)

    assert director.slideshow_showing_on() == BOTH


def test_a_region_opens_armed_with_the_versions_of_the_library_it_plays(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    director, host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    assert host.visible == []
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}

    open_both_shapes(director)

    assert director.region_slideshow(PORTRAIT).versions == {"g4.png": ["newer", "older"]}, (
        "versions read off the Gallery pane's rows name none of the slides on screen, and every "
        "versions button on the HUD is then drawn faded however many enhancements the library "
        "holds")
    assert director.region_slideshow(LANDSCAPE).versions == {"g5.png": ["newer", "older"]}


def test_a_sessions_regions_open_on_their_base_state_whatever_was_pressed(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    made[0].actions.filters_changed(SlideshowFilters(enhanced=True))
    made[0].close()

    open_both_shapes(director)

    assert director.region_slideshow(PORTRAIT).taken_up == (SlideshowFilters(), False)
    assert director.region_slideshow(LANDSCAPE).taken_up == (SlideshowFilters(), False)


def test_a_region_says_how_long_it_took_to_fill(slideshows, caplog):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())

    with caplog.at_level("INFO", logger="origenerator.gui.slideshow_director"):
        open_both_shapes(director)

    opened = [record.message for record in caplog.records if "region opens" in record.message]
    assert len(opened) == 2
    assert all(re.search(r", filled in \d+ ms$", message) for message in opened), (
        "timed because the wait between the press that opens this mode and the slides arriving "
        f"is what the user judges the mode by: {opened}")


_LEFT_LOOPING_ON_G5 = SlideshowState(order=("g4", "g5"), current="g5", locked=True,
                                     loop="seed", loop_pool=("g5",))
_LEFT_NARROWED = SlideshowFilters(favorites=True, action="alpha")


def _regions_of_two_images(slideshows, **build):
    gallery_pane = FakeGalleryPane(collections={
        ALL_PORTRAIT: [_row("g4"), _row("g5")], ALL_LANDSCAPE: [_row("g6")],
        LATEST_PORTRAIT: [_image("g5", "a red fox", seed=5), _image("g4", "a blue car", seed=4)]})
    return slideshows(gallery_pane=gallery_pane, fun_time=FakeSession(), **build)


def _left_on_g5(slideshow):
    slideshow.state_at_close = _LEFT_LOOPING_ON_G5
    slideshow.filters = _LEFT_NARROWED


def test_a_region_opened_for_the_next_session_comes_back_where_the_last_one_left_it(slideshows):
    director, _host, _made = _regions_of_two_images(slideshows)
    open_both_shapes(director)
    _left_on_g5(director.region_slideshow(PORTRAIT))

    director.become_standalone(motion=None)
    director.become_hosted(FakeSession())
    open_both_shapes(director)

    back = director.region_slideshow(PORTRAIT)
    assert back.resumed == replace(_LEFT_LOOPING_ON_G5, location=ALL_PORTRAIT)
    assert back.taken_up == (_LEFT_NARROWED, True)
    assert back.items[back.opened_with["start"]][2] == "g5"


def test_a_region_comes_back_where_it_was_left_after_origenerator_itself_restarts(slideshows):
    first, _host, _made = _regions_of_two_images(slideshows)
    open_both_shapes(first)
    _left_on_g5(first.region_slideshow(PORTRAIT))
    saved = json.loads(json.dumps(first.remembered_regions()))

    second, _host, _made = _regions_of_two_images(slideshows)
    second.remember_regions(saved)
    open_both_shapes(second)

    back = second.region_slideshow(PORTRAIT)
    assert back.resumed == replace(_LEFT_LOOPING_ON_G5, location=ALL_PORTRAIT)
    assert back.taken_up == (_LEFT_NARROWED, True)


def test_a_region_left_on_latest_comes_back_on_latest(slideshows):
    director, _host, _made = _regions_of_two_images(slideshows)
    director.remember_regions({PORTRAIT: {"state": {"current": "g4", "location": LATEST_PORTRAIT},
                                          "filters": {}}})

    open_both_shapes(director)

    back = director.region_slideshow(PORTRAIT)
    assert [item[2] for item in back.items] == ["g5", "g4"]
    assert back.hud.order_label == LATEST_LABEL
    assert back.opened_with["shuffle"] is module.in_order


def test_a_region_left_on_an_item_since_deleted_still_comes_back_narrowed_as_it_was(slideshows):
    director, _host, _made = _regions_of_two_images(slideshows)
    director.remember_regions({PORTRAIT: {
        "state": {"current": "gone", "location": ALL_PORTRAIT},
        "filters": SlideshowFilters.saved(_LEFT_NARROWED)}})

    open_both_shapes(director)

    back = director.region_slideshow(PORTRAIT)
    assert back.opened_with["start"] is None
    assert back.taken_up == (_LEFT_NARROWED, False)


def test_origenerator_on_its_own_keeps_what_each_region_was_left_on(slideshows):
    director, _host, _made = slideshows()
    left = {PORTRAIT: {"state": replace(_LEFT_LOOPING_ON_G5, location=ALL_PORTRAIT).saved(),
                       "filters": SlideshowFilters.saved(_LEFT_NARROWED)}}

    director.remember_regions(left)

    assert director.remembered_regions() == left


def test_a_director_handed_back_from_a_session_gives_up_its_regions_for_a_fullscreen_slideshow(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    open_both_shapes(director)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    motion = object()

    director.become_standalone(motion)
    director.open([("b.png", "image", "g2", None)])

    assert made[0].closes == 1
    assert director.region_slideshow(PORTRAIT) is None
    assert director.showing is made[-1]
    assert made[-1].shown.fullscreen == 1
    assert made[-1].shown.motion is motion


def test_a_landing_reaches_the_slideshow_whose_own_folder_holds_it(slideshows):
    gallery_pane = FakeGalleryPane(collections={"collection/a": [_row("g9")], "collection/b": []})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a",
                  shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="collection/b",
                  shape=PORTRAIT)

    director.note_finished(_row("g9", favorite=True))

    assert made[0].added == [("g9", True, False)]
    assert made[1].added == []


def test_an_arrival_from_outside_is_lined_up_on_a_slideshow_playing_latest(slideshows):
    gallery_pane = FakeGalleryPane(collections={LATEST_LANDSCAPE: [_row("g9")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_LANDSCAPE,
                  shape=LANDSCAPE)

    director.note_arrived([_row("g9", favorite=True)])

    assert made[0].added == [("g9", True, False)]


def test_an_arrival_from_outside_leaves_a_slideshow_in_shuffle_as_it_was(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_LANDSCAPE: [_row("g9")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=ALL_LANDSCAPE,
                  shape=LANDSCAPE)

    director.note_arrived([_row("g9")])

    assert made[0].added == []


def test_a_run_in_another_folder_is_turned_down(slideshows):
    host = FakeHost(rows=[_row("g1")])
    director, _host, made = slideshows(host, db=FakeDB([_row("g7")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g7", b"frame-one")
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == []


def test_a_run_the_folder_lists_only_after_its_first_frame_joins_on_its_next(slideshows):
    host = FakeHost(rows=[_row("g1")])
    director, _host, made = slideshows(host, db=FakeDB([_row("g1"), _row("g7")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g7", b"frame-one")
    host.rows.append(_row("g7"))
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == [("g7", b"frame-two")]


def test_an_enhancement_is_never_a_slide_of_its_own_frames(slideshows):
    enhance = _row("g8", workflow_name="enhance_image")
    host = FakeHost(rows=[_row("g1"), enhance])
    director, _host, made = slideshows(host, db=FakeDB([enhance]),
                                       gallery_pane=FakeGalleryPane(latest=True))
    enhance["workflow_name"] = gallery.ENHANCE_WORKFLOW
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g8", b"frame")

    assert made[0].generating == [], (
        "an enhancement is nobody's slide: a second slide of the image half-rendered would be "
        "the same image twice, one of them worse")


def test_a_run_turned_down_frame_after_frame_looks_at_the_slideshows_set_once(slideshows):
    gallery_pane = FakeGalleryPane(collections={"collection/a": [_row("g1")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, db=FakeDB([_row("g-run")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", shape=LANDSCAPE)
    gallery_pane.library.asked = 0

    for frame in (b"one", b"two", b"three"):
        director.note_generating("g-run", frame)

    assert made[0].generating == [], (
        "a collection is a deliberate set (favorited, requested, condemned) that nothing joins "
        "by being made")
    assert gallery_pane.library.asked == 1


def test_a_run_a_collection_lists_only_after_the_next_reading_joins_on_the_frame_after_it(slideshows):
    gallery_pane = FakeGalleryPane(collections={"collection/a": [_row("g1")]})
    db = FakeDB([_row("g7")])
    director, _host, made = slideshows(gallery_pane=gallery_pane, db=db, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", shape=LANDSCAPE)

    director.note_generating("g7", b"frame-one")
    gallery_pane.library = FakeLibrary(db, _host, {"collection/a": [_row("g1"), _row("g7")]})
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == [("g7", b"frame-two")]


def test_a_run_of_the_folder_on_screen_joins_on_its_first_frame(slideshows):
    host = FakeHost(rows=[_row("g1"), _row("g5")])
    director, _host, made = slideshows(host, db=FakeDB([_row("g5")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g5", b"frame")

    assert made[0].generating == [("g5", b"frame")]


def test_a_landed_enhancement_reaches_every_surface(slideshows, tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    director.note_enhanced(_row("g1", files=("better.png",)))

    assert [slideshow.enhanced for slideshow in made] == [
        [("g1", "image", None)], [("g1", "image", None)]], (
        "not only the slideshow with that image on screen: an enhancement asked for from a "
        "slideshow lands minutes later, when the slideshow has long paged on, and an upgrade it "
        "does not take then it never takes")


def test_a_landed_enhancement_hands_every_slideshow_its_new_thumbnail(
        slideshows, tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)

    director.note_enhanced({**_row("g1", files=("better.png",)),
                            "thumbnail_path": "thumbnails/better.jpg"})

    assert made[0].enhanced == [("g1", "image", "thumbnails/better.jpg")], (
        "a slideshow also draws each item small on its map, so it takes the new thumbnail "
        "along with the new file")


_WELL_BEFORE_ITS_UPSCALE = (1_000_000, 1_000_000)


def _evolver_upscaled_video(tmp_path, monkeypatch):
    output = tmp_path / "output"
    video = output / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    os.utime(video, _WELL_BEFORE_ITS_UPSCALE)
    library = tmp_path / "upscaled_by_orientation"
    upscale = library / "landscape" / "origenerator" / "clip_topaz.mp4"
    upscale.parent.mkdir(parents=True)
    upscale.write_bytes(b"upscale")
    monkeypatch.setattr(library_views, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    monkeypatch.setattr(library_views, "KINO_UPSCALES_DIR", library)
    return _row("g1", files=("clip.mp4",)), video, upscale


def _director():
    db = FakeDB()
    host = FakeHost()
    return SlideshowDirector(
        host,
        DirectorSources(db=db, jobs=FakeJobQueue(), names=ItemNames(db),
                        library=lambda: LibrarySnapshot([]), listing=host.listing),
        DirectorSurroundings(pace=SlideshowPace(), motion=None, fun_time=None))


def test_a_video_evolver_upscaled_plays_as_the_upscale(tmp_path, monkeypatch):
    row, _video, upscale = _evolver_upscaled_video(tmp_path, monkeypatch)

    assert _director().items_of([row]) == [(upscale, "video", "g1", None)]


def test_shift_arrows_step_from_an_upscale_to_the_video_it_was_made_from(tmp_path,
                                                                        monkeypatch):
    row, video, upscale = _evolver_upscaled_video(tmp_path, monkeypatch)

    assert _director().versions_of([row]) == {
        str(upscale): [(upscale, "video", "Evolved", ()), (video, "video", "Original", ())]}


def _enhanced_with(places: list[dict]) -> dict:
    return {**_row("g1", files=()), "output_files": json.dumps([
        {"filename": "enhanced.png", "subfolder": "image", "points_of_interest": places},
        {"filename": "base.png", "subfolder": "image"}]),
        "original_files": json.dumps([{"filename": "base.png", "subfolder": "image"}])}


def test_each_version_of_an_enhanced_image_brings_the_places_its_fixes_found(tmp_path, monkeypatch):
    monkeypatch.setattr(library_views, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    face = {"part": "faces", "left": 0.4, "top": 0.1, "right": 0.6, "bottom": 0.3}

    ((_key, (enhanced, original)),) = _director().versions_of([_enhanced_with([face])]).items()

    assert enhanced.points_of_interest == ((0.4, 0.1, 0.6, 0.3),)
    assert original.points_of_interest == ()


def test_the_eyes_of_two_faces_in_an_enhanced_image_come_back_as_a_close_up_of_each_pair(
        tmp_path, monkeypatch):
    monkeypatch.setattr(library_views, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    eyes = [{"part": "eyes", "left": left, "top": 0.1, "right": right, "bottom": 0.19}
            for left, right in ((0.10, 0.25), (0.20, 0.35), (0.33, 0.48), (0.43, 0.58))]

    ((_key, (enhanced, _original)),) = _director().versions_of([_enhanced_with(eyes)]).items()

    assert enhanced.points_of_interest == ((0.1, 0.1, 0.35, 0.19), (0.33, 0.1, 0.58, 0.19))


def test_a_region_reset_re_points_what_feeds_it(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  shape=LANDSCAPE)

    director.reset_region(made[0])

    assert director._live_slideshows == [(made[0], ALL_LANDSCAPE)]
    assert made[0].retuned == ([("g4.png", "image", "g4", None)], set())


def test_a_slideshow_counts_as_enhanced_what_the_library_counts_as_enhanced(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_LANDSCAPE: [_row("g4"), _row("g5")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    gallery_pane.library.enhanced_ids_of = lambda rows: {"g5"}
    director.open([("a.png", "image", "g1", None)], location="workflow/a", shape=LANDSCAPE)

    director.reset_region(made[0])

    assert made[0].retuned[1] == {"g5"}


def test_an_item_that_lands_is_enhanced_when_the_library_counts_it_so(slideshows):
    gallery_pane = FakeGalleryPane(collections={"collection/a": [_row("g9")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    gallery_pane.library.enhanced_ids_of = lambda rows: {"g9"}
    director.open([("a.png", "image", "g1", None)], location="collection/a", shape=LANDSCAPE)

    director.note_finished(_row("g9"))

    assert made[0].added == [("g9", False, True)]


def test_a_set_handed_to_a_running_slideshow_brings_its_own_versions_with_it(slideshows):
    gallery_pane = FakeGalleryPane(collections={LATEST_LANDSCAPE: [_row("g9")],
                                       ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane,
                                       db=FakeDB([_row("g9"), _row("g4")]),
                                       fun_time=FakeSession())
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  shape=LANDSCAPE)

    director.reorder_slideshow(made[0], True)
    assert made[0].versions == {"g9.png": ["newer", "older"]}

    director.reset_region(made[0])
    assert made[0].versions == {"g4.png": ["newer", "older"]}


def test_latest_points_a_region_slideshow_at_its_sides_latest_and_feeds_it_from_there(slideshows):
    two_images = [_image("g9", "a red fox", seed=9), _image("g4", "a blue car", seed=4)]
    gallery_pane = FakeGalleryPane(collections={LATEST_LANDSCAPE: two_images})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  shape=LANDSCAPE)

    director.reorder_slideshow(made[0], True)

    assert made[0].reordered == (
        [("g9.png", "image", "g9", None), ("g4.png", "image", "g4", None)], True, set())
    assert director._live_slideshows == [(made[0], LATEST_LANDSCAPE)]
    assert made[0].said == ["Latest"]


def test_shuffle_points_a_region_slideshow_back_at_its_sides_whole_library(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")],
                                       LATEST_PORTRAIT: [_row("g9")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_PORTRAIT,
                  shape=PORTRAIT)

    director.reorder_slideshow(made[0], False)

    assert made[0].reordered == ([("g4.png", "image", "g4", None)], False, set())
    assert director._live_slideshows == [(made[0], ALL_PORTRAIT)]
    assert made[0].said == ["Shuffle"]


def test_a_slideshow_on_its_own_takes_latest_of_the_shape_it_opened_on(slideshows):
    gallery_pane = FakeGalleryPane(collections={LATEST_PORTRAIT: [_row("g9")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    director.reorder_slideshow(made[0], True)

    assert made[0].reordered == ([("g9.png", "image", "g9", None)], True, set())


def test_an_order_with_nothing_to_play_says_so_and_leaves_the_slideshow_alone(slideshows):
    director, _host, made = slideshows(gallery_pane=FakeGalleryPane(collections={}), fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  shape=LANDSCAPE)

    director.reorder_slideshow(made[0], True)

    assert made[0].reordered is None
    assert list(zip(made[0].said, made[0].said_kinds, strict=True)) == [
        ("Nothing there to play", WARNING)]
    assert director._live_slideshows == [(made[0], "workflow/a")]


@pytest.mark.parametrize("session", [None, FakeSession()])
def test_a_slideshow_asks_this_director_for_its_order_hosted_or_not(slideshows, session):
    director, _host, made = slideshows(fun_time=session)

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert made[0].actions.reorder == director.reorder_slideshow


def test_a_loop_ending_on_a_folder_slideshow_hands_it_the_library_it_is_ordered_by(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  shape=LANDSCAPE)

    assert director.browse_it_all(made[0]) is True

    assert made[0].reordered == ([("g4.png", "image", "g4", None)], False, set())
    assert made[0].kept_the_slide is True
    assert director._live_slideshows == [(made[0], ALL_LANDSCAPE)]
    assert made[0].said == [], (
        "the surface says \"Loop off\" itself")


def test_a_slideshow_playing_latest_falls_back_to_latest_rather_than_to_the_shuffle(slideshows):
    gallery_pane = FakeGalleryPane(collections={LATEST_PORTRAIT: [_row("g9")],
                                       ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    made[0].hud_order_label = LATEST_LABEL

    assert director.browse_it_all(made[0]) is True

    assert made[0].reordered == ([("g9.png", "image", "g9", None)], True, set())


def test_a_way_out_with_nothing_of_that_shape_to_play_leaves_the_slideshow_alone(slideshows):
    director, _host, made = slideshows(gallery_pane=FakeGalleryPane(collections={}))
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  shape=PORTRAIT)

    assert director.browse_it_all(made[0]) is False

    assert made[0].reordered is None
    assert director._live_slideshows == [(made[0], "workflow/a")]


def test_a_second_set_in_the_one_window_brings_its_own_sides_library_with_it(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g7")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    director.open([("b.png", "image", "g2", None)], shape=LANDSCAPE)

    assert director.browse_it_all(made[0]) is True
    assert made[0].reordered == ([("g7.png", "image", "g7", None)], False, set())


def test_a_slideshow_asks_this_director_for_the_way_out_of_a_loop(slideshows):
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert made[0].actions.browse_all == director.browse_it_all


def test_a_region_slideshow_ending_comes_back_on_the_base_state(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    open_both_shapes(director)
    first = director.region_slideshow(PORTRAIT)

    first.close()

    assert director.region_slideshow(PORTRAIT) is not first
    assert director.region_slideshow(PORTRAIT) is not None, (
        "the Funestra under a region is blacked for the whole session, so a region left with no "
        "slideshow is a black rectangle")


def test_closing_the_slideshows_drops_the_wanting_before_it_closes_anything(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    open_both_shapes(director)

    director.close_the_slideshows()
    director.fill_the_wanted_regions()

    assert director.region_slideshow(PORTRAIT) is None


def test_a_side_handed_over_alone_opens_on_that_side_alone(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")], ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())

    director.fill_the_region(PORTRAIT)

    assert director.region_slideshow(PORTRAIT) is not None
    assert director.region_slideshow(LANDSCAPE) is None


def test_a_side_let_go_alone_stays_empty_and_leaves_the_other_playing(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")], ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    open_both_shapes(director)
    landscape = director.region_slideshow(LANDSCAPE)

    director.close_the_slideshow(PORTRAIT)
    director.fill_the_wanted_regions()

    assert director.region_slideshow(PORTRAIT) is None
    assert director.region_slideshow(LANDSCAPE) is landscape


def _asking_session(tmp_path):
    session = FakeSession(funestras={PORTRAIT: object(), LANDSCAPE: object()})
    session.dashboard_cmd_file = tmp_path / "dashboard_cmd.txt"
    return session


def test_a_slideshow_for_a_side_the_session_still_plays_waits_for_the_session_to_hand_it_over(
        slideshows, tmp_path):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=_asking_session(tmp_path))

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert made == []
    assert (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split() == [
        "portrait_origenerator_activate"]
    director.fill_the_region(PORTRAIT)
    assert [item[2] for item in made[0].items] == ["g1"]


def test_a_side_let_go_before_it_was_handed_over_forgets_the_slideshow_asked_for_it(
        slideshows, tmp_path):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=_asking_session(tmp_path))
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    director.close_the_slideshow(PORTRAIT)
    director.fill_the_region(PORTRAIT)

    assert [item[2] for item in made[0].items] == ["g4"]


def test_a_slideshow_handed_to_a_sessions_funestra_opens_with_what_is_in_flight(slideshows):
    host = FakeHost()
    waiting = _being_made("g-waiting", frame=None)
    host.queue = ([waiting], 3)
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(
        host, gallery_pane=gallery_pane,
        fun_time=FakeSession(funestras={PORTRAIT: object(), LANDSCAPE: object()}))

    director.fill_the_region(PORTRAIT)

    assert made[0].actions.queue_now() == ([waiting], 3)


def test_what_is_in_flight_reaches_a_slideshow_on_a_sessions_funestra(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(
        gallery_pane=gallery_pane, fun_time=FakeSession(funestras={PORTRAIT: object(), LANDSCAPE: object()}))
    director.fill_the_region(PORTRAIT)
    waiting = _being_made("g-waiting", frame=None)

    director.note_queue([waiting], 2)

    assert made[0].shown.queue_set == ([waiting], 2)


def test_a_region_already_holding_a_slideshow_is_left_alone(slideshows):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    open_both_shapes(director)
    standing = director.region_slideshow(PORTRAIT)

    open_both_shapes(director)

    assert director.region_slideshow(PORTRAIT) is standing


def test_a_freeze_that_one_slideshow_refuses_still_reaches_the_rest(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)
    made[0].pause_raises = True
    refused = []

    try:
        director.set_room_paused(True)
    except RuntimeError as error:
        refused.append(error)

    assert (refused, made[1].paused) == ([], True), (
        "each slideshow is its own step, so the freeze cannot be skipped when one raises: a "
        "freeze that stopped at the slideshows left the thumbnails running with no sign of why")


def test_a_slideshow_opened_while_the_room_is_frozen_opens_frozen(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.set_room_paused(True)

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert made[0].paused is True


def test_a_click_on_a_hosted_slideshow_asks_for_omnipause_on_the_sessions_channel(slideshows, tmp_path):
    session = FakeSession()
    session.dashboard_cmd_file = tmp_path / "dashboard_cmd.txt"
    director, _host, made = slideshows(fun_time=session)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    made[0].actions.omnipause()

    assert session.dashboard_cmd_file.exists(), (
        "a click on a slideshow asks the room for OmniPause in this same file, where a "
        "Funestra's click on what it shows asks for it")
    assert session.dashboard_cmd_file.read_text(encoding="utf-8").split() == [
        "omnipause_toggle"]


def test_a_click_on_a_slideshow_standing_on_its_own_pauses_the_whole_room(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].actions.omnipause()

    assert host.room_paused == [True]
    assert made[0].paused is True


def test_a_second_click_on_it_plays_the_room_again(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].actions.omnipause()
    made[0].actions.omnipause()

    assert host.room_paused == [True, False]
    assert made[0].paused is False


def test_closing_a_paused_slideshow_standing_on_its_own_leaves_the_room_paused(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])
    made[0].actions.omnipause()

    made[0].close()

    assert host.room_paused == [True]


def test_a_press_that_reaches_a_slideshow_already_gone_leaves_the_room_as_it_is(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])
    made[0].actions.omnipause()
    made[0].close()

    made[0].actions.omnipause()

    assert host.room_paused == [True]


def test_a_hosted_slideshow_closing_leaves_the_sessions_pause_to_the_session(slideshows):
    director, host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    director.set_room_paused(True)

    made[0].close()

    assert host.room_paused == []


def test_the_spoken_close_with_no_slideshow_up_says_so(slideshows):
    director, host, made = slideshows()

    director.run_slideshow_command(SlideshowCommand.STOP, None)

    assert host.said == ["no slideshow to close"]
    assert made == []


def test_the_spoken_pause_with_no_slideshow_up_pauses_the_room_as_esc_does(slideshows):
    director, host, _made = slideshows()

    director.run_slideshow_command(SlideshowCommand.PAUSE, None)

    assert host.room_paused == [True]
    assert director._pace.seconds == DEFAULT_PACE_S
    assert host.said == ["paused"]


def test_the_spoken_pause_pauses_the_room_and_leaves_the_slideshow_up_at_its_pace(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])
    made[0].dwell_s = 4

    director.run_slideshow_command(SlideshowCommand.PAUSE, None)

    assert host.room_paused == [True]
    assert (made[0].paused, made[0].dwell_s, made[0].closes) == (True, 4, 0)
    assert made[0].said == ["slideshow paused"]


def test_the_spoken_pause_leaves_a_room_already_paused_as_it_is(slideshows):
    director, host, _made = slideshows()
    director.set_room_paused(True)

    director.run_slideshow_command(SlideshowCommand.PAUSE, None)

    assert host.room_paused == []


def test_the_spoken_play_plays_a_paused_room_again_at_the_clip_seconds_set(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])
    made[0].dwell_s = 7
    made[0].actions.omnipause()

    director.run_slideshow_command(SlideshowCommand.START, None)

    assert host.room_paused == [True, False]
    assert (made[0].paused, made[0].dwell_s) == (False, 7)


def test_the_spoken_start_with_no_slideshow_up_opens_one_at_the_clip_seconds_set(slideshows):
    director, _host, _made = slideshows(FakeHost(rows=[_row("g1")]))
    director._pace.set_seconds(7)

    director.run_slideshow_command(SlideshowCommand.START, None)

    assert director._pace.seconds == 7


@pytest.mark.parametrize(("command", "paused", "asked"), [
    (SlideshowCommand.PAUSE, False, ["omnipause_toggle"]),
    (SlideshowCommand.PAUSE, True, []),
    (SlideshowCommand.START, True, ["omnipause_toggle"]),
    (SlideshowCommand.START, False, []),
], ids=["pause a playing room", "pause a paused room", "play a paused room",
        "play a playing room"])
def test_a_spoken_pause_or_play_asks_a_hosting_session_for_omnipause_only_to_change_the_room(
        slideshows, tmp_path, command, paused, asked):
    session = FakeSession()
    session.dashboard_cmd_file = tmp_path / "dashboard_cmd.txt"
    director, _host, _made = slideshows(fun_time=session)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    director.set_room_paused(paused)

    director.run_slideshow_command(command, PORTRAIT)

    sent = session.dashboard_cmd_file
    assert (sent.read_text(encoding="utf-8").split() if sent.exists() else []) == asked


def test_a_spoken_word_is_answered_at_the_center_top_of_the_slideshows_own_window(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.answer("audio on")

    assert made[0].said == ["audio on"]
    assert host.said == []


def test_an_answer_keeps_its_kind_at_the_center_top_of_the_slideshow(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.answer("no Latest collection yet", kind=WARNING)

    assert made[0].said_kinds == [WARNING]


def test_a_spoken_word_with_no_slideshow_up_is_answered_on_the_caption(slideshows):
    director, host, _made = slideshows()

    director.answer("audio on")

    assert host.said == ["audio on"]


def test_a_named_side_holding_nothing_is_an_answer_in_itself(slideshows):
    director, _host, _made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)

    assert director.surface_for(PORTRAIT) is None
    assert director.surface_for(LANDSCAPE) is not None


def test_the_spoken_favorites_flips_f_mode_rather_than_opening_a_collection(slideshows):
    class Spoken:
        collection_key = FAVORITES_KEY
        shape = None

    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.play_collection(Spoken())

    assert made[0].hud_favorites_filter is True
    assert len(made) == 1
    assert host.said == ["F-mode on"]


def test_a_spoken_collection_with_nothing_in_it_opens_nothing(slideshows):
    class Spoken:
        collection_key = LATEST_KEY
        shape = None

    director, host, made = slideshows(gallery_pane=FakeGalleryPane(collections={}))

    director.play_collection(Spoken())

    assert made == []
    assert host.said == ["nothing there to play"]


def test_the_transport_words_step_the_slide_and_say_which_way(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.FORWARD, said_at=7.5)
    director.run_on_slide(AppCommand.BACK, said_at=7.5)

    assert made[0].steps == [1, -1]
    assert made[0].done == []
    assert made[0].said == ["next", "back"]
    assert made[0].said_kinds == [INFO, INFO]


def test_a_lock_said_over_a_slide_since_left_puts_that_slide_back_and_locks_it(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.LOCK, said_at=7.5)

    assert made[0].done == [("back to", 7.5), ("lock", True)]


def test_trash_said_over_a_slide_since_left_puts_that_slide_back_and_takes_it_away(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.CULL, said_at=7.5)

    assert made[0].done == [("back to", 7.5), ("cull",)]


def test_a_favorite_said_over_a_slide_since_left_puts_that_slide_back_and_favorites_it(
        slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.FAVORITE, said_at=7.5)

    assert made[0].done == [("back to", 7.5), ("favorite",)]


def test_a_favorite_over_a_slide_with_nothing_to_favorite_says_so(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])
    made[0].favoritable = False

    director.run_on_slide(AppCommand.FAVORITE)

    assert made[0].said == ["nothing here to favorite"]
    assert made[0].said_kinds == [WARNING]


def test_a_favorite_that_lands_says_so_in_the_favorites_green(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.FAVORITE)

    assert made[0].said == ["favorited"]
    assert made[0].said_kinds == [FAVORITE]


def test_leaving_a_slideshow_picks_its_slide_where_the_slideshow_was_playing(slideshows):
    director, host, made = slideshows(FakeHost(rows=[_row("g1")]))
    director.open([("a.png", "image", "g1", None)])

    made[0].open_requested.emit("g1")

    assert host.revealed == ["g1"]
    assert host.followed == []
    assert director.showing is None


def test_leaving_a_slideshow_on_a_slide_the_pane_does_not_hold_goes_to_it(slideshows):
    director, host, made = slideshows(FakeHost(rows=[_row("g1")]))
    director.open([("a.png", "image", "g1", None)])

    made[0].open_requested.emit("g2")

    assert host.followed == ["g2"]


def test_a_region_slideshow_is_placed_muted_frameless_and_on_top(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    window = made[0].shown
    assert window.audio_muted is True, (
        "silent like every Satellite Funestra: the session's Main Funestra owns the room's "
        "audio")
    assert window.geometry == (1920, 0, 960, 540)
    assert window.raised == 1
    assert window.activated == 1
    assert window.window_flags & Qt.WindowType.FramelessWindowHint
    assert window.window_flags & Qt.WindowType.WindowStaysOnTopHint, (
        "topmost because the Satellite Funestra it covers is topmost itself")


def test_a_standalone_slideshow_takes_the_whole_monitor(slideshows):
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)])

    assert made[0].shown.fullscreen == 1
    assert made[0].shown.window_title is None


def test_a_session_that_hands_over_its_funestras_gets_the_slideshow_on_one(slideshows):
    channel = object()
    director, _host, made = slideshows(fun_time=FakeSession(funestras={PORTRAIT: channel}))

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert made[0].opened_with["channel"] is channel
    assert made[0].opened_with["shape"] == PORTRAIT
    assert not isinstance(made[0].shown, FakeWindow)
    assert director.region_slideshow(PORTRAIT) is made[0]


def test_a_slideshow_on_a_funestra_says_its_lines_in_the_gallerys_caption(slideshows):
    director, host, made = slideshows(fun_time=FakeSession(funestras={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)

    assert made[0].opened_with["say"] == host.say


def test_a_side_the_session_named_no_funestra_for_still_gets_a_window(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession(funestras={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)

    assert "channel" not in made[0].opened_with, (
        "an older session names no Funestras, and its regions want a window of this app's over them "
        "exactly as before")
    assert made[0].shown.shows == 1


def test_what_is_on_screen_opens_where_the_last_slideshow_left_off(slideshows):
    host = FakeHost(location="workflow/a", rows=[_row("g1")])
    director, _host, made = slideshows(host)
    director.open([("a.png", "image", "g1", None)])
    made[0].state_at_close = SlideshowState(order=("g1",), current="g1")
    made[0].close()

    director.start()

    assert made[1].resumed == SlideshowState(order=("g1",), current="g1")


def test_what_is_on_screen_opens_on_the_one_item_picked_and_is_led_nowhere_else(slideshows):
    host = FakeHost(location="workflow/a", rows=[_row("g1"), _row("g2")])
    host.picked = ["g2"]
    director, _host, made = slideshows(host)

    director.start()

    assert made[0].opened_with.get("start") == 1
    assert (made[0].leads, made[0].resumed) == (0, None)


def test_the_one_item_picked_where_the_last_slideshow_closed_is_picked_back_up_leading_nothing(
        slideshows):
    host = FakeHost(location="workflow/a", rows=[_row("g1"), _row("g2")])
    director, _host, made = slideshows(host)
    director.open([("a.png", "image", "g1", None), ("b.png", "image", "g2", None)])
    made[0].state_at_close = SlideshowState(order=("g1", "g2"), current="g2")
    made[0].close()
    host.picked = ["g2"]

    director.start()

    assert (made[1].resumed, made[1].resumed_on_its_slide) == (made[0].state_at_close, True)
    assert made[1].leads == 0


def test_nothing_to_play_opens_no_slideshow_at_all(slideshows):
    director, _host, made = slideshows(FakeHost(rows=[]))

    director.start()

    assert made == []
    assert director.showing is None


def test_the_queue_block_comes_up_filled_rather_than_blank(slideshows):
    host = FakeHost()
    waiting = _being_made("g-waiting", frame=None)
    host.queue = ([waiting], 3)
    director, _host, made = slideshows(host)

    director.open([("a.png", "image", "g1", None)])

    assert made[0].actions.queue_now() == ([waiting], 3)


def test_the_blocks_clear_drops_another_apps_work(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].actions.clear_queue()

    assert host.cleared_queue == 1


def test_the_blocks_start_now_starts_the_video_waiting_out_the_minute(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].actions.start_now()

    assert host.started_now == 1


def test_the_blocks_cancel_all_asks_the_gallery(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].actions.cancel_all()

    assert host.cancelled_all == 1


def test_a_slideshow_asks_the_gallery_for_cores_window(slideshows):
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    assert made[0].actions.core_window() is host.core


def test_a_row_dragged_down_the_block_re_lines_the_queue(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    made[0].actions.move("g2", "g1")

    assert director._jobs.moved == [("g2", "g1")]


def test_the_spoken_filter_narrows_the_slideshow_and_says_what_is_left(slideshows):
    slideshow = FakeSlideshow()
    slideshow.enhanced_items = ["a", "b"]
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_enhanced()

    assert slideshow.said == ["enhanced only — 2 to play"]


def test_a_slideshow_with_nothing_enhanced_in_it_says_so(slideshows):
    slideshow = FakeSlideshow()
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_enhanced()

    assert slideshow.said == ["nothing here is enhanced"]
    assert slideshow.said_kinds == [WARNING]


def test_the_spoken_filter_answers_even_when_the_switch_was_already_on(slideshows):
    slideshow = FakeSlideshow()
    slideshow.enhanced_items = ["a", "b"]
    slideshow.hud_enhanced_mode = True
    slideshow.set_enhanced_mode = lambda on: False
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_enhanced()

    assert slideshow.said == ["enhanced only — 2 to play"], (
        "said even when the switch was already that way: a word that did nothing and said "
        "nothing reads as a mic that missed it")


def test_original_only_narrows_the_slideshow_and_says_what_is_left(slideshows):
    slideshow = FakeSlideshow()
    slideshow.original_items = ["a"]
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_originals()

    assert slideshow.hud_originals_mode is True
    assert slideshow.said == ["original only — 1 to play"]


def test_original_only_on_a_slideshow_where_everything_is_enhanced_says_so_and_stays_off(
        slideshows):
    slideshow = FakeSlideshow()
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_originals()

    assert slideshow.hud_originals_mode is False
    assert (slideshow.said, slideshow.said_kinds) == (["everything here is enhanced"], [WARNING])


def test_enhanced_and_original_shows_all_of_them_and_leaves_f_mode_on(slideshows):
    slideshow = FakeSlideshow()
    slideshow.hud_favorites_filter = True
    slideshow.hud_enhanced_mode = True
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.show_enhanced_and_original()

    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_mode) == (True, False)
    assert slideshow.said == ["showing all of them"]


def test_no_filter_said_of_a_slideshow_lifts_its_action_filter_alone(slideshows):
    slideshow = FakeSlideshow()
    slideshow.filters = SlideshowFilters(favorites=True, enhanced=True, action="beta")
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.clear_action_filter()

    assert slideshow.filters == SlideshowFilters(favorites=True, enhanced=True)


def test_no_filter_with_no_slideshow_up_says_there_is_nothing_to_narrow(slideshows):
    director, host, _made = slideshows()

    director.clear_action_filter()

    assert host.said == ["the filter needs a slideshow to narrow"]


def test_the_filter_with_no_slideshow_up_says_there_is_nothing_to_narrow(slideshows):
    director, host, _made = slideshows()

    director.filter_enhanced()

    assert host.said == ["the filter needs a slideshow to narrow"]


def test_the_filter_said_with_no_slideshow_up_is_not_kept_for_the_next_one(slideshows):
    director, _host, made = slideshows()
    director.filter_enhanced()

    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)

    assert made[0].filters.enhanced is False, (
        "with no slideshow up there is nothing for the word to narrow, and it says so rather "
        "than arming the switch for the next slideshow")


def test_every_surface_lets_go_of_a_file_a_delete_is_about_to_move(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    director.release_media(["one.png"])

    assert [slideshow.released for slideshow in made] == [[(["one.png"], False)],
                                                          [(["one.png"], False)]]


def test_every_surface_hears_that_the_file_a_delete_moves_is_a_version_of_an_item_that_stays(
        slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    director.release_media(["one.png"], the_item_stays=True)

    assert [slideshow.released for slideshow in made] == [[(["one.png"], True)],
                                                          [(["one.png"], True)]]


def test_every_surface_hears_which_file_and_versions_an_item_has_left_after_a_delete(
        slideshows, tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    director.note_versions_deleted(_row("g1", files=("better.png",)))

    assert [[(pid, Path(path).name) for pid, path, *_ in slideshow.versions_deleted]
            for slideshow in made] == [[("g1", "better.png")], [("g1", "better.png")]]


def _image(prompt_id, prompt, *, seed, steps=50, size=(100, 200)):
    width, height = size
    params = {"positive_prompt": prompt, "seed": seed, "steps": steps,
              "width": width, "height": height}
    row = _row(prompt_id, params=params)
    row["params_json"] = json.dumps(params)
    return row


def _animation(prompt_id, *, frame, action, tmp_path, size=(100, 200)):
    width, height = size
    params = {"positive_prompt": "it moves", "noise_seed": 5, "input_image": frame}
    row = _row(prompt_id, workflow_name="wan22_i2v", params=params,
               files=(f"{prompt_id}.mp4",))
    row["params_json"] = json.dumps(params)
    row["video_actions"] = json.dumps([action])
    thumb = tmp_path / f"{prompt_id}_thumb.png"
    Image.new("RGB", (width, height)).save(thumb)
    row["thumbnail_path"] = str(thumb)
    return row


def _library(rows):
    return FakeHost(rows=rows)


def test_the_library_of_the_slideshows_side_answers_for_the_map_around_a_generation(slideshows, tmp_path):
    fox = _image("g1", "a red fox", seed=1)
    fox["output_files"] = json.dumps([{"filename": "g1.png"}])
    rows = [fox, _image("g2", "a red fox", seed=2),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="g1.png", action="beta", tmp_path=tmp_path),
            _animation("v3", frame="g1.png", action="beta", tmp_path=tmp_path),
            _image("w1", "a red fox", seed=3, size=(200, 100))]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", shape="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["g2"]
    assert [row.slide.prompt_id for row in around.column] == ["v1", "v2"]
    assert (around.label, tuple(row.label for row in around.column)) == (
        "Source image", ("alpha", "beta"))
    assert [slide.prompt_id for slide in around.group] == ["v1", "v2", "v3"]


def _fox(prompt_id, *, seed):
    image = _image(prompt_id, "a red fox", seed=seed)
    image["output_files"] = json.dumps([{"filename": f"{prompt_id}.png"}])
    return image


def test_every_row_shows_its_items_actions_and_nothing_when_it_has_none_as_in_kino(slideshows):
    tweaked = {**_image("c1", "a red fox", seed=1, steps=30),
               "image_actions": json.dumps(["alpha"]), "image_checked": json.dumps(["first box"])}
    rows = [_fox("g1", seed=1), tweaked, _image("c2", "a red fox", seed=1, steps=20)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", shape="portrait")

    assert (around.label, {row.slide.prompt_id: row.label for row in around.column}) == (
        "", {"c1": "alpha, first box", "c2": ""})


def test_the_map_is_drawn_against_the_gallerys_reading_of_the_library_never_a_reading_of_its_own(
        slideshows):
    rows = [_fox("g1", seed=1), _fox("g2", seed=2)]
    db = FakeDB(rows)
    director, _host, _made = slideshows(_library(rows), db=db)

    director.neighbors_of("g1", shape="portrait")
    director.neighbors_of("g2", shape="portrait")

    assert db.listings == 0


def test_the_column_is_this_seeds_other_configurations_then_the_videos_of_it(slideshows, tmp_path):
    fox = _fox("g1", seed=1)
    tweaked = _image("g2", "a red fox at dawn", seed=1)
    tweaked["output_files"] = json.dumps([{"filename": "g2.png"}])
    rows = [fox, tweaked, _fox("g3", seed=2),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", shape="portrait")

    assert [(row.slide.prompt_id, row.label) for row in around.column] == [("g2", ""), ("v1", "alpha")]


def test_a_video_sits_under_its_images_seed_with_the_image_down_its_column(slideshows, tmp_path):
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="g2.png", action="alpha", tmp_path=tmp_path),
            _animation("v3", frame="g1.png", action="beta", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", shape="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["v2"]
    assert [row.slide.prompt_id for row in around.column] == ["g1", "v3"]
    assert (around.label, tuple(row.label for row in around.column)) == (
        "alpha", ("Source image", "beta"))


def _a_sites(row):
    return {**row, "source": GenerationSource.OUTSIDE}


def test_what_another_site_made_stays_off_the_map(slideshows, tmp_path):
    rows = [_fox("g1", seed=1), _a_sites(_fox("g2", seed=2)),
            _fox("g3", seed=3),
            _a_sites(_animation("o1", frame="g1.png", action="beta", tmp_path=tmp_path)),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", shape="portrait")

    mapped = [*around.seeds, *(row.slide for row in around.column), *around.group]
    assert {slide.prompt_id for slide in mapped} == {"g3", "v1"}


def test_a_sites_pictures_in_one_folder_are_each_others_seeds_and_nothing_made_here_joins_them(
        slideshows):
    rows = [_a_sites(_fox("o1", seed=1)), _a_sites(_fox("o2", seed=2)),
            _a_sites(_fox("o3", seed=3)), _fox("g1", seed=4)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("o1", shape="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["o2", "o3"]


def test_videos_made_from_a_sites_picture_stay_together_on_the_map(slideshows, tmp_path):
    rows = [_a_sites(_fox("g1", seed=1)),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="g1.png", action="beta", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", shape="portrait")

    assert [(row.label, row.slide.prompt_id) for row in around.column] == [("beta", "v2")]
    assert [slide.prompt_id for slide in around.group] == ["v2"]


def test_widening_the_map_takes_in_nothing_another_site_made(slideshows, tmp_path):
    rows = [_fox("g1", seed=1), _a_sites(_image("o1", "a red fox", seed=2, steps=20)),
            _image("g2", "a red fox", seed=3, steps=20)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    assert [slide.prompt_id
            for slide in director.beyond_the_row_of("g1", shape="portrait")] == ["g2"]


def test_videos_made_from_one_hidden_starting_frame_list_each_other_on_the_map(slideshows, tmp_path):
    frame = {**_fox("h1", seed=1), "source": GenerationSource.STARTING_FRAME}
    rows = [frame, _animation("v1", frame="h1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="h1.png", action="beta", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", shape="portrait")

    assert [(row.label, row.slide.prompt_id) for row in around.column] == [("beta", "v2")]
    assert [slide.prompt_id for slide in around.group] == ["v2"]


def test_a_hidden_starting_frame_stays_off_the_map_of_a_video_made_from_it(slideshows, tmp_path):
    frame = {**_fox("h1", seed=1), "source": GenerationSource.STARTING_FRAME}
    rows = [frame, _animation("v1", frame="h1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="h1.png", action="beta", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", shape="portrait")

    mapped = [*around.seeds, *(row.slide for row in around.column), *around.group]
    assert "h1" not in [slide.prompt_id for slide in mapped]


def test_the_library_says_what_each_generation_an_action_filter_asks_about_is_named_for(slideshows, tmp_path):
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    assert director.actions_of(["g1", "v1", "nobody"], shape="portrait") == {
        "g1": "Source image", "v1": "alpha"}


def test_an_image_taken_away_leaves_the_map_its_row_draws(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a red fox", seed=2)]
    host, db = FakeHost(rows=rows), FakeDB(rows)
    director, _host, _made = slideshows(host, db=db)
    assert [slide.prompt_id for slide in director.neighbors_of("g1", shape="portrait").seeds] == ["g2"]

    db.rows.pop("g2")
    host.rows = [row for row in host.rows if row["prompt_id"] != "g2"]

    assert director.neighbors_of("g1", shape="portrait").seeds == ()


def test_beyond_the_row_lies_the_nearest_of_the_models_other_configurations(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a red fox", seed=2),
            _image("g3", "a red fox at dawn", seed=7),
            _image("g4", "a blue car", seed=8, steps=30)]
    director, _host, _made = slideshows(FakeHost(rows=rows), db=FakeDB(rows))

    beyond = director.beyond_the_row_of("g1", shape="portrait")

    assert [slide.prompt_id for slide in beyond] == ["g3", "g4"]
    assert director.beyond_the_row_of("nobody", shape="portrait") == ()


def test_a_generation_the_gallery_has_no_row_for_maps_alone(slideshows):
    director, _host, _made = slideshows()

    assert director.neighbors_of("nobody", shape="portrait").seeds == ()
    assert director.neighbors_of("", shape="landscape").column == ()


def test_a_slideshow_is_wired_to_the_library_of_the_side_it_opened_on(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a red fox", seed=2)]
    director, host, made = slideshows(FakeHost(rows=rows), db=FakeDB(rows))

    director.open(director.items_of(rows), location="a-folder", shape="portrait")

    actions = made[0].actions
    assert [slide.prompt_id for slide in actions.neighbors("g1").seeds] == ["g2"]
    assert actions.widen("g1") == ()
    assert actions.actions_of(["g1"]) == {"g1": ""}
    assert [slide.prompt_id for slide in actions.slides(("g2", "nobody", "g1"))] == ["g2", "g1"]
    actions.favorite("g1")
    actions.unfavorite("g1")
    assert host.favorited == []


def test_wrong_action_on_a_slide_takes_the_action_off_its_row_and_the_gallery_rereads(slideshows):
    rows = [{**_image("g1", "a red fox", seed=1), "image_actions": json.dumps(["alpha"])}]
    db = FakeDB(rows)
    director, host, made = slideshows(FakeHost(rows=rows), db=db)
    director.open(director.items_of(rows), location="a-folder", shape="portrait")

    assert made[0].actions.strike_action(Slide("g1.png", "image", "g1")) == "alpha"

    assert actions_of(db.rows["g1"], MediaType.IMAGE) == ItemActions()
    assert host.reread == 1


def test_wrong_action_on_a_slide_with_no_action_leaves_the_gallery_as_it_is(slideshows):
    rows = [_image("g1", "a red fox", seed=1)]
    director, host, made = slideshows(FakeHost(rows=rows), db=FakeDB(rows))
    director.open(director.items_of(rows), location="a-folder", shape="portrait")

    assert made[0].actions.strike_action(Slide("g1.png", "image", "g1")) == ""

    assert host.reread == 0


def test_a_lock_on_a_hosted_slideshow_puts_the_generation_it_holds_in_front_of_him(slideshows):
    rows = [_image("g1", "a red fox", seed=1)]
    director, host, made = slideshows(FakeHost(rows=rows), db=FakeDB(rows),
                                      fun_time=FakeSession())
    director.open(director.items_of(rows), location="a-folder", shape="portrait")

    made[0].actions.lock("g1")
    made[0].actions.lock("nobody")

    assert host.shown == ["g1"]
    assert host.followed == []


def _a_video_locked_in_a_session(slideshows, tmp_path, row):
    session = FakeSession()
    session.dashboard_cmd_file = tmp_path / "dashboard_cmd.txt"
    director, host, made = slideshows(FakeHost(rows=[row]), db=FakeDB([row]), fun_time=session)
    director.open(director.items_of([row]), location="a-folder", shape="portrait")

    made[0].actions.lock(row["prompt_id"])

    return host, session.dashboard_cmd_file.read_text(encoding="utf-8").splitlines()


def test_a_lock_on_another_sites_video_is_left_to_the_session_which_knows_its_sites_page(
        slideshows, tmp_path):
    video = _a_sites(_animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path))

    host, told = _a_video_locked_in_a_session(slideshows, tmp_path, video)

    assert told == ["portrait_lock_held|v1.png"]
    assert host.shown == []


def test_a_lock_on_a_video_made_here_is_left_to_the_session_so_core_shows_it_only_once(
        slideshows, tmp_path):
    video = _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path)

    host, told = _a_video_locked_in_a_session(slideshows, tmp_path, video)

    assert told == ["portrait_lock_held|v1.png"]
    assert host.shown == []


def test_a_lock_on_a_video_the_session_cannot_be_told_of_is_shown_in_core(
        slideshows, tmp_path):
    video = _a_sites(_animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path))
    director, host, made = slideshows(FakeHost(rows=[video]), db=FakeDB([video]),
                                      fun_time=FakeSession())
    director.open(director.items_of([video]), location="a-folder", shape="portrait")

    made[0].actions.lock("v1")

    assert host.shown == ["v1"]


def _a_sitting():
    return [_image("g5", "a red fox", seed=5), _image("g4", "a red fox", seed=4),
            _image("g3", "a blue car", seed=3),
            _image("g2", "a red fox", seed=2), _image("g1", "a red fox", seed=1)]


def _played(slideshow) -> list[str]:
    return [item[2] for item in slideshow.items]


def test_a_slideshow_of_latest_plays_one_of_each_run_of_a_folders_generations(slideshows):
    rows = _a_sitting()
    director, _host, made = slideshows(FakeHost(location=LATEST_PORTRAIT, rows=rows))

    director.start()

    assert _played(made[0]) == ["g5", "g3", "g2"]


def test_a_slideshow_of_a_folders_latest_plays_one_of_each_run_newest_first(slideshows):
    location = shaped_key(FolderCollection(LATEST_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = slideshows(FakeHost(location=location, rows=_a_sitting()))

    director.start()

    assert _played(made[0]) == ["g5", "g3", "g2"]


def test_a_slideshow_of_a_folder_plays_every_one_of_its_seeds(slideshows):
    rows = _a_sitting()
    director, _host, made = slideshows(FakeHost(location="workflow/a", rows=rows))

    director.start()

    assert _played(made[0]) == ["g5", "g4", "g3", "g2", "g1"]


def test_a_seed_landing_while_latest_plays_reaches_it_as_its_runs_newest(slideshows):
    sitting = _a_sitting()
    gallery_pane = FakeGalleryPane(collections={LATEST_PORTRAIT: sitting})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open(director.items_of(director.rows_at(LATEST_PORTRAIT)),
                  location=LATEST_PORTRAIT, shape=PORTRAIT)
    another_seed = _image("g6", "a red fox", seed=6)
    a_new_image = _image("g7", "a green hill", seed=7)

    gallery_pane.collections[LATEST_PORTRAIT] = [another_seed, *sitting]
    director.note_finished(another_seed)
    gallery_pane.collections[LATEST_PORTRAIT] = [a_new_image, another_seed, *sitting]
    director.note_finished(a_new_image)

    assert [added[0] for added in made[0].added] == ["g6", "g7"]


def test_a_slideshow_of_favorites_plays_the_sides_whole_library_with_the_filter_on(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    gallery_pane = FakeGalleryPane(collections={shaped_key(FAVORITES_KEY, PORTRAIT): [rows[0]],
                                       ALL_PORTRAIT: rows})
    director, _host, made = slideshows(FakeHost(location=shaped_key(FAVORITES_KEY, PORTRAIT),
                                                rows=rows),
                                       gallery_pane=gallery_pane)

    director.start()

    assert _played(made[0]) == ["g1", "g2"], (
        "Favorites and Enhanced are not sets of their own: each is the side's whole library "
        "with its filter held on, so the filter can be let go to widen the slideshow and Latest "
        "and Shuffle mean the library rather than what the collection lists")
    assert made[0].hud_favorites_filter is True
    assert director._live_slideshows == [(made[0], ALL_PORTRAIT)]


def _folder_of(rows):
    return gallery.SettingsGroup("workflow/a", "A", list(rows))


def test_a_slideshow_of_a_folders_favorites_plays_that_folder_with_the_filter_on(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    folder = shaped_key("workflow/a", PORTRAIT)
    favorites = shaped_key(FolderCollection(FAVORITES_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = slideshows(FakeHost(location=favorites, rows=[rows[0]],
                                                groups={folder: _folder_of(rows)}))

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].hud_favorites_filter is True
    assert director._live_slideshows == [(made[0], folder)]


def test_a_slideshow_of_a_folders_enhanced_plays_that_folder_with_enhanced_only_on(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    folder = shaped_key("workflow/a", PORTRAIT)
    enhanced = shaped_key(FolderCollection(ENHANCED_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = slideshows(FakeHost(location=enhanced, rows=[rows[0]],
                                                groups={folder: _folder_of(rows)}))

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].taken_up == (SlideshowFilters(enhanced=True), False)
    assert director._live_slideshows == [(made[0], folder)]


def test_a_slideshow_of_latest_opens_on_the_newest_rather_than_where_the_last_one_stopped(slideshows):
    rows = _a_sitting()
    director, _host, made = slideshows(FakeHost(location=LATEST_PORTRAIT, rows=rows))
    director._slideshow_state = SlideshowState(order=["g1"], current="g1")

    director.start()

    assert made[0].resumed is None, (
        "a slideshow of Latest opens on the newest image instead, which is what Latest is "
        "opened for")


def test_a_slideshow_of_another_folder_opens_on_the_filters_the_last_was_left_on(slideshows):
    host = FakeHost(location="workflow/a", rows=[_image("g1", "a red fox", seed=1)])
    director, host, made = slideshows(host)
    director.start()
    made[0].actions.filters_changed(SlideshowFilters(enhanced=True))
    made[0].close()

    host.location = "workflow/b"
    host.rows = [_image("g2", "a blue car", seed=2)]
    director.start()

    assert made[-1].taken_up == (SlideshowFilters(enhanced=True), False)


def test_the_next_launch_picks_up_the_slideshow_the_last_one_left(slideshows):
    rows = [_image("g1", "a red fox", seed=1)]
    director, _host, made = slideshows(FakeHost(location="workflow/a", rows=rows))
    director.start()
    left = SlideshowState(order=("g1",), current="g1", locked=True)
    made[0].state_at_close = left
    made[0].actions.filters_changed(SlideshowFilters(enhanced=True))
    made[0].close()

    relaunched, _host, _made = slideshows(FakeHost(location="workflow/a", rows=rows))
    relaunched.remember(json.loads(json.dumps(director.remembered())))
    relaunched.start()

    assert made[-1].resumed == replace(left, location="workflow/a")
    assert made[-1].taken_up == (SlideshowFilters(enhanced=True), False)


def test_a_new_session_opens_its_regions_at_standalones_clip_seconds_again(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director._pace.set_seconds(6)
    director.open([("a.png", "image", "g1", None)], shape=PORTRAIT)
    made[-1].pace.step(3)

    director.become_standalone(motion=None)
    director.become_hosted(FakeSession())
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    assert made[-1].pace.seconds == 6


def test_the_next_launch_opens_its_slideshows_at_the_pace_the_last_one_was_left_at(slideshows):
    director, _host, _made = slideshows()
    director._pace.set_seconds(9)

    relaunched, _host, _made = slideshows()
    relaunched.remember(json.loads(json.dumps(director.remembered())))

    assert relaunched._pace.seconds == 9


def test_the_next_launch_wears_the_hud_where_the_last_one_left_it(slideshows):
    director, _host, _made = slideshows()
    director.move_the_hud("right", shape=LANDSCAPE)
    director.collapse_the_hud(True, shape=LANDSCAPE)

    relaunched, _host, _made = slideshows()
    relaunched.remember(json.loads(json.dumps(director.remembered())))

    assert relaunched.hud_place(LANDSCAPE) == (HudCorner.UPPER_RIGHT, True)
    assert relaunched.hud_place(PORTRAIT) == (HudCorner.UPPER_LEFT, False)


def test_a_hud_opened_in_a_corner_is_there_and_open_on_the_next_launch(slideshows):
    director, _host, _made = slideshows()
    director.collapse_the_hud(True, shape=LANDSCAPE)

    director.open_the_hud_in(HudCorner.LOWER_RIGHT, shape=LANDSCAPE)

    relaunched, _host, _made = slideshows()
    relaunched.remember(json.loads(json.dumps(director.remembered())))
    assert relaunched.hud_place(LANDSCAPE) == (HudCorner.LOWER_RIGHT, False)


def test_the_favorites_collection_holds_f_mode_down_without_turning_it_on_for_the_next(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    folder = shaped_key("workflow/a", PORTRAIT)
    favorites = shaped_key(FolderCollection(FAVORITES_KEY, "workflow/a").key, PORTRAIT)
    host = FakeHost(location=favorites, rows=[rows[0]], groups={folder: _folder_of(rows)})
    director, host, made = slideshows(host)
    director.start()
    made[0].close()

    host.location = folder
    director.start()

    assert made[0].taken_up == (SlideshowFilters(favorites=True), False)
    assert made[-1].taken_up == (SlideshowFilters(), False)


def test_a_slideshow_of_latest_opens_on_the_newest_under_the_one_filter_state(slideshows):
    director, _host, made = slideshows(FakeHost(location=LATEST_PORTRAIT, rows=_a_sitting()))
    director._note_filters(SlideshowFilters(enhanced=True))

    director.start()

    assert made[0].resumed is None
    assert made[0].taken_up == (SlideshowFilters(enhanced=True), False)


def test_a_double_clicked_item_opens_under_the_one_filter_state_and_stays_up(slideshows):
    host = FakeHost(rows=[_row("a1"), _row("a2")])
    director, _host, made = slideshows(host)
    director._note_filters(SlideshowFilters(enhanced=True))

    director.open_in_its_folder(("a2.png", "image"), "a2")

    assert made[0].taken_up == (SlideshowFilters(enhanced=True), True)


def test_a_slideshow_of_a_folder_still_picks_up_where_the_last_one_stopped(slideshows):
    director, _host, made = slideshows(FakeHost(location="workflow/a",
                                                rows=[_image("g1", "a red fox", seed=1)]))
    director._slideshow_state = SlideshowState(order=["g1"], current="g1")

    director.start()

    assert made[0].resumed is director._slideshow_state



def _being_made(key, frame=b"frame"):
    return SimpleNamespace(key=key, reading=SimpleNamespace(frame=frame))


def test_how_the_enhancements_are_going_reaches_every_slideshow_that_is_up(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    director.note_enhancing({"g1": "running"})

    assert [slideshow.enhancing for slideshow in made] == [{"g1": "running"}] * 2


def test_what_each_slideshow_still_up_is_locked_on_is_known(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)
    made[0].locked_on = "g1"
    made[1].locked_on = "g2"
    made[1].visible = False

    assert director.locked_prompt_ids() == {"g1"}


def test_a_slideshow_opens_knowing_what_is_being_enhanced(slideshows):
    director, _host, made = slideshows()
    director.note_enhancing({"g1": "running"})

    director.open([("a.png", "image", "g1", None)])

    assert made[0].hud.enhancing == {"g1": "running"}


def test_a_slideshow_opened_with_no_slide_named_leads_with_the_run_being_generated(slideshows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    host.queue = ([_being_made("g-run")], 0)
    director, _host, made = slideshows(host=host, db=FakeDB([_row("g1"), _row("g-run")]))

    director.open([("a.png", "image", "g1", None)])

    assert made[0].generating == [("g-run", b"frame")]
    assert made[0].leads == 1


def test_a_run_with_no_frame_yet_is_no_slide(slideshows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    host.queue = ([_being_made("g-run", frame=None)], 0)
    director, _host, made = slideshows(host=host, db=FakeDB([_row("g1"), _row("g-run")]))

    director.open([("a.png", "image", "g1", None)])

    assert made[0].generating == [], (
        "a black screen saying a run is being generated is nothing to watch; it joins once its "
        "first frame comes in")


def test_a_slideshow_opened_on_a_named_slide_is_led_nowhere_else(slideshows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    host.queue = ([_being_made("g-run")], 0)
    director, _host, made = slideshows(host=host, db=FakeDB([_row("g1"), _row("g-run")]))

    director.open([("a.png", "image", "g1", None)], start=0)

    assert (made[0].generating, made[0].leads) == ([], 0)


def test_a_landed_enhancement_hands_every_slideshow_the_images_new_versions(
        slideshows, tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)
    director.versions_of = lambda rows: {"better.png": ["newer", "older"]}

    director.note_enhanced(_row("g1", files=("better.png",)))

    assert [slideshow.versions_added for slideshow in made] == [[{"better.png": ["newer", "older"]}]] * 2


def test_the_frames_of_the_enhancements_being_made_reach_every_slideshow_that_is_up(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], shape=PORTRAIT)

    director.note_enhancing({"g1": "running"}, frames={"g1": b"frame"})

    assert [slideshow.enhancing_frames for slideshow in made] == [{"g1": b"frame"}] * 2


def test_a_run_reaches_each_slideshow_whose_own_set_holds_it(slideshows):
    gallery_pane = FakeGalleryPane(collections={"collection/a": [_row("g1"), _row("g-run")],
                                       "collection/b": [_row("g2")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, db=FakeDB([_row("g-run")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="collection/b", shape=PORTRAIT)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == [("g-run", b"frame")]
    assert made[1].generating == []


def test_every_slideshow_that_is_up_hears_which_runs_are_still_being_made(slideshows):
    gallery_pane = FakeGalleryPane(collections={"collection/a": [_row("g1")], "collection/b": [_row("g2")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", shape=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="collection/b", shape=PORTRAIT)

    director.note_in_flight([_being_made("g-run", frame=None)])

    assert [slideshow.in_flight for slideshow in made] == [{"g-run"}, {"g-run"}]


def test_a_latest_slideshow_takes_a_new_run_after_the_gallery_pane_has_moved_on(slideshows):
    gallery_pane = FakeGalleryPane(collections={LATEST_LANDSCAPE: [_row("g1")]}, latest=False)
    director, _host, made = slideshows(gallery_pane=gallery_pane, db=FakeDB([_row("g-run")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_LANDSCAPE,
                  shape=LANDSCAPE)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == [("g-run", b"frame")]


def test_a_slideshow_of_one_kinds_latest_takes_a_new_run_of_that_kind_alone(slideshows):
    videos_latest = shaped_key(FolderCollection(LATEST_KEY, "video").key, LANDSCAPE)
    video_run = _row("v-run", workflow_name="wan22_i2v", files=("v-run.mp4",))
    gallery_pane = FakeGalleryPane(collections={videos_latest: [_row("v1", files=("v1.mp4",))]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, db=FakeDB([video_run, _row("i-run")]),
                                       fun_time=FakeSession())
    director.open([("v1.mp4", "video", "v1", None)], location=videos_latest, shape=LANDSCAPE)

    director.note_generating("i-run", b"frame")
    director.note_generating("v-run", b"frame")

    assert made[0].generating == [("v-run", b"frame")]


def test_a_latest_slideshow_turns_down_a_run_asked_for_in_the_other_shape(slideshows):
    run = _row("g-run")
    run["params_json"] = json.dumps({"width": 1024, "height": 768})
    gallery_pane = FakeGalleryPane(collections={LATEST_PORTRAIT: [_row("g1")]})
    director, _host, made = slideshows(gallery_pane=gallery_pane, db=FakeDB([run]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_PORTRAIT,
                  shape=PORTRAIT)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == []


def test_a_run_double_clicked_while_hosted_opens_its_folder_on_a_funestra_following_it(slideshows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    director, host, made = slideshows(host, db=FakeDB([_row("g-run")]), fun_time=FakeSession(
        funestras={PORTRAIT: object(), LANDSCAPE: object()}))
    host.queue = ([_being_made("g-run")], 0)

    director.open([], carrying=Carrying(folder_items=[("a.png", "image", "g1", None)]), start=0)

    assert made[0].items == [("a.png", "image", "g1", None)]
    assert made[0].generating == [("g-run", b"frame")]
    assert (made[0].follows, made[0].leads) == (1, 0)


def _a_session_side_with_its_opening_ready(slideshows, qtbot, gallery_pane):
    director, host, made = slideshows(gallery_pane=gallery_pane,
                                      fun_time=FakeSession(funestras={PORTRAIT: object()}))
    director.make_the_openings_ready()
    qtbot.waitUntil(lambda: director._openings.of(PORTRAIT) is not None)
    return director, host, made


class FakeRecords:
    def __init__(self, filed=None, loops=None):
        self.learned = []
        self.filed = filed or {}
        self.loops = loops or {}

    def loops_of(self, item):
        return self.loops.get(str(item), FiledLoops())

    def of(self, item):
        return 4.0

    def learn(self, items):
        self.learned.extend(items)

    def group_of(self, item, by_seed_group):
        return self.filed.get(str(item))


def test_a_slideshow_is_dealt_by_the_weights_the_app_keeps_and_by_none_where_it_keeps_none(
        slideshows):
    director, _host, made = slideshows(records=FakeRecords())
    director.open([("a.mp4", "video", "g1", None)], location="workflow/a")
    unweighted, _host, made_unweighted = slideshows()
    unweighted.open([("a.mp4", "video", "g1", None)], location="workflow/a")

    assert made[0].actions.weight_of("a.mp4") == 4.0
    assert made_unweighted[-1].actions.weight_of is None


def test_a_sides_opening_learns_the_weights_of_its_videos_while_it_is_made_ready(
        slideshows, qtbot):
    weights = FakeRecords()
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4"), _row("g5")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane, records=weights,
                                        fun_time=FakeSession(funestras={PORTRAIT: object()}))
    director.items_of = lambda rows: [("g4.png", "image", "g4", None),
                                      ("g5.mp4", "video", "g5", None)]

    director.make_the_openings_ready()
    qtbot.waitUntil(lambda: director._openings.of(PORTRAIT) is not None)

    assert weights.learned == ["g5.mp4"]


def test_a_side_with_its_opening_ready_opens_without_walking_the_library(
        slideshows, qtbot, monkeypatch):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4"), _row("g5")]})
    director, _host, made = _a_session_side_with_its_opening_ready(slideshows, qtbot, gallery_pane)

    def walked(_rows):
        raise AssertionError("walked the library on the press")

    monkeypatch.setattr(director, "items_of", walked)
    monkeypatch.setattr(director, "versions_of", walked)

    director.fill_the_region(PORTRAIT)

    assert [item[2] for item in made[-1].items] == ["g4", "g5"]


def test_a_side_left_on_its_whole_library_comes_back_without_walking_the_library(
        slideshows, qtbot, monkeypatch):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4"), _row("g5")]})
    director, _host, made = _a_session_side_with_its_opening_ready(slideshows, qtbot, gallery_pane)
    director.remember_regions({PORTRAIT: {"state": {"current": "g5", "location": ALL_PORTRAIT},
                                          "filters": {}}})

    def walked(_rows):
        raise AssertionError("walked the library on the press")

    monkeypatch.setattr(director, "items_of", walked)
    monkeypatch.setattr(director, "versions_of", walked)

    director.fill_the_region(PORTRAIT)

    assert made[-1].resumed.current == "g5"
    assert made[-1].items[made[-1].opened_with["start"]][2] == "g5"


def test_the_library_moving_leaves_no_opening_from_before_it(slideshows, qtbot):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = _a_session_side_with_its_opening_ready(slideshows, qtbot, gallery_pane)

    gallery_pane.collections[ALL_PORTRAIT] = [_row("g4"), _row("g5")]
    director.library_moved()
    director.fill_the_region(PORTRAIT)

    assert [item[2] for item in made[-1].items] == ["g4", "g5"]


def test_a_side_let_go_gets_its_next_opening_ready(slideshows, monkeypatch):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane,
                                        fun_time=FakeSession(funestras={PORTRAIT: object()}))
    director.fill_the_region(PORTRAIT)
    asked = []
    monkeypatch.setattr(director._openings, "make_ready", asked.append)

    director.close_the_slideshow(PORTRAIT)

    assert asked == [PORTRAIT]


def test_nothing_is_made_ready_for_a_side_with_a_slideshow_up_or_no_funestra(
        slideshows, monkeypatch):
    gallery_pane = FakeGalleryPane(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(gallery_pane=gallery_pane,
                                        fun_time=FakeSession(funestras={PORTRAIT: object()}))
    director.fill_the_region(PORTRAIT)
    asked = []
    monkeypatch.setattr(director._openings, "make_ready", asked.append)

    director.make_the_openings_ready()

    assert asked == []


def _group_of_on_the_portrait_side(director, made):
    director.open([("a.mp4", "video", "g1", None)], location="workflow/a", shape="portrait")
    return made[-1].actions.group_of


def _groups_of(group_of) -> dict:
    return {prompt_id: group_of(Slide(f"{prompt_id}.mp4", "video", prompt_id), False)
            for prompt_id in ("g1", "v1", "v2", "v3", "o1", "o2")}


def test_a_slideshow_groups_what_it_made_by_its_image_and_another_sites_videos_by_their_records(
        slideshows, tmp_path):
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="g2.png", action="alpha", tmp_path=tmp_path),
            _animation("v3", frame="g1.png", action="beta", tmp_path=tmp_path),
            _a_sites(_animation("o1", frame="g1.png", action="beta", tmp_path=tmp_path)),
            _a_sites(_animation("o2", frame="g2.png", action="beta", tmp_path=tmp_path))]
    filed = {"o1.mp4": "img|one image", "o2.mp4": "img|one image"}
    director, _host, made = slideshows(_library(rows), db=FakeDB(rows), records=FakeRecords(filed))

    groups = _groups_of(_group_of_on_the_portrait_side(director, made))

    assert groups["g1"] == groups["v1"] == groups["v3"]
    assert groups["v2"] != groups["v1"]
    assert groups["o1"] == groups["o2"] != groups["g1"]


def _hidden_frame(prompt_id: str) -> dict:
    return {**_fox(prompt_id, seed=1), "source": GenerationSource.STARTING_FRAME}


def test_videos_made_from_one_hidden_starting_frame_are_one_group_in_the_list(
        slideshows, tmp_path):
    rows = [_hidden_frame("h1"), _hidden_frame("h2"),
            _animation("v1", frame="h1.png", action="alpha", tmp_path=tmp_path),
            _animation("v2", frame="h1.png", action="beta", tmp_path=tmp_path),
            _animation("v3", frame="h2.png", action="alpha", tmp_path=tmp_path)]
    director, _host, made = slideshows(_library(rows), db=FakeDB(rows), records=FakeRecords())

    groups = _groups_of(_group_of_on_the_portrait_side(director, made))

    assert groups["v1"] == groups["v2"] != groups["v3"]


def test_a_video_made_here_from_another_sites_videos_starting_frame_is_in_that_videos_group(
        slideshows, tmp_path):
    rows = [_hidden_frame("h1"), _hidden_frame("h2"),
            _a_sites(_animation("o1", frame="h1.png", action="alpha", tmp_path=tmp_path)),
            _animation("v1", frame="h1.png", action="beta", tmp_path=tmp_path),
            _a_sites(_animation("o2", frame="h2.png", action="alpha", tmp_path=tmp_path))]
    filed = {"o1.mp4": "t2v|one", "o2.mp4": "t2v|two"}
    director, _host, made = slideshows(_library(rows), db=FakeDB(rows), records=FakeRecords(filed))

    groups = _groups_of(_group_of_on_the_portrait_side(director, made))

    assert groups["o1"] == groups["v1"] != groups["o2"]


def _another_sites_videos_on_file(slideshows, tmp_path, loops):
    rows = [_a_sites(_animation("o1", frame="h1.png", action="alpha", tmp_path=tmp_path)),
            _a_sites(_animation("o2", frame="h1.png", action="beta", tmp_path=tmp_path)),
            _a_sites(_animation("o3", frame="h2.png", action="alpha", tmp_path=tmp_path)),
            _fox("g1", seed=1),
            {**_animation("v1", frame="g1.png", action="gamma", tmp_path=tmp_path),
             "workflow_name": "another_workflow"}]
    records = FakeRecords(loops=loops)
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows), records=records)
    director.items_of = lambda rows: [
        (f"{row['prompt_id']}.mp4", "video", row["prompt_id"], None) for row in rows]
    return director, records


def test_another_sites_video_is_mapped_with_the_videos_its_record_groups_it_with(
        slideshows, tmp_path):
    director, _records = _another_sites_videos_on_file(
        slideshows, tmp_path, {"o1.mp4": FiledLoops(actions=("o2.mp4",), seeds=("o3.mp4",))})

    around = director.neighbors_of("o1", shape="portrait")

    assert around.label == "alpha"
    assert [slide.prompt_id for slide in around.seeds] == ["o3"]
    assert [(row.label, row.slide.prompt_id) for row in around.column] == [("beta", "o2")]
    assert [slide.prompt_id for slide in around.group] == ["o2"]


def test_the_records_of_every_video_another_site_made_are_learned_before_one_is_mapped(
        slideshows, tmp_path):
    director, records = _another_sites_videos_on_file(slideshows, tmp_path, {})

    director.neighbors_of("o1", shape="portrait")
    director.neighbors_of("o2", shape="portrait")

    assert records.learned == ["o1.mp4", "o2.mp4", "o3.mp4"]


def test_a_video_its_record_groups_with_none_in_the_gallery_is_mapped_alone(slideshows, tmp_path):
    director, _records = _another_sites_videos_on_file(
        slideshows, tmp_path, {"o1.mp4": FiledLoops(actions=("gone from the gallery.mp4",))})

    around = director.neighbors_of("o1", shape="portrait")

    assert (around.seeds, around.column, around.group) == ((), (), ())


def test_what_was_made_here_from_another_sites_video_stays_on_its_map_beside_its_records_group(
        slideshows, tmp_path):
    frame = {**_fox("h1", seed=1), "source": GenerationSource.STARTING_FRAME}
    rows = [frame,
            _a_sites(_animation("o1", frame="h1.png", action="alpha", tmp_path=tmp_path)),
            _a_sites(_animation("o2", frame="h2.png", action="beta", tmp_path=tmp_path)),
            _animation("v1", frame="h1.png", action="gamma", tmp_path=tmp_path)]
    records = FakeRecords(loops={"o1.mp4": FiledLoops(actions=("o2.mp4",))})
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows), records=records)
    director.items_of = lambda rows: [
        (f"{row['prompt_id']}.mp4", "video", row["prompt_id"], None) for row in rows]

    around = director.neighbors_of("o1", shape="portrait")

    assert [slide.prompt_id for slide in around.group] == ["o2", "v1"]
    assert [(row.label, row.slide.prompt_id) for row in around.column] == [
        ("beta", "o2"), ("gamma", "v1")]


def test_a_video_with_no_action_has_its_row_in_the_column_of_another_sites_video(
        slideshows, tmp_path):
    rows = [_a_sites(_animation("o1", frame="h1.png", action="alpha", tmp_path=tmp_path)),
            _a_sites(_animation("o2", frame="h1.png", action="", tmp_path=tmp_path))]
    records = FakeRecords(loops={"o1.mp4": FiledLoops(actions=("o2.mp4",))})
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows), records=records)
    director.items_of = lambda rows: [
        (f"{row['prompt_id']}.mp4", "video", row["prompt_id"], None) for row in rows]

    around = director.neighbors_of("o1", shape="portrait")

    assert [(row.label, row.slide.prompt_id) for row in around.column] == [("", "o2")]


def test_an_image_another_site_made_keeps_the_map_the_gallery_gives_it(slideshows, tmp_path):
    rows = [_a_sites(_fox("g1", seed=1)),
            _animation("v1", frame="g1.png", action="alpha", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows), records=FakeRecords())

    around = director.neighbors_of("g1", shape="portrait")

    assert [slide.prompt_id for slide in around.group] == ["v1"]


def test_more_seeds_of_another_sites_video_are_the_ones_its_record_widens_to(slideshows, tmp_path):
    director, _records = _another_sites_videos_on_file(
        slideshows, tmp_path, {"o1.mp4": FiledLoops(more_seeds=("o3.mp4",))})

    assert [slide.prompt_id
            for slide in director.beyond_the_row_of("o1", shape="portrait")] == ["o3"]


def test_a_video_with_no_group_on_its_record_is_a_group_of_its_own(slideshows, tmp_path):
    rows = [_a_sites(_animation("o1", frame="g1.png", action="beta", tmp_path=tmp_path))]
    director, _host, made = slideshows(_library(rows), db=FakeDB(rows), records=FakeRecords())

    group_of = _group_of_on_the_portrait_side(director, made)

    assert group_of(Slide("o1.mp4", "video", "o1"), False) is None
