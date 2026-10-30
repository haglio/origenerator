"""The fullscreen slideshows, driven with no gallery and no Qt around them.

Every behaviour here used to need a 7,000-line widget and a real window on a
monitor to reach: what a slideshow is offered when a generation lands, which runs it
turns down, what happens to a satellite region when the slideshow covering it ends,
and what the spoken words about a slideshow do. The slideshow itself is a recorder, the
host a handful of recorded calls.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest
from funestra.hud_placement import HudCorner
from funestra.hud_title import LATEST_LABEL, SHUFFLE_LABEL
from PIL import Image
from PyQt6.QtCore import QRect, Qt

from origenerator import gallery
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    FolderCollection,
)
from origenerator.gallery.sides import BOTH
from origenerator.generation_state import GenerationSource
from origenerator.gui import slideshow_director as module
from origenerator.gui.notice_overlay import FAVORITE, NOTICE, WARNING
from origenerator.gui.slideshow_director import SlideshowDirector
from origenerator.gui.slideshow_pace import DEFAULT_S as DEFAULT_PACE_S
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.item_names import ItemNames
from origenerator.orientation import oriented_key
from origenerator.output_places import OutputPlaces
from origenerator.slideshow import Slide, SlideshowFilters, SlideshowState
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.slideshow_commands import SlideshowCommand
from tests.slideshow_hud_support import open_both_sides

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
# What a region plays with nothing else asked for: the whole library,
# narrowed to that region's shape.
ALL_PORTRAIT = oriented_key(gallery.ALL_KEY, PORTRAIT)
ALL_LANDSCAPE = oriented_key(gallery.ALL_KEY, LANDSCAPE)
LATEST_PORTRAIT = oriented_key(RECENTS_KEY, PORTRAIT)
LATEST_LANDSCAPE = oriented_key(RECENTS_KEY, LANDSCAPE)
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
    """A slideshow reduced to what the director asks of one."""

    def __init__(self, items=(), *, actions=None, pace=None, hud=None, **kwargs):
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
        self.levels = None
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
        self.hud_order_label = SHUFFLE_LABEL
        self.hud_favorites_filter = False
        self.hud_enhanced_mode = False
        self.enhanced_items = []
        self.steps = []
        self.culled = 0
        self.favoritable = True
        self.favorites = 0
        self.released = []
        self.pause_raises = False
        self.state_at_close = SlideshowState()
        self.played = []
        self.leads = 0
        self.follows = 0
        self.levels_added = []
        self.hud_order_label = ""
        self.locked_on = None
        self.shown_locked = []
        self.done = []

    # what a slideshow is, and what it holds
    def holds(self, prompt_id):
        return prompt_id in self.ids

    def state(self):
        return self.state_at_close

    def whole_set(self):
        return [Slide.of(item) for item in self.items]

    def is_showing(self):
        return self.visible

    # what the director tells it
    def play(self, items, *, hud=None, **kwargs):
        self.items = list(items)
        self.hud = hud
        self.played.append(list(items))

    def set_levels(self, levels):
        self.levels = levels

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

    def note_added(self, path, media_type, prompt_id, thumb, *, favorite, enhanced):
        self.added.append((prompt_id, favorite, enhanced))

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

    def add_levels(self, levels):
        self.levels_added.append(levels)

    def note_voice_command(self, message, *, kind=NOTICE):
        self.said.append(message)
        self.said_kinds.append(kind)

    def note_voice_run(self, prompt_id, message, *, kind=NOTICE):
        self.runs_said.append((prompt_id, message))

    def set_paused(self, paused):
        if self.pause_raises:
            raise RuntimeError("this slideshow will not freeze")
        self.paused = paused

    def release_media(self, paths):
        self.released.append(list(paths))

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

    def clear_modes(self):
        self.hud_favorites_filter = False
        self.hud_enhanced_mode = False

    def pass_size(self):
        return len(self.enhanced_items)

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
    """Where a slideshow handed to one of a session's Funestras is seen: on the
    session's own window, which draws the panel this app publishes for it."""

    def __init__(self) -> None:
        self.queue_set = None

    def set_queue(self, items, foreign_total):
        self.queue_set = (list(items), foreign_total)


class FakeWindow:
    """The window a slideshow of this app's own is drawn in, reduced to what the
    director asks of it."""

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
    """A hosting Fun Time session reduced to the three things a slideshow asks of one.

    *Funestras* is which sides it hands over as Funestras, by the channel it names
    for each; a side it names none for is one a window of this app's covers.
    """

    dashboard_cmd_file = None

    def __init__(self, funestras=None):
        self.funestras = funestras or {}

    def region_rect(self, side):
        return FakeRect(0 if side == LANDSCAPE else 1920, 0, 960, 540)

    def funestra(self, side):
        return self.funestras.get(side)


class FakeJobQueue:
    def __init__(self):
        self.moved = []

    def move(self, key, before):
        self.moved.append((key, before))


class FakeBrowser:
    """The middle pane reduced to the questions a slideshow asks of it.

    Its gallery reads as new at every look unless a test gives it a *stamp*,
    since most tests here change its collections between looks."""

    def __init__(self, collections=None, recents=False, searching=False, stamp=None):
        self.collections = collections or {}
        self.recents = recents
        self.searching = searching
        self.stamp = stamp
        self.collections_asked = 0

    def rows_for_collection(self, key):
        self.collections_asked += 1
        return self.collections.get(key)

    def model_stamp(self):
        return object() if self.stamp is None else self.stamp

    def showing_recents(self):
        return self.recents

    def showing_search(self):
        return self.searching


class FakeDB:
    def __init__(self, rows=(), requests=()):
        self.rows = {row["prompt_id"]: row for row in rows}
        self.requests = {record["prompt_id"]: record for record in requests}

    def get_request(self, prompt_id):
        return self.requests.get(prompt_id)

    def list_generations(self):
        return list(self.rows.values())

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)

    def folder_meta_map(self):
        return {}


class FakeHost:
    """A gallery reduced to what the slideshows ask of one."""

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

    def slideshow_location(self):
        return self.location

    def rows_to_play(self):
        return self.rows

    def slideshow_subject(self):
        return "this folder"

    def side_in_view(self):
        return LANDSCAPE

    def group_for_key(self, key):
        return self.groups.get(key)

    def row_for(self, prompt_id):
        return next((r for r in self.rows if r["prompt_id"] == prompt_id), None)

    def image_config_index(self):
        return {}

    def listed_prompt_ids(self):
        return list(self.visible)

    def selected_prompt_ids(self):
        return list(self.picked)

    def queue_now(self):
        return self.queue

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

    # The app's one OSR2 switch, handed to a slideshow whole: a host with no device
    # (which is every host here) has none to hand over.
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
    """The slideshow button only needs to know that something can play. Reading
    every row's files to answer it is what made one click on the folder list
    redraw for seconds: five of these go into a single redraw."""
    director, _host, _made = slideshows(FakeHost(rows=[_row(f"g{n}") for n in range(50)]))
    del director.items_of  # the fixture's stand-in, so the real one answers
    read = []

    def resolve(row, _output_dir):
        read.append(row["prompt_id"])
        return (f"{row['prompt_id']}.png", "image")

    monkeypatch.setattr(module.gallery, "resolve_preview", resolve)

    assert director.anything_to_play()
    assert read == ["g0"]


def test_asking_whether_anything_can_play_lists_no_folder_of_upscales(slideshows, monkeypatch):
    # An upscale changes which file a slide plays, never whether there is one,
    # and every click on the folder list asks this several times over.
    director, _host, _made = slideshows(FakeHost(rows=[_row("g0")]))
    del director.items_of
    monkeypatch.setattr(module.gallery, "resolve_preview",
                        lambda row, _places: (f"{row['prompt_id']}.png", "image"))
    scanned = []
    monkeypatch.setattr(module.EvolverUpscales, "scan",
                        lambda *args: scanned.append(args) or module.EvolverUpscales({}))

    assert director.anything_to_play()
    assert scanned == []


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
    """A director whose slideshows are recorders and whose HUD panel is absent."""
    made = []

    def build_slideshow(items, **kwargs):
        slideshow = FakeSlideshow(items, **kwargs)
        made.append(slideshow)
        return slideshow

    def build_window(items, *, motion=None, **kwargs):
        return FakeWindow(build_slideshow(items, **kwargs), motion=motion)

    monkeypatch.setattr(module, "SlideshowView", build_window)
    monkeypatch.setattr(module, "FunestraSlideshow", build_slideshow)
    monkeypatch.setattr(module.SlideshowDirector, "_wear_the_hud", lambda self, view, side: None)
    monkeypatch.setattr(module, "place_window_in_device_pixels",
                        lambda *args: None)
    monkeypatch.setattr(module, "_screens", list)

    def build(host=None, *, db=None, browser=None, fun_time=None):
        host = host or FakeHost()
        db = db or FakeDB()
        director = SlideshowDirector(
            host, db=db, browser=browser or FakeBrowser(),
            jobs=FakeJobQueue(), pace=SlideshowPace(), motion=None,
            fun_time=fun_time, names=ItemNames(db))
        host.slideshows = director
        # The playlist is what a slideshow is of; deriving it from files on disk is
        # resolve_preview's own tested job, not this one's.
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
    # Standalone there is one screen, so there is one slideshow. A second set asked
    # for while one is up -- by voice, or from the window Alt+Tab reaches --
    # re-points the slideshow that is there rather than stacking another over it.
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)], location="collection/a")

    again = director.open([("b.png", "image", "g2", None)], location="collection/b")

    assert made == [again]
    assert again.played == [[("b.png", "image", "g2", None)]]
    assert director._live_slideshows == [(again, "collection/b")]


def test_a_double_clicked_item_plays_its_folder_newest_first_and_says_latest(slideshows):
    """The gallery lists a folder's newest generation first and this slideshow plays
    it in that order, which is the order Latest plays — so the panel lights
    Latest over it rather than leaving both of the order pair dark."""
    host = FakeHost(rows=[_row("a2"), _row("a1")])
    host.visible = ["a2", "a1"]
    director, _host, made = slideshows(host)

    director.open_on_preview(("a2.png", "image"), "a2")

    (slideshow,) = made
    assert slideshow.hud.order_label == LATEST_LABEL


def test_a_slideshow_put_back_goes_on_taking_in_what_lands_where_it_plays(slideshows):
    landed = _row("g2")
    director, _host, made = slideshows(browser=FakeBrowser(collections={"collection/a": [_row("g1"), landed]}))
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


def test_a_folder_s_modify_landing_leaves_a_slideshow_locked_on_its_original(slideshows):
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
    assert slideshow.levels == {"t1.png": ["newer", "older"]}


def test_one_of_two_hosted_slideshows_closing_leaves_the_other_showing(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    made[1].close()

    assert director.showing is made[0]


def test_a_director_taken_into_a_session_closes_its_fullscreen_slideshow_for_the_regions(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.become_hosted(FakeSession())
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    assert made[0].closes == 1
    assert director.region_slideshow(PORTRAIT) is made[1]
    assert made[1].shown.fullscreen == 0


def _shaped(prompt_id, params):
    return {**_row(prompt_id), "params_json": json.dumps(params)}


def _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, *, side=PORTRAIT, shapes=(TALL, TALL), monitor=PORTRAIT_MONITOR,
        standing=SlideshowState(order=("g2", "g1"), current="g1", locked=True)):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    rows = [_shaped(f"g{n}", params) for n, params in enumerate(shapes, start=1)]
    director, _host, made = slideshows(FakeHost(rows=rows), browser=browser)
    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, side=side, location="collection/a")
    watched = made[0]
    watched.shown.monitor = monitor
    watched.state_at_close = standing
    watched.filters = SlideshowFilters(favorites=True)
    director.become_hosted(FakeSession())
    return director, watched


def test_a_slideshow_up_when_a_session_takes_the_window_over_opens_on_its_side_as_it_was(slideshows):
    director, watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(slideshows)

    open_both_sides(director)

    carried = director.region_slideshow(PORTRAIT)
    assert [slide[2] for slide in carried.items] == ["g1", "g2"]
    assert carried.resumed == replace(watched.state_at_close, location="collection/a")
    assert carried.taken_up == (SlideshowFilters(favorites=True), False)
    assert [slide[2] for slide in director.region_slideshow(LANDSCAPE).items] == ["g5"]


@pytest.mark.parametrize(("side", "shapes", "monitor", "carried_to", "the_other", "its_library"), [
    (LANDSCAPE, (WIDE, WIDE), PORTRAIT_MONITOR, LANDSCAPE, PORTRAIT, ["g4"]),
    (PORTRAIT, (TALL, TALL), LANDSCAPE_MONITOR, PORTRAIT, LANDSCAPE, ["g5"]),
])
def test_a_slideshow_taken_over_opens_on_the_funestra_of_its_shape_whatever_monitor_it_was_on(
        slideshows, side, shapes, monitor, carried_to, the_other, its_library):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, side=side, shapes=shapes, monitor=monitor)

    open_both_sides(director)

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
        slideshows, side=BOTH, shapes=shapes, monitor=monitor)

    open_both_sides(director)

    assert [slide[2] for slide in director.region_slideshow(PORTRAIT).items] == tall
    assert [slide[2] for slide in director.region_slideshow(LANDSCAPE).items] == wide


def test_a_slideshow_taken_over_on_an_item_of_the_other_shape_goes_on_from_the_next_of_its_own(
        slideshows):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(
        slideshows, side=BOTH, shapes=(TALL, WIDE, TALL), standing=SlideshowState(
            order=("g1", "g2", "g3"), current="g2", locked=True, level_index=1))

    open_both_sides(director)

    assert director.region_slideshow(PORTRAIT).resumed == SlideshowState(
        order=("g1", "g3"), current="g3", location="collection/a")


@pytest.mark.parametrize(("side", "monitor"), [(PORTRAIT, PORTRAIT_MONITOR),
                                                (LANDSCAPE, LANDSCAPE_MONITOR)])
def test_a_slideshow_on_its_own_opens_full_screen_on_the_monitor_of_its_shape(
        slideshows, monkeypatch, side, monitor):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], side=side)

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
                   for row in rows], rows=rows, side=BOTH)

    assert made[0].shown.geometry == monitor.getRect()


@pytest.mark.parametrize(("shapes", "monitor"), [((TALL, TALL, WIDE), LANDSCAPE_MONITOR),
                                                  ((WIDE, WIDE, TALL), PORTRAIT_MONITOR)])
def test_a_slideshow_of_both_shapes_opened_on_an_item_goes_to_that_items_monitor(
        slideshows, monkeypatch, shapes, monitor):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate(shapes)]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, side=BOTH, start=2)

    assert made[0].shown.geometry == monitor.getRect()


def test_a_slideshow_of_both_shapes_coming_back_to_an_item_goes_to_that_items_monitor(
        slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate((TALL, TALL, WIDE))]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, side=BOTH,
                  resume=SlideshowState(order=("g0", "g1", "g2"), current="g2"))

    assert made[0].shown.geometry == LANDSCAPE_MONITOR.getRect()


def test_a_slideshow_of_the_other_shape_asked_for_while_one_is_up_moves_to_its_monitor(
        slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)

    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    (slideshow,) = made
    assert (slideshow.shown.geometry, slideshow.shown.isFullScreen()) == (
        PORTRAIT_MONITOR.getRect(), True)


def test_a_slideshow_asked_for_again_on_the_monitor_it_is_on_stays_put(slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS)
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    assert made[0].shown.fullscreen == 1


def test_a_slideshow_with_no_monitor_of_its_shape_opens_full_screen_where_it_always_did(
        slideshows, monkeypatch):
    monkeypatch.setattr(module, "_screens", lambda: HIS_TWO_MONITORS[:1])
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert (made[0].shown.geometry, made[0].shown.fullscreen) == (None, 1)


def test_the_slideshow_a_session_took_over_is_put_back_on_the_first_opening_only(slideshows):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(slideshows)
    open_both_sides(director)

    director.close_the_slideshows()
    open_both_sides(director)

    assert [slide[2] for slide in director.region_slideshow(PORTRAIT).items] == ["g4"]


def test_a_window_handed_back_before_its_regions_opened_lets_go_of_the_slideshow_it_held(slideshows):
    director, _watched = _a_slideshow_he_is_watching_when_the_session_takes_the_window_over(slideshows)

    director.become_standalone(motion=None)
    director.become_hosted(FakeSession())
    open_both_sides(director)

    assert [slide[2] for slide in director.region_slideshow(PORTRAIT).items] == ["g4"]


def test_a_director_names_the_shape_of_a_slideshow_it_could_hand_a_session(slideshows):
    director, _host, made = slideshows()
    assert director.slideshow_showing_on() is None

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
    assert director.slideshow_showing_on() == PORTRAIT

    made[0].close()
    assert director.slideshow_showing_on() is None


def test_a_director_names_both_shapes_for_a_slideshow_of_both(slideshows):
    director, _host, _made = slideshows()
    rows = [_shaped(f"g{n}", params) for n, params in enumerate((TALL, WIDE))]

    director.open([(f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
                   for row in rows], rows=rows, side=BOTH)

    assert director.slideshow_showing_on() == BOTH


def test_a_region_opens_armed_with_the_versions_of_the_library_it_plays(slideshows):
    """A slideshow on a Funestra opens on its side's whole library, which the browser
    is not listing — so versions read off the browser's rows named none of the
    slides on screen, and every versions button on the band was drawn faded
    however many enhancements that library held (2026-09-19)."""
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    director, host, made = slideshows(browser=browser, fun_time=FakeSession())
    assert host.visible == []  # the browser is somewhere else entirely
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}

    open_both_sides(director)

    assert director.region_slideshow(PORTRAIT).levels == {"g4.png": ["newer", "older"]}
    assert director.region_slideshow(LANDSCAPE).levels == {"g5.png": ["newer", "older"]}


def test_a_sessions_regions_open_on_their_base_state_whatever_was_pressed(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    made[0].actions.filters_changed(SlideshowFilters(enhanced=True))
    made[0].close()

    open_both_sides(director)

    assert director.region_slideshow(PORTRAIT).taken_up == (SlideshowFilters(), False)
    assert director.region_slideshow(LANDSCAPE).taken_up == (SlideshowFilters(), False)


def test_a_region_says_how_long_it_took_to_fill(slideshows, caplog):
    """The wait the owner is judging when he presses the button that brings
    this mode up -- the one between the press and the slides -- named in the
    line that says the region opened, so a slow one can be read off the log
    instead of counted off a stopwatch."""
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = slideshows(browser=browser, fun_time=FakeSession())

    with caplog.at_level("INFO", logger="origenerator.gui.slideshow_director"):
        open_both_sides(director)

    opened = [record.message for record in caplog.records if "region opens" in record.message]
    assert len(opened) == 2
    assert all(re.search(r", filled in \d+ ms$", message) for message in opened), opened


def test_a_director_handed_back_from_a_session_gives_up_its_regions_for_a_fullscreen_slideshow(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    open_both_sides(director)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
    motion = object()

    director.become_standalone(motion)
    director.open([("b.png", "image", "g2", None)])

    assert made[0].closes == 1
    assert director.region_slideshow(PORTRAIT) is None
    assert director.showing is made[-1]
    assert made[-1].shown.fullscreen == 1 and made[-1].shown.motion is motion


def test_a_landing_reaches_the_slideshow_whose_own_folder_holds_it(slideshows):
    # Asked of each slideshow's OWN location rather than of the browser, which has
    # usually moved on by the time a generation lands.
    # On the two regions, which is the only place two slideshows are up at once:
    # standalone the monitor's one slideshow takes over the new set instead.
    browser = FakeBrowser(collections={"collection/a": [_row("g9")], "collection/b": []})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a",
                  side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="collection/b",
                  side=PORTRAIT)

    director.note_finished(_row("g9", favorite=True))

    assert made[0].added == [("g9", True, False)]
    assert made[1].added == []


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
    # It is a better version of an image the slideshow may already be playing, and a
    # half-rendered second slide would be the same image twice, one of them worse.
    enhance = _row("g8", workflow_name="enhance_image")
    host = FakeHost(rows=[_row("g1"), enhance])
    director, _host, made = slideshows(host, db=FakeDB([enhance]),
                                       browser=FakeBrowser(recents=True))
    enhance["workflow_name"] = gallery.ENHANCE_WORKFLOW
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g8", b"frame")

    assert made[0].generating == []


def test_a_run_turned_down_frame_after_frame_looks_at_the_slideshows_set_once(slideshows):
    """Every in-progress image asked each slideshow that was not playing the run
    whether it would, and answering collected that slideshow's whole set again -- on
    a region's base state, sorting the whole library by shape -- until Core
    stopped answering and Windows closed it (2026-10-07 23:31)."""
    browser = FakeBrowser(collections={"collection/a": [_row("g1")]}, stamp="one gallery")
    director, _host, made = slideshows(browser=browser, db=FakeDB([_row("g-run")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", side=LANDSCAPE)
    browser.collections_asked = 0

    for frame in (b"one", b"two", b"three"):
        director.note_generating("g-run", frame)

    assert made[0].generating == []
    assert browser.collections_asked == 1


def test_a_run_a_collection_lists_only_after_the_next_rebuild_joins_on_the_frame_after_it(slideshows):
    browser = FakeBrowser(collections={"collection/a": [_row("g1")]}, stamp=1)
    director, _host, made = slideshows(browser=browser, db=FakeDB([_row("g7")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", side=LANDSCAPE)

    director.note_generating("g7", b"frame-one")
    browser.collections["collection/a"].append(_row("g7"))
    browser.stamp = 2
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == [("g7", b"frame-two")]


def test_a_run_of_the_folder_on_screen_joins_on_its_first_frame(slideshows):
    # Waiting for the file is waiting minutes for the one thing the slideshow is
    # being watched for.
    host = FakeHost(rows=[_row("g1"), _row("g5")])
    director, _host, made = slideshows(host, db=FakeDB([_row("g5")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g5", b"frame")

    assert made[0].generating == [("g5", b"frame")]


def test_a_landed_enhancement_reaches_every_surface(slideshows, tmp_path, monkeypatch):
    # An enhancement asked for from a slideshow lands minutes later, by which time it
    # has long paged on: an upgrade it doesn't take here it never takes at all.
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.note_enhanced(_row("g1", files=("better.png",)))

    assert [slideshow.enhanced for slideshow in made] == [
        [("g1", "image", None)], [("g1", "image", None)]]


def _evolver_upscaled_video(tmp_path, monkeypatch):
    """A video row with its file on disk, and the upscale Evolver made of it."""
    output = tmp_path / "output"
    video = output / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    os.utime(video, (1_000_000, 1_000_000))  # made well before its upscale
    library = tmp_path / "upscaled_by_orientation"
    upscale = library / "landscape" / "origenerator" / "clip_topaz.mp4"
    upscale.parent.mkdir(parents=True)
    upscale.write_bytes(b"upscale")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    monkeypatch.setattr(module, "EVOLVER_UPSCALED_DIR", library)
    return _row("g1", files=("clip.mp4",)), video, upscale


def _director():
    db = FakeDB()
    return SlideshowDirector(FakeHost(), db=db, browser=FakeBrowser(),
                             jobs=FakeJobQueue(), pace=SlideshowPace(), motion=None,
                             fun_time=None, names=ItemNames(db))


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
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    face = {"part": "faces", "left": 0.4, "top": 0.1, "right": 0.6, "bottom": 0.3}

    ((_key, (enhanced, original)),) = _director().versions_of([_enhanced_with([face])]).items()

    assert enhanced.points_of_interest == ((0.4, 0.1, 0.6, 0.3),)
    assert original.points_of_interest == ()


def test_the_eyes_of_two_faces_in_an_enhanced_image_come_back_as_a_close_up_of_each_pair(
        tmp_path, monkeypatch):
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    eyes = [{"part": "eyes", "left": left, "top": 0.1, "right": right, "bottom": 0.19}
            for left, right in ((0.10, 0.25), (0.20, 0.35), (0.33, 0.48), (0.43, 0.58))]

    ((_key, (enhanced, _original)),) = _director().versions_of([_enhanced_with(eyes)]).items()

    assert enhanced.points_of_interest == ((0.1, 0.1, 0.35, 0.19), (0.33, 0.1, 0.58, 0.19))


def test_a_region_reset_re_points_what_feeds_it(slideshows):
    # A generation landing in the library must reach a region that has been
    # reset back to the library, not the folder it used to be playing.
    browser = FakeBrowser(collections={ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reset_region(made[0])

    assert director._live_slideshows == [(made[0], ALL_LANDSCAPE)]
    assert made[0].retuned == ([("g4.png", "image", "g4", None)], set())


def test_a_set_handed_to_a_running_slideshow_brings_its_own_versions_with_it(slideshows):
    """Latest, Shuffle and a region reset each hand the slideshow a different set of
    its side's library.  A versions map still armed on the set the slideshow opened
    with names none of the images now on screen, so the band's versions button
    goes faded over a whole library of enhancements (2026-09-19)."""
    browser = FakeBrowser(collections={LATEST_LANDSCAPE: [_row("g9")],
                                       ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = slideshows(browser=browser,
                                       db=FakeDB([_row("g9"), _row("g4")]),
                                       fun_time=FakeSession())
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reorder_slideshow(made[0], True)
    assert made[0].levels == {"g9.png": ["newer", "older"]}

    director.reset_region(made[0])
    assert made[0].levels == {"g4.png": ["newer", "older"]}


def test_latest_points_a_region_slideshow_at_its_sides_latest_and_feeds_it_from_there(slideshows):
    two_images = [_image("g9", "a red fox", seed=9), _image("g4", "a blue car", seed=4)]
    browser = FakeBrowser(collections={LATEST_LANDSCAPE: two_images})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reorder_slideshow(made[0], True)

    assert made[0].reordered == (
        [("g9.png", "image", "g9", None), ("g4.png", "image", "g4", None)], True, set())
    assert director._live_slideshows == [(made[0], LATEST_LANDSCAPE)]
    assert made[0].said == ["Latest"]


def test_shuffle_points_a_region_slideshow_back_at_its_sides_whole_library(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")],
                                       LATEST_PORTRAIT: [_row("g9")]})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_PORTRAIT,
                  side=PORTRAIT)

    director.reorder_slideshow(made[0], False)

    assert made[0].reordered == ([("g4.png", "image", "g4", None)], False, set())
    assert director._live_slideshows == [(made[0], ALL_PORTRAIT)]
    assert made[0].said == ["Shuffle"]


def test_a_slideshow_on_its_own_takes_latest_of_the_shape_it_opened_on(slideshows):
    browser = FakeBrowser(collections={LATEST_PORTRAIT: [_row("g9")]})
    director, _host, made = slideshows(browser=browser)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    director.reorder_slideshow(made[0], True)

    assert made[0].reordered == ([("g9.png", "image", "g9", None)], True, set())


def test_an_order_with_nothing_to_play_says_so_and_leaves_the_slideshow_alone(slideshows):
    director, _host, made = slideshows(browser=FakeBrowser(collections={}), fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reorder_slideshow(made[0], True)

    assert made[0].reordered is None
    assert list(zip(made[0].said, made[0].said_kinds)) == [
        ("Nothing there to play", WARNING)]
    assert director._live_slideshows == [(made[0], "workflow/a")]


@pytest.mark.parametrize("session", [None, FakeSession()])
def test_a_slideshow_asks_this_director_for_its_order_hosted_or_not(slideshows, session):
    director, _host, made = slideshows(fun_time=session)

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].actions.reorder == director.reorder_slideshow


def test_a_loop_ending_on_a_folder_slideshow_hands_it_the_library_it_is_ordered_by(slideshows):
    browser = FakeBrowser(collections={ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    assert director.browse_it_all(made[0]) is True

    assert made[0].reordered == ([("g4.png", "image", "g4", None)], False, set())
    assert made[0].kept_the_slide is True
    assert director._live_slideshows == [(made[0], ALL_LANDSCAPE)]
    assert made[0].said == []               # the surface says "Loop off" itself


def test_a_slideshow_playing_latest_falls_back_to_latest_rather_than_to_the_shuffle(slideshows):
    browser = FakeBrowser(collections={LATEST_PORTRAIT: [_row("g9")],
                                       ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(browser=browser)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
    made[0].hud_order_label = LATEST_LABEL

    assert director.browse_it_all(made[0]) is True

    assert made[0].reordered == ([("g9.png", "image", "g9", None)], True, set())


def test_a_way_out_with_nothing_of_that_shape_to_play_leaves_the_slideshow_alone(slideshows):
    director, _host, made = slideshows(browser=FakeBrowser(collections={}))
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=PORTRAIT)

    assert director.browse_it_all(made[0]) is False

    assert made[0].reordered is None
    assert director._live_slideshows == [(made[0], "workflow/a")]


def test_a_second_set_in_the_one_window_brings_its_own_sides_library_with_it(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")],
                                       ALL_LANDSCAPE: [_row("g7")]})
    director, _host, made = slideshows(browser=browser)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    director.open([("b.png", "image", "g2", None)], side=LANDSCAPE)

    assert director.browse_it_all(made[0]) is True
    assert made[0].reordered == ([("g7.png", "image", "g7", None)], False, set())


def test_a_slideshow_asks_this_director_for_the_way_out_of_a_loop(slideshows):
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].actions.browse_all == director.browse_it_all


def test_a_region_slideshow_ending_comes_back_on_the_base_state(slideshows):
    # In origenerator mode the Funestra underneath is blacked for the whole mode,
    # so a region left empty is a black rectangle rather than a fallback.
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    open_both_sides(director)
    first = director.region_slideshow(PORTRAIT)

    first.close()

    assert director.region_slideshow(PORTRAIT) is not first
    assert director.region_slideshow(PORTRAIT) is not None


def test_closing_the_slideshows_drops_the_wanting_before_it_closes_anything(slideshows):
    # A slideshow closing while the mode still wants its regions is refilled with the
    # base state, and these closes must not be.
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(browser=browser, fun_time=FakeSession())
    open_both_sides(director)

    director.close_the_slideshows()
    director.fill_the_wanted_regions()

    assert director.region_slideshow(PORTRAIT) is None


def test_a_side_handed_over_alone_opens_on_that_side_alone(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")], ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = slideshows(browser=browser, fun_time=FakeSession())

    director.fill_the_region(PORTRAIT)

    assert director.region_slideshow(PORTRAIT) is not None
    assert director.region_slideshow(LANDSCAPE) is None


def test_a_side_let_go_alone_stays_empty_and_leaves_the_other_playing(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")], ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = slideshows(browser=browser, fun_time=FakeSession())
    open_both_sides(director)
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
    """A slideshow started in the gallery on a side whose Funestra is still in
    Kino mode: the session is asked for that Funestra, and the slideshow opens there
    once the session hands it over, rather than the side's library."""
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(browser=browser, fun_time=_asking_session(tmp_path))

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made == []
    assert (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split() == [
        "portrait_origenerator_activate"]
    director.fill_the_region(PORTRAIT)
    assert [item[2] for item in made[0].items] == ["g1"]


def test_a_side_let_go_before_it_was_handed_over_forgets_the_slideshow_asked_for_it(
        slideshows, tmp_path):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(browser=browser, fun_time=_asking_session(tmp_path))
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    director.close_the_slideshow(PORTRAIT)
    director.fill_the_region(PORTRAIT)

    assert [item[2] for item in made[0].items] == ["g4"]


def test_a_slideshow_handed_to_a_sessions_funestra_opens_with_what_is_in_flight(slideshows):
    host = FakeHost()
    waiting = _being_made("g-waiting", frame=None)
    host.queue = ([waiting], 3)
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(
        host, browser=browser,
        fun_time=FakeSession(funestras={PORTRAIT: object(), LANDSCAPE: object()}))

    director.fill_the_region(PORTRAIT)

    assert made[0].shown.queue_set == ([waiting], 3)


def test_what_is_in_flight_reaches_a_slideshow_on_a_sessions_funestra(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = slideshows(
        browser=browser, fun_time=FakeSession(funestras={PORTRAIT: object(), LANDSCAPE: object()}))
    director.fill_the_region(PORTRAIT)
    waiting = _being_made("g-waiting", frame=None)

    director.note_queue([waiting], 2)

    assert made[0].shown.queue_set == ([waiting], 2)


def test_a_region_already_holding_a_slideshow_is_left_alone(slideshows):
    browser = FakeBrowser(collections={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = slideshows(browser=browser, fun_time=FakeSession())
    open_both_sides(director)
    standing = director.region_slideshow(PORTRAIT)

    open_both_sides(director)

    assert director.region_slideshow(PORTRAIT) is standing


def test_a_freeze_that_one_slideshow_refuses_still_reaches_the_rest(slideshows):
    # A freeze that stopped at the first slideshow left the others running with no
    # sign of why.
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)
    made[0].pause_raises = True

    director.set_room_paused(True)

    assert made[1].paused is True


def test_a_slideshow_opened_while_the_room_is_frozen_opens_frozen(slideshows):
    # The room's OmniPause holds this surface from its first frame, not from
    # whenever the flag next changes.
    director, _host, made = slideshows(fun_time=FakeSession())
    director.set_room_paused(True)

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].paused is True


def test_a_click_on_a_hosted_slideshow_asks_for_omnipause_on_the_sessions_channel(slideshows, tmp_path):
    session = FakeSession()
    session.dashboard_cmd_file = tmp_path / "dashboard_cmd.txt"
    director, _host, made = slideshows(fun_time=session)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    made[0].actions.omnipause()

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
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
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
    director, _host, made = slideshows(FakeHost(rows=[_row("g1")]))
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
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
    director.set_room_paused(paused)

    director.run_slideshow_command(command, PORTRAIT)

    sent = session.dashboard_cmd_file
    assert (sent.read_text(encoding="utf-8").split() if sent.exists() else []) == asked


def test_a_spoken_word_is_answered_in_the_slideshows_own_corner(slideshows):
    # The window under it is covered by the very thing being talked to.
    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.answer("audio on")

    assert made[0].said == ["audio on"]
    assert host.said == []


def test_an_answer_keeps_its_kind_in_the_slideshows_corner(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.answer("no Latest collection yet", kind=WARNING)

    assert made[0].said_kinds == [WARNING]


def test_a_spoken_word_with_no_slideshow_up_is_answered_on_the_caption(slideshows):
    director, host, _made = slideshows()

    director.answer("audio on")

    assert host.said == ["audio on"]


def test_a_named_side_holding_nothing_is_an_answer_in_itself(slideshows):
    # Falling back to the other region's slideshow would act on the slide the
    # speaker did not name.
    director, _host, _made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)

    assert director.surface_for(PORTRAIT) is None
    assert director.surface_for(LANDSCAPE) is not None


def test_the_spoken_favorites_flips_f_mode_rather_than_opening_a_collection(slideshows):
    # On a Funestra that word is F-mode, and a slideshow is meant to read the same way.

    class Spoken:
        collection_key = FAVORITES_KEY
        side = None

    director, host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.play_collection(Spoken())

    assert made[0].hud_favorites_filter is True
    assert len(made) == 1  # no second slideshow opened
    assert host.said == ["F-mode on"]


def test_a_spoken_collection_with_nothing_in_it_opens_nothing(slideshows):
    class Spoken:
        collection_key = RECENTS_KEY
        side = None

    director, host, made = slideshows(browser=FakeBrowser(collections={}))

    director.play_collection(Spoken())

    assert made == []
    assert host.said == ["nothing there to play"]


def test_the_transport_words_step_the_slide_and_say_which_way(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.FORWARD, said_at=7.5)
    director.run_on_slide(AppCommand.BACK, said_at=7.5)

    assert made[0].steps == [1, -1]
    assert made[0].done == []  # a step is from the slide on screen
    assert made[0].said == ["next", "back"]
    assert made[0].said_kinds == [NOTICE, NOTICE]


def test_a_lock_said_over_a_slide_since_left_puts_that_slide_back_and_locks_it(slideshows):
    director, _host, made = slideshows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.LOCK, said_at=7.5)

    assert made[0].done == [("back to", 7.5), ("lock", True)]


def test_weird_said_over_a_slide_since_left_puts_that_slide_back_and_takes_it_away(slideshows):
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
    # Not the folder the item was generated in: the items you were watching
    # are where you want to be put back, with that one picked among them.
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
    # The Satellite Funestra it covers is topmost itself, and the session's main
    # Funestra owns the room's audio.
    director, _host, made = slideshows(fun_time=FakeSession())

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    window = made[0].shown
    assert window.audio_muted is True
    assert window.geometry == (1920, 0, 960, 540)
    assert window.raised == 1 and window.activated == 1
    assert window.window_flags & Qt.WindowType.FramelessWindowHint
    assert window.window_flags & Qt.WindowType.WindowStaysOnTopHint


def test_a_standalone_slideshow_takes_the_whole_monitor(slideshows):
    director, _host, made = slideshows()

    director.open([("a.png", "image", "g1", None)])

    assert made[0].shown.fullscreen == 1
    assert made[0].shown.window_title is None


def test_a_session_that_hands_over_its_funestras_gets_the_slideshow_on_one(slideshows):
    # The Funestra IS the surface: the slideshow is handed that side's channel, and no
    # window of this app's is placed, shown or raised over the region.
    channel = object()
    director, _host, made = slideshows(fun_time=FakeSession(funestras={PORTRAIT: channel}))

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].opened_with["channel"] is channel
    assert made[0].opened_with["side"] == PORTRAIT
    assert not isinstance(made[0].shown, FakeWindow)
    assert director.region_slideshow(PORTRAIT) is made[0]


def test_a_slideshow_on_a_funestra_says_its_lines_in_the_gallerys_caption(slideshows):
    # A Funestra has no corner to flash a line in, and the gallery's own caption
    # is on screen beside the Funestras in a session.
    director, host, made = slideshows(fun_time=FakeSession(funestras={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].opened_with["say"] == host.say


def test_a_side_the_session_named_no_funestra_for_still_gets_a_window(slideshows):
    # An older session names no Funestras, and its regions want a window of this
    # app's over them exactly as before.
    director, _host, made = slideshows(fun_time=FakeSession(funestras={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)

    assert "channel" not in made[0].opened_with
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

    assert made[0].shown.queue_set == ([waiting], 3)


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
    # A speaker who has just narrowed a slideshow wants to know there is still
    # something in it, and "nothing here is enhanced" is the one answer worth
    # hearing at once.
    slideshow = FakeSlideshow()
    slideshow.enhanced_items = ["a", "b"]
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_enhanced(True)

    assert slideshow.said == ["enhanced only — 2 to play"]


def test_a_slideshow_with_nothing_enhanced_in_it_says_so(slideshows):
    slideshow = FakeSlideshow()
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_enhanced(True)

    assert slideshow.said == ["nothing here is enhanced"]
    assert slideshow.said_kinds == [WARNING]


def test_clearing_the_filter_takes_f_mode_with_it(slideshows):
    # "clear filter" is the way out of ALL of the narrowing, on every satellite
    # in this family.
    slideshow = FakeSlideshow()
    slideshow.hud_favorites_filter = True
    director, _host, _made = slideshows()
    director._slideshow = slideshow

    director.filter_enhanced(False)

    assert slideshow.hud_favorites_filter is False
    assert slideshow.said == ["showing all of them"]


def test_the_filter_with_no_slideshow_up_says_there_is_nothing_to_narrow(slideshows):
    director, host, _made = slideshows()

    director.filter_enhanced(True)

    assert host.said == ["the filter needs a slideshow to narrow"]


def test_every_surface_lets_go_of_a_file_a_delete_is_about_to_move(slideshows):
    # Windows won't move a file while a handle on it is open.
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.release_media(["one.png"])

    assert [slideshow.released for slideshow in made] == [[["one.png"]], [["one.png"]]]


# --- the map around the slide on screen: what the library says ---------------

def _image(prompt_id, prompt, *, seed, steps=50, width=100, height=200):
    """A finished image with real params, shaped by what it asked for —
    which is what places it on a side with no file to measure."""
    params = {"positive_prompt": prompt, "seed": seed, "steps": steps,
              "width": width, "height": height}
    row = _row(prompt_id, params=params)
    row["params_json"] = json.dumps(params)
    return row


def _animation(prompt_id, *, frame, act, tmp_path, width=100, height=200):
    """A finished video animated from the image that wrote *frame*, showing
    *act* — picked for it in Combine, which is where an act is written down.

    A video's settings ask for no size, so what puts this one on a side is the
    shape of the film itself, which is what its thumbnail carries."""
    params = {"positive_prompt": "it moves", "noise_seed": 5, "input_image": frame}
    row = _row(prompt_id, workflow_name="wan22_i2v", params=params,
               files=(f"{prompt_id}.mp4",))
    row["params_json"] = json.dumps(params)
    row["act"] = act
    thumb = tmp_path / f"{prompt_id}_thumb.png"
    Image.new("RGB", (width, height)).save(thumb)
    row["thumbnail_path"] = str(thumb)
    return row


def _library(rows):
    """A director over *rows*, its gallery indexing the images among them the
    way the real one does."""
    host = FakeHost(rows=rows)
    index = gallery.build_image_config_index(
        [row for row in rows if row["workflow_name"] != "wan22_i2v"])
    host.image_config_index = lambda: index
    return host


def test_the_library_of_the_slideshows_side_answers_for_the_map_around_a_generation(slideshows, tmp_path):
    """The same configuration under other seeds is the row and the videos
    animated from the image are the column, each named for its act — read
    off every generation of that side's shape, whatever set the slideshow itself is
    playing."""
    fox = _image("g1", "a red fox", seed=1)
    fox["output_files"] = json.dumps([{"filename": "g1.png"}])
    rows = [fox, _image("g2", "a red fox", seed=2),
            _animation("v1", frame="g1.png", act="alpha", tmp_path=tmp_path),
            _animation("v2", frame="g1.png", act="beta", tmp_path=tmp_path),
            _animation("v3", frame="g1.png", act="beta", tmp_path=tmp_path),
            _image("w1", "a red fox", seed=3, width=200, height=100)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", side="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["g2"]
    assert [row.slide.prompt_id for row in around.column] == ["v1", "v2"]
    assert (around.label, tuple(row.label for row in around.column)) == (
        "Source image", ("alpha", "beta"))
    assert [slide.prompt_id for slide in around.group] == ["v1", "v2", "v3"]


def _fox(prompt_id, *, seed):
    image = _image(prompt_id, "a red fox", seed=seed)
    image["output_files"] = json.dumps([{"filename": f"{prompt_id}.png"}])
    return image


def test_the_column_is_this_seeds_other_configurations_then_the_videos_of_it(slideshows, tmp_path):
    """Both halves, in that order: the same seed under another configuration,
    named by its folder as the tree names it, and then the videos animated from
    this image, named by the act each shows."""
    fox = _fox("g1", seed=1)
    tweaked = _image("g2", "a red fox at dawn", seed=1)
    tweaked["output_files"] = json.dumps([{"filename": "g2.png"}])
    rows = [fox, tweaked, _fox("g3", seed=2),
            _animation("v1", frame="g1.png", act="alpha", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", side="portrait")

    assert [row.slide.prompt_id for row in around.column] == ["g2", "v1"]
    folder, act = (row.label for row in around.column)
    assert act == "alpha"
    assert folder and folder not in ("alpha", "Source image")   # the tree's name for it


def test_a_video_sits_under_its_images_seed_with_the_image_down_its_column(slideshows, tmp_path):
    """A video's own sampler seed says nothing about which image it is of, so
    its row is its act animated from its image's other seeds, and its column
    opens on the image it was animated from."""
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", act="alpha", tmp_path=tmp_path),
            _animation("v2", frame="g2.png", act="alpha", tmp_path=tmp_path),
            _animation("v3", frame="g1.png", act="beta", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", side="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["v2"]
    assert [row.slide.prompt_id for row in around.column] == ["g1", "v3"]
    assert (around.label, tuple(row.label for row in around.column)) == (
        "alpha", ("Source image", "beta"))


def test_a_hidden_starting_frame_stays_off_the_map_of_a_video_made_from_it(slideshows, tmp_path):
    frame = {**_fox("h1", seed=1), "source": GenerationSource.STARTING_FRAME}
    rows = [frame, _animation("v1", frame="h1.png", act="alpha", tmp_path=tmp_path),
            _animation("v2", frame="h1.png", act="beta", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", side="portrait")

    mapped = [*around.seeds, *(row.slide for row in around.column), *around.group]
    assert "h1" not in [slide.prompt_id for slide in mapped]


def test_the_library_says_what_each_generation_an_act_filter_asks_about_is_named_for(slideshows, tmp_path):
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", act="alpha", tmp_path=tmp_path)]
    director, _host, _made = slideshows(_library(rows), db=FakeDB(rows))

    assert director.acts_of(["g1", "v1", "nobody"], side="portrait") == {
        "g1": "Source image", "v1": "alpha"}


def test_an_image_taken_away_leaves_the_map_its_row_draws(slideshows):
    """The map is read off the library every time it is drawn, not off a list
    taken once — so an image condemned from a slideshow stops being drawn beside its
    siblings instead of offering a thumbnail of something that is gone."""
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a red fox", seed=2)]
    host, db = FakeHost(rows=rows), FakeDB(rows)
    director, _host, _made = slideshows(host, db=db)
    assert [slide.prompt_id for slide in director.neighbors_of("g1", side="portrait").seeds] == ["g2"]

    db.rows.pop("g2")                                    # condemned: the row goes
    host.rows = [row for row in host.rows if row["prompt_id"] != "g2"]

    assert director.neighbors_of("g1", side="portrait").seeds == ()


def test_beyond_the_row_lies_the_nearest_of_the_models_other_configurations(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a red fox", seed=2),
            _image("g3", "a red fox at dawn", seed=7),
            _image("g4", "a blue car", seed=8, steps=30)]
    director, _host, _made = slideshows(FakeHost(rows=rows), db=FakeDB(rows))

    beyond = director.beyond_the_row_of("g1", side="portrait")

    assert [slide.prompt_id for slide in beyond] == ["g3", "g4"]
    assert director.beyond_the_row_of("nobody", side="portrait") == ()


def test_a_generation_the_gallery_has_no_row_for_maps_alone(slideshows):
    director, _host, _made = slideshows()

    assert director.neighbors_of("nobody", side="portrait").seeds == ()
    assert director.neighbors_of("", side="landscape").column == ()


def test_a_slideshow_is_wired_to_the_library_of_the_side_it_opened_on(slideshows):
    """What a slideshow asks the gallery on its own behalf now includes what the
    library says about an item — and the star's undoing, for the Funestras'
    "weird" over a favorite."""
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a red fox", seed=2)]
    director, host, made = slideshows(FakeHost(rows=rows), db=FakeDB(rows))

    director.open(director.items_of(rows), location="a-folder", side="portrait")

    actions = made[0].actions
    assert [slide.prompt_id for slide in actions.neighbors("g1").seeds] == ["g2"]
    assert actions.widen("g1") == ()
    assert actions.acts(["g1"]) == {"g1": ""}
    assert [slide.prompt_id for slide in actions.slides(("g2", "nobody", "g1"))] == ["g2", "g1"]
    actions.favorite("g1")
    actions.unfavorite("g1")
    assert host.favorited == []


def test_a_lock_on_a_hosted_slideshow_puts_the_generation_it_holds_in_front_of_him(slideshows):
    rows = [_image("g1", "a red fox", seed=1)]
    director, host, made = slideshows(FakeHost(rows=rows), db=FakeDB(rows),
                                      fun_time=FakeSession())
    director.open(director.items_of(rows), location="a-folder", side="portrait")

    made[0].actions.lock("g1")
    made[0].actions.lock("nobody")

    assert host.shown == ["g1"]
    assert host.followed == []


def _a_sitting():
    """Newest first, as a collection lists: two seeds of one image, another image,
    then two more seeds of the first."""
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
    location = oriented_key(FolderCollection(RECENTS_KEY, "workflow/a").key, PORTRAIT)
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
    browser = FakeBrowser(collections={LATEST_PORTRAIT: sitting})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open(director.items_of(director.rows_at(LATEST_PORTRAIT)),
                  location=LATEST_PORTRAIT, side=PORTRAIT)
    another_seed = _image("g6", "a red fox", seed=6)
    a_new_image = _image("g7", "a green hill", seed=7)

    browser.collections[LATEST_PORTRAIT] = [another_seed, *sitting]
    director.note_finished(another_seed)
    browser.collections[LATEST_PORTRAIT] = [a_new_image, another_seed, *sitting]
    director.note_finished(a_new_image)

    assert [added[0] for added in made[0].added] == ["g6", "g7"]


def test_a_slideshow_of_favorites_plays_the_sides_whole_library_with_the_filter_on(slideshows):
    """Favorites is the Shuffle playlist with the favorites switch held down,
    so the switch can be let go to widen and the order pair still means the
    library rather than the bookmarks."""
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    browser = FakeBrowser(collections={oriented_key(FAVORITES_KEY, PORTRAIT): [rows[0]],
                                       ALL_PORTRAIT: rows})
    director, _host, made = slideshows(FakeHost(location=oriented_key(FAVORITES_KEY, PORTRAIT),
                                                rows=rows),
                                       browser=browser)

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].hud_favorites_filter is True
    assert director._live_slideshows == [(made[0], ALL_PORTRAIT)]


def _folder_of(rows):
    return gallery.SettingsGroup("workflow/a", "A", list(rows))


def test_a_slideshow_of_a_folders_favorites_plays_that_folder_with_the_filter_on(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    folder = oriented_key("workflow/a", PORTRAIT)
    favorites = oriented_key(FolderCollection(FAVORITES_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = slideshows(FakeHost(location=favorites, rows=[rows[0]],
                                                groups={folder: _folder_of(rows)}))

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].hud_favorites_filter is True
    assert director._live_slideshows == [(made[0], folder)]


def test_a_slideshow_of_a_folders_enhanced_plays_that_folder_with_enhanced_only_on(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    folder = oriented_key("workflow/a", PORTRAIT)
    enhanced = oriented_key(FolderCollection(ENHANCED_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = slideshows(FakeHost(location=enhanced, rows=[rows[0]],
                                                groups={folder: _folder_of(rows)}))

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].taken_up == (SlideshowFilters(enhanced=True), False)
    assert director._live_slideshows == [(made[0], folder)]


def test_a_slideshow_of_latest_opens_on_the_newest_rather_than_where_the_last_one_stopped(slideshows):
    """Latest is newest-first and the newest is the whole point of opening it,
    so it does not pick up where a Latest slideshow left off."""
    rows = _a_sitting()
    director, _host, made = slideshows(FakeHost(location=LATEST_PORTRAIT, rows=rows))
    director._slideshow_state = SlideshowState(order=["g1"], current="g1")

    director.start()

    assert made[0].resumed is None


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
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
    made[-1].pace.step(3)

    director.become_standalone(motion=None)
    director.become_hosted(FakeSession())
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    assert made[-1].pace.seconds == 6


def test_the_next_launch_opens_its_slideshows_at_the_pace_the_last_one_was_left_at(slideshows):
    director, _host, _made = slideshows()
    director._pace.set_seconds(9)

    relaunched, _host, _made = slideshows()
    relaunched.remember(json.loads(json.dumps(director.remembered())))

    assert relaunched._pace.seconds == 9


def test_the_next_launch_wears_the_panel_where_the_last_one_left_it(slideshows):
    director, _host, _made = slideshows()
    director.move_the_hud("right", side=LANDSCAPE)
    director.collapse_the_hud(True, side=LANDSCAPE)

    relaunched, _host, _made = slideshows()
    relaunched.remember(json.loads(json.dumps(director.remembered())))

    assert relaunched.hud_place(LANDSCAPE) == (HudCorner.UPPER_RIGHT, True)
    assert relaunched.hud_place(PORTRAIT) == (HudCorner.UPPER_LEFT, False)


def test_a_panel_opened_in_a_corner_is_there_and_open_on_the_next_launch(slideshows):
    director, _host, _made = slideshows()
    director.collapse_the_hud(True, side=LANDSCAPE)

    director.open_the_hud_in(HudCorner.LOWER_RIGHT, side=LANDSCAPE)

    relaunched, _host, _made = slideshows()
    relaunched.remember(json.loads(json.dumps(director.remembered())))
    assert relaunched.hud_place(LANDSCAPE) == (HudCorner.LOWER_RIGHT, False)


def test_the_favorites_collection_holds_f_mode_down_without_turning_it_on_for_the_next(slideshows):
    rows = [_image("g1", "a red fox", seed=1), _image("g2", "a blue car", seed=2)]
    folder = oriented_key("workflow/a", PORTRAIT)
    favorites = oriented_key(FolderCollection(FAVORITES_KEY, "workflow/a").key, PORTRAIT)
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

    director.open_on_preview(("a2.png", "image"), "a2")

    assert made[0].taken_up == (SlideshowFilters(enhanced=True), True)


def test_a_slideshow_of_a_folder_still_picks_up_where_the_last_one_stopped(slideshows):
    director, _host, made = slideshows(FakeHost(location="workflow/a",
                                                rows=[_image("g1", "a red fox", seed=1)]))
    director._slideshow_state = SlideshowState(order=["g1"], current="g1")

    director.start()

    assert made[0].resumed is director._slideshow_state



# --- what is being made while a slideshow is up ---------------------------------

def _being_made(key, frame=b"frame"):
    return SimpleNamespace(key=key, reading=SimpleNamespace(frame=frame))


def test_how_the_enhancements_are_going_reaches_every_slideshow_that_is_up(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.note_enhancing({"g1": "running"})

    assert [slideshow.enhancing for slideshow in made] == [{"g1": "running"}] * 2


def test_what_each_slideshow_still_up_is_locked_on_is_known(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)
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
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)
    director.versions_of = lambda rows: {"better.png": ["newer", "older"]}

    director.note_enhanced(_row("g1", files=("better.png",)))

    assert [slideshow.levels_added for slideshow in made] == [[{"better.png": ["newer", "older"]}]] * 2


def test_the_frames_of_the_enhancements_being_made_reach_every_slideshow_that_is_up(slideshows):
    director, _host, made = slideshows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.note_enhancing({"g1": "running"}, frames={"g1": b"frame"})

    assert [slideshow.enhancing_frames for slideshow in made] == [{"g1": b"frame"}] * 2


def test_a_run_reaches_each_slideshow_whose_own_set_holds_it(slideshows):
    browser = FakeBrowser(collections={"collection/a": [_row("g1"), _row("g-run")],
                                       "collection/b": [_row("g2")]})
    director, _host, made = slideshows(browser=browser, db=FakeDB([_row("g-run")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="collection/b", side=PORTRAIT)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == [("g-run", b"frame")]
    assert made[1].generating == []


def test_every_slideshow_that_is_up_hears_which_runs_are_still_being_made(slideshows):
    browser = FakeBrowser(collections={"collection/a": [_row("g1")], "collection/b": [_row("g2")]})
    director, _host, made = slideshows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="collection/a", side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="collection/b", side=PORTRAIT)

    director.note_in_flight([_being_made("g-run", frame=None)])

    assert [slideshow.in_flight for slideshow in made] == [{"g-run"}, {"g-run"}]


def test_a_latest_slideshow_takes_a_new_run_after_the_browser_has_moved_on(slideshows):
    browser = FakeBrowser(collections={LATEST_LANDSCAPE: [_row("g1")]}, recents=False)
    director, _host, made = slideshows(browser=browser, db=FakeDB([_row("g-run")]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_LANDSCAPE,
                  side=LANDSCAPE)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == [("g-run", b"frame")]


def test_a_slideshow_of_one_kinds_latest_takes_a_new_run_of_that_kind_alone(slideshows):
    videos_latest = oriented_key(FolderCollection(RECENTS_KEY, "video").key, LANDSCAPE)
    clip_run = _row("v-run", workflow_name="wan22_i2v", files=("v-run.mp4",))
    browser = FakeBrowser(collections={videos_latest: [_row("v1", files=("v1.mp4",))]})
    director, _host, made = slideshows(browser=browser, db=FakeDB([clip_run, _row("i-run")]),
                                       fun_time=FakeSession())
    director.open([("v1.mp4", "video", "v1", None)], location=videos_latest, side=LANDSCAPE)

    director.note_generating("i-run", b"frame")
    director.note_generating("v-run", b"frame")

    assert made[0].generating == [("v-run", b"frame")]


def test_a_latest_slideshow_turns_down_a_run_asked_for_in_the_other_shape(slideshows):
    run = _row("g-run")
    run["params_json"] = json.dumps({"width": 1024, "height": 768})
    browser = FakeBrowser(collections={LATEST_PORTRAIT: [_row("g1")]})
    director, _host, made = slideshows(browser=browser, db=FakeDB([run]),
                                       fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_PORTRAIT,
                  side=PORTRAIT)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == []


def test_a_run_double_clicked_while_hosted_opens_its_folder_on_a_funestra_following_it(slideshows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    director, host, made = slideshows(host, db=FakeDB([_row("g-run")]), fun_time=FakeSession(
        funestras={PORTRAIT: object(), LANDSCAPE: object()}))
    host.queue = ([_being_made("g-run")], 0)

    director.open([], folder_items=[("a.png", "image", "g1", None)], start=0,
                  frame=b"frame")

    assert made[0].items == [("a.png", "image", "g1", None)]
    assert made[0].generating == [("g-run", b"frame")]
    assert (made[0].follows, made[0].leads) == (1, 0)
