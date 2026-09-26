"""The fullscreen shows, driven with no gallery and no Qt around them.

Every behaviour here used to need a 7,000-line widget and a real window on a
monitor to reach: what a show is offered when a generation lands, which runs it
turns down, what happens to a satellite region when the show covering it ends,
and what the spoken words about a show do. The show itself is a recorder, the
host a handful of recorded calls.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt

from origenerator import gallery
from origenerator.gallery.shelves import FAVORITES_KEY, RECENTS_KEY, FolderShelf
from origenerator.gui import show_director as module
from origenerator.gui.notice_overlay import FAVORITE, NOTICE, WARNING
from origenerator.gui.show_director import ShowDirector
from origenerator.orientation import oriented_key
from origenerator.slideshow import ShowState
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.show_commands import ShowCommand

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
# What a region plays with nothing else asked for: the whole library,
# narrowed to that region's shape.
ALL_PORTRAIT = oriented_key(gallery.ALL_KEY, PORTRAIT)
ALL_LANDSCAPE = oriented_key(gallery.ALL_KEY, LANDSCAPE)
LATEST_PORTRAIT = oriented_key(RECENTS_KEY, PORTRAIT)
LATEST_LANDSCAPE = oriented_key(RECENTS_KEY, LANDSCAPE)


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeQueuePlate:
    def __init__(self):
        self.reorder_requested = FakeSignal()
        self.clear_queue_requested = FakeSignal()


class FakeShow:
    """A slideshow reduced to what the director asks of one."""

    def __init__(self, items=(), *, actions=None, pace=None, motion=None,
                 hud=None, **kwargs):
        self.items = list(items)
        self.actions = actions
        self.motion = motion
        self.hud = hud
        self.opened_with = kwargs
        self.open_requested = FakeSignal()
        self.closed = FakeSignal()
        self.media_changed = FakeSignal()
        self._queue = FakeQueuePlate()
        self.added = []
        self.generating = []
        self.enhanced = []
        self.enhancing = None
        self.in_flight = None
        self.queue_set = None
        self.said = []
        self.said_kinds = []
        self.runs_said = []
        self.levels = None
        self.playlist = None
        self.resumed = None
        self.retuned = None
        self.reordered = None
        self.dwell_s = None
        self.paused = None
        self.audio_muted = None
        self.window_title = None
        self.window_flags = Qt.WindowType.Widget
        self.geometry = None
        self.raised = 0
        self.activated = 0
        self.shown = 0
        self.fullscreen = 0
        self.closes = 0
        self.visible = True
        self.live = False
        self.ids = set()
        self.hud_favorites_filter = False
        self.hud_enhanced_mode = False
        self.enhanced_items = []
        self.steps = []
        self.culled = 0
        self.favoritable = True
        self.favorites = 0
        self.hud_panel = None
        self.released = []
        self.pause_raises = False
        self.state_at_close = "where-it-got-to"
        self.played = []
        self.leads = 0
        self.levels_added = []

    # what a show is, and what it holds
    def queue(self):
        return self._queue

    def is_live(self):
        return self.live

    def holds(self, prompt_id):
        return prompt_id in self.ids

    def state(self):
        return self.state_at_close

    def is_showing(self):
        return self.visible

    # what the director tells it
    def play(self, items, *, hud=None, **kwargs):
        self.items = list(items)
        self.hud = hud
        self.played.append(list(items))

    def set_playlist(self, items, index):
        self.playlist = (list(items), index)

    def set_levels(self, levels):
        self.levels = levels

    def resume(self, state):
        self.resumed = state

    def retune(self, items, *, enhanced_ids):
        self.retuned = (list(items), set(enhanced_ids))

    def reorder(self, items, *, latest, enhanced_ids):
        self.reordered = (list(items), latest, set(enhanced_ids))

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

    def add_levels(self, levels):
        self.levels_added.append(levels)

    def note_voice_command(self, message, *, kind=NOTICE):
        self.said.append(message)
        self.said_kinds.append(kind)

    def note_voice_run(self, prompt_id, message, *, kind=NOTICE):
        self.runs_said.append((prompt_id, message))

    def set_queue(self, items, foreign_total):
        self.queue_set = (list(items), foreign_total)

    def set_dwell_s(self, seconds):
        self.dwell_s = seconds

    def set_paused(self, paused):
        if self.pause_raises:
            raise RuntimeError("this show will not freeze")
        self.paused = paused

    def set_audio_muted(self, muted):
        self.audio_muted = muted

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

    def step(self, delta):
        self.steps.append(delta)

    def cull(self):
        self.culled += 1

    def favorite(self):
        self.favorites += 1
        return self.favoritable

    def set_locked(self, locked):
        return locked

    def adopt_hud(self, panel):
        self.hud_panel = panel

    # the window it is
    def showFullScreen(self):
        self.fullscreen += 1

    def show(self):
        self.shown += 1

    def close(self):
        self.closes += 1
        self.visible = False
        self.closed.emit(self)

    def setWindowTitle(self, title):
        self.window_title = title

    def windowFlags(self):
        return self.window_flags

    def setWindowFlags(self, flags):
        self.window_flags = flags

    def setGeometry(self, x, y, width, height):
        self.geometry = (x, y, width, height)

    def winId(self):
        return 4242

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        self.activated += 1


class FakeRect:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


class FakeSession:
    """A hosting Fun Time session reduced to the three things a show asks of one.

    *players* is which sides it hands over as players, by the channel it names
    for each; a side it names none for is one a window of this app's covers.
    """

    dashboard_cmd_file = None

    def __init__(self, players=None):
        self.players = players or {}

    def region_rect(self, side):
        return FakeRect(0 if side == LANDSCAPE else 1920, 0, 960, 540)

    def player(self, side):
        return self.players.get(side)


class FakeReroll:
    def __init__(self):
        self.holds = []

    def hold_videos(self, held):
        self.holds.append(held)

    def reorder(self, *args):
        pass


class FakePace:
    def __init__(self):
        self.seconds = None

    def set_seconds(self, seconds):
        self.seconds = seconds


class FakeBrowser:
    """The middle pane reduced to the four questions a show asks of it."""

    def __init__(self, shelves=None, recents=False, searching=False):
        self.shelves = shelves or {}
        self.recents = recents
        self.searching = searching

    def rows_for_shelf(self, key):
        return self.shelves.get(key)

    def showing_recents(self):
        return self.recents

    def showing_search(self):
        return self.searching


class FakeDB:
    def __init__(self, rows=()):
        self.rows = {row["prompt_id"]: row for row in rows}

    def list_generations(self):
        return list(self.rows.values())

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)

    def folder_meta_map(self):
        return {}


class FakeHost:
    """A gallery reduced to what the shows ask of one."""

    def __init__(self, *, location=None, rows=(), groups=None):
        self.location = location
        self.rows = list(rows)
        self.groups = groups or {}
        self.said = []
        self.followed = []
        self.trashed = []
        self.favorited = []
        self.enhanced = []
        self.drive_toggles = 0
        self.reconciles = 0
        self.cleared_queue = 0
        self.queue = ([], 0)
        self.visible = [row["prompt_id"] for row in self.rows]
        self.types = {"image", "video"}

    def show_location(self):
        return self.location

    def rows_to_play(self):
        return self.rows

    def slideshow_subject(self):
        return "this folder"

    def side_in_view(self):
        return LANDSCAPE

    def group_for_key(self, key):
        return self.groups.get(key)

    def media_types(self):
        return self.types

    def row_for(self, prompt_id):
        return next((r for r in self.rows if r["prompt_id"] == prompt_id), None)

    def image_config_index(self):
        return {}

    def visible_prompt_ids(self):
        return list(self.visible)

    def queue_now(self):
        return self.queue

    def clear_foreign_queue(self):
        self.cleared_queue += 1

    def follow_link(self, prompt_id):
        self.followed.append(prompt_id)

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

    # The app's one OSR2 switch, handed to a show whole: a host with no device
    # (which is every host here) has none to hand over.
    osr2_control = None

    def toggle_osr2_drive(self):
        self.drive_toggles += 1

    def reconcile_osr2(self):
        self.reconciles += 1

    def say(self, message):
        self.said.append(message)


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
def shows(monkeypatch):
    """A director whose shows are recorders and whose HUD panel is absent."""
    made = []

    def build_show(items, **kwargs):
        show = FakeShow(items, **kwargs)
        made.append(show)
        return show

    monkeypatch.setattr(module, "SlideshowView", build_show)
    monkeypatch.setattr(module, "PlayerShow", build_show)
    monkeypatch.setattr(module.ShowDirector, "_wear_the_hud", lambda self, view, side: None)
    monkeypatch.setattr(module, "place_window_in_device_pixels",
                        lambda *args: None)

    def build(host=None, *, db=None, browser=None, fun_time=None):
        host = host or FakeHost()
        director = ShowDirector(
            host, db=db or FakeDB(), browser=browser or FakeBrowser(),
            jobs=FakeReroll(), pace=FakePace(), motion=None,
            fun_time=fun_time)
        # The playlist is what a show is of; deriving it from files on disk is
        # resolve_preview's own tested job, not this one's.
        director.items_of = lambda rows: [
            (f"{r['prompt_id']}.png", "image", r["prompt_id"], None) for r in rows]
        return director, host, made
    return build


def test_a_show_is_remembered_with_the_place_it_opened_from(shows):
    director, _host, made = shows()

    director.open([("a.png", "image", "g1", None)], location="workflow/a")

    assert director.showing is made[0]
    assert director._live_shows == [(made[0], "workflow/a")]


def test_opening_a_show_holds_the_videos_back(shows):
    # A video generation would saturate the card the show is drawn with, and a
    # show is exactly the stretch when nobody is waiting on a video.
    director, _host, _made = shows()

    director.open([("a.png", "image", "g1", None)])

    assert director._jobs.holds == [True]


def test_the_last_show_closing_lets_the_videos_go(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    made[0].close()

    assert director.showing is None
    assert director._jobs.holds == [True, False]


def test_asking_for_a_second_show_standalone_replays_the_one_already_up(shows):
    # Standalone there is one screen, so there is one show. A second set asked
    # for while one is up -- by voice, or from the window Alt+Tab reaches --
    # re-points the show that is there rather than stacking another over it.
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)], location="shelf/a")

    again = director.open([("b.png", "image", "g2", None)], location="shelf/b")

    assert made == [again]
    assert again.played == [[("b.png", "image", "g2", None)]]
    assert director._live_shows == [(again, "shelf/b")]


def test_a_double_click_on_a_picture_no_folder_lists_still_names_its_generation(shows):
    host = FakeHost(rows=[_row("a1"), _row("t1")])
    host.visible = ["a1"]
    director, _host, made = shows(host)
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}

    director.open_on_preview(("t1.png", "image"), None, "t1")

    (show,) = made
    assert show.items == [("t1.png", "image", "t1", None)]
    assert show.levels == {"t1.png": ["newer", "older"]}


def test_one_of_two_shows_closing_keeps_the_hold_and_the_other(shows):
    # Hosted, two run at once: closing the portrait one must not forget the
    # landscape one, and the videos stay held while it is still playing them.
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    made[1].close()

    assert director.showing is made[0]
    assert director._jobs.holds == [True, True]


def test_a_director_taken_into_a_session_closes_its_fullscreen_show_for_the_regions(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.become_hosted(FakeSession())
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    assert made[0].closes == 1
    assert director.region_show(PORTRAIT) is made[1]
    assert made[1].fullscreen == 0


def test_a_region_opens_armed_with_the_versions_of_the_library_it_plays(shows):
    """A show on a player opens on its side's whole library, which the browser
    is not listing — so versions read off the browser's rows named none of the
    pictures on screen, and every versions button on the band was drawn faded
    however many enhancements that library held (2026-09-19)."""
    browser = FakeBrowser(shelves={ALL_PORTRAIT: [_row("g4")],
                                   ALL_LANDSCAPE: [_row("g5")]})
    director, host, made = shows(browser=browser, fun_time=FakeSession())
    assert host.visible == []  # the browser is somewhere else entirely
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}

    director.fill_the_regions()

    assert director.region_show(PORTRAIT).levels == {"g4.png": ["newer", "older"]}
    assert director.region_show(LANDSCAPE).levels == {"g5.png": ["newer", "older"]}


def test_a_region_says_how_long_it_took_to_fill(shows, caplog):
    """The wait the owner is judging when he presses the button that brings
    this mode up -- the one between the press and the pictures -- named in the
    line that says the region opened, so a slow one can be read off the log
    instead of counted off a stopwatch."""
    browser = FakeBrowser(shelves={ALL_PORTRAIT: [_row("g4")],
                                   ALL_LANDSCAPE: [_row("g5")]})
    director, _host, _made = shows(browser=browser, fun_time=FakeSession())

    with caplog.at_level("INFO", logger="origenerator.gui.show_director"):
        director.fill_the_regions()

    opened = [record.message for record in caplog.records if "region opens" in record.message]
    assert len(opened) == 2
    assert all(re.search(r", filled in \d+ ms$", message) for message in opened), opened


def test_a_director_handed_back_from_a_session_gives_up_its_regions_for_a_fullscreen_show(shows):
    director, _host, made = shows(fun_time=FakeSession())
    director.fill_the_regions()
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)
    motion = object()

    director.become_standalone(motion)
    director.open([("b.png", "image", "g2", None)])

    assert made[0].closes == 1
    assert director.region_show(PORTRAIT) is None
    assert director.showing is made[-1]
    assert made[-1].fullscreen == 1 and made[-1].motion is motion


def test_a_landing_reaches_the_show_whose_own_folder_holds_it(shows):
    # Asked of each show's OWN location rather than of the browser, which has
    # usually moved on by the time a generation lands.
    # On the two regions, which is the only place two shows are up at once:
    # standalone the monitor's one show takes over the new set instead.
    browser = FakeBrowser(shelves={"shelf/a": [_row("g9")], "shelf/b": []})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="shelf/a",
                  side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="shelf/b",
                  side=PORTRAIT)

    director.note_finished(_row("g9", favorite=True))

    assert made[0].added == [("g9", True, False)]
    assert made[1].added == []


def test_a_run_in_another_folder_is_turned_down(shows):
    host = FakeHost(rows=[_row("g1")])
    director, _host, made = shows(host, db=FakeDB([_row("g7")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g7", b"frame-one")
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == []


def test_a_run_the_folder_lists_only_after_its_first_frame_joins_on_its_next(shows):
    host = FakeHost(rows=[_row("g1")])
    director, _host, made = shows(host, db=FakeDB([_row("g1"), _row("g7")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g7", b"frame-one")
    host.rows.append(_row("g7"))
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == [("g7", b"frame-two")]


def test_an_enhancement_is_never_a_slide_of_its_own_frames(shows):
    # It is a better version of a picture the show may already be playing, and a
    # half-rendered second slide would be the same image twice, one of them worse.
    enhance = _row("g8", workflow_name="enhance_image")
    host = FakeHost(rows=[_row("g1"), enhance])
    director, _host, made = shows(host, db=FakeDB([enhance]),
                                  browser=FakeBrowser(recents=True))
    enhance["workflow_name"] = gallery.ENHANCE_WORKFLOW
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g8", b"frame")

    assert made[0].generating == []


def test_a_run_of_the_folder_on_screen_joins_on_its_first_frame(shows):
    # Waiting for the file is waiting minutes for the one thing the show is
    # being watched for.
    host = FakeHost(rows=[_row("g1"), _row("g5")])
    director, _host, made = shows(host, db=FakeDB([_row("g5")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g5", b"frame")

    assert made[0].generating == [("g5", b"frame")]


def test_a_show_following_one_run_full_screen_takes_no_other(shows):
    host = FakeHost(rows=[_row("g5")])
    director, _host, made = shows(host, db=FakeDB([_row("g5")]))
    director.open([])
    made[0].live = True

    director.note_generating("g5", b"frame")

    assert made[0].generating == []


def test_a_landed_enhancement_reaches_every_surface(shows, tmp_path, monkeypatch):
    # An enhancement asked for from a show lands minutes later, by which time it
    # has long paged on: an upgrade it doesn't take here it never takes at all.
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output)
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.note_enhanced(_row("g1", files=("better.png",)))

    assert [show.enhanced for show in made] == [
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
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output)
    monkeypatch.setattr(module, "EVOLVER_UPSCALED_DIR", library)
    return _row("g1", files=("clip.mp4",)), video, upscale


def _director():
    return ShowDirector(FakeHost(), db=FakeDB(), browser=FakeBrowser(),
                        jobs=FakeReroll(), pace=FakePace(), motion=None,
                        fun_time=None)


def test_a_video_evolver_upscaled_plays_as_the_upscale(tmp_path, monkeypatch):
    row, _video, upscale = _evolver_upscaled_video(tmp_path, monkeypatch)

    assert _director().items_of([row]) == [(upscale, "video", "g1", None)]


def test_shift_arrows_step_from_an_upscale_to_the_video_it_was_made_from(tmp_path,
                                                                        monkeypatch):
    row, video, upscale = _evolver_upscaled_video(tmp_path, monkeypatch)

    assert _director().versions_of([row]) == {
        str(upscale): [(upscale, "video", "Evolved"), (video, "video", "Original")]}


def test_a_region_reset_re_points_what_feeds_it(shows):
    # A generation landing in the library must reach a region that has been
    # reset back to the library, not the folder it used to be playing.
    browser = FakeBrowser(shelves={ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reset_region(made[0])

    assert director._live_shows == [(made[0], ALL_LANDSCAPE)]
    assert made[0].retuned == ([("g4.png", "image", "g4", None)], set())


def test_a_set_handed_to_a_running_show_brings_its_own_versions_with_it(shows):
    """Latest, Shuffle and a region reset each hand the show a different set of
    its side's library.  A versions map still armed on the set the show opened
    with names none of the pictures now on screen, so the band's versions button
    goes faded over a whole library of enhancements (2026-09-19)."""
    browser = FakeBrowser(shelves={LATEST_LANDSCAPE: [_row("g9")],
                                   ALL_LANDSCAPE: [_row("g4")]})
    director, _host, made = shows(browser=browser,
                                  db=FakeDB([_row("g9"), _row("g4")]),
                                  fun_time=FakeSession())
    director.versions_of = lambda rows: {f"{row['prompt_id']}.png": ["newer", "older"]
                                         for row in rows}
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reorder_show(made[0], True)
    assert made[0].levels == {"g9.png": ["newer", "older"]}

    director.reset_region(made[0])
    assert made[0].levels == {"g4.png": ["newer", "older"]}


def test_latest_points_a_region_show_at_its_sides_latest_and_feeds_it_from_there(shows):
    two_pictures = [_picture("g9", "a red fox", seed=9), _picture("g4", "a blue car", seed=4)]
    browser = FakeBrowser(shelves={LATEST_LANDSCAPE: two_pictures})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reorder_show(made[0], True)

    assert made[0].reordered == (
        [("g9.png", "image", "g9", None), ("g4.png", "image", "g4", None)], True, set())
    assert director._live_shows == [(made[0], LATEST_LANDSCAPE)]
    assert made[0].said == ["Latest"]


def test_shuffle_points_a_region_show_back_at_its_sides_whole_library(shows):
    browser = FakeBrowser(shelves={ALL_PORTRAIT: [_row("g4")],
                                   LATEST_PORTRAIT: [_row("g9")]})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_PORTRAIT,
                  side=PORTRAIT)

    director.reorder_show(made[0], False)

    assert made[0].reordered == ([("g4.png", "image", "g4", None)], False, set())
    assert director._live_shows == [(made[0], ALL_PORTRAIT)]
    assert made[0].said == ["Shuffle"]


def test_a_show_on_its_own_takes_latest_of_the_shape_it_opened_on(shows):
    browser = FakeBrowser(shelves={LATEST_PORTRAIT: [_row("g9")]})
    director, _host, made = shows(browser=browser)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    director.reorder_show(made[0], True)

    assert made[0].reordered == ([("g9.png", "image", "g9", None)], True, set())


def test_an_order_with_nothing_to_play_says_so_and_leaves_the_show_alone(shows):
    director, _host, made = shows(browser=FakeBrowser(shelves={}), fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="workflow/a",
                  side=LANDSCAPE)

    director.reorder_show(made[0], True)

    assert made[0].reordered is None
    assert list(zip(made[0].said, made[0].said_kinds)) == [
        ("Nothing there to play", WARNING)]
    assert director._live_shows == [(made[0], "workflow/a")]


@pytest.mark.parametrize("session", [None, FakeSession()])
def test_a_show_asks_this_director_for_its_order_hosted_or_not(shows, session):
    director, _host, made = shows(fun_time=session)

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].actions.reorder == director.reorder_show


def test_a_region_show_ending_comes_back_on_the_base_state(shows):
    # In origenerator mode the player underneath is blacked for the whole mode,
    # so a region left empty is a black rectangle rather than a fallback.
    browser = FakeBrowser(shelves={ALL_PORTRAIT: [_row("g4")]})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.fill_the_regions()
    first = director.region_show(PORTRAIT)

    first.close()

    assert director.region_show(PORTRAIT) is not first
    assert director.region_show(PORTRAIT) is not None


def test_closing_the_shows_drops_the_wanting_before_it_closes_anything(shows):
    # A show closing while the mode still wants its regions is refilled with the
    # base state, and these closes must not be.
    browser = FakeBrowser(shelves={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = shows(browser=browser, fun_time=FakeSession())
    director.fill_the_regions()

    director.close_the_shows()

    assert director.regions_wanted is False
    assert director.region_show(PORTRAIT) is None


def test_a_region_already_holding_a_show_is_left_alone(shows):
    browser = FakeBrowser(shelves={ALL_PORTRAIT: [_row("g4")]})
    director, _host, _made = shows(browser=browser, fun_time=FakeSession())
    director.fill_the_regions()
    standing = director.region_show(PORTRAIT)

    director.fill_the_regions()

    assert director.region_show(PORTRAIT) is standing


def test_a_freeze_that_one_show_refuses_still_reaches_the_rest(shows):
    # A freeze that stopped at the first show left the others running with no
    # sign of why.
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)
    made[0].pause_raises = True

    director.set_session_paused(True)

    assert made[1].paused is True


def test_a_show_opened_while_the_room_is_frozen_opens_frozen(shows):
    # The room's OmniPause holds this surface from its first frame, not from
    # whenever the flag next changes.
    director, _host, made = shows(fun_time=FakeSession())
    director.set_session_paused(True)

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].paused is True


def test_a_click_on_a_hosted_show_asks_for_omnipause_on_the_sessions_channel(shows, tmp_path):
    session = FakeSession()
    session.dashboard_cmd_file = tmp_path / "dashboard_cmd.txt"
    director, _host, made = shows(fun_time=session)
    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    made[0].actions.omnipause()

    assert session.dashboard_cmd_file.read_text(encoding="utf-8").split() == [
        "omnipause_toggle"]


def test_a_show_with_no_session_to_ask_is_left_to_pause_itself(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    assert made[0].actions.omnipause is None


def test_the_spoken_close_with_no_show_up_says_so(shows):
    director, host, made = shows()

    director.run_show_command(ShowCommand.STOP, None)

    assert host.said == ["🎤 no slideshow to close"]
    assert made == []


def test_the_spoken_pause_with_no_show_sets_what_the_next_one_opens_at(shows):
    # A show that never moves on is exactly what a stopped picture is here.
    director, host, _made = shows()

    director.run_show_command(ShowCommand.PAUSE, None)

    assert director._pace.seconds == 0
    assert host.said == ["🎤 no slideshow to pause"]


def test_a_spoken_word_is_answered_in_the_shows_own_corner(shows):
    # The window under it is covered by the very thing being talked to.
    director, host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.answer("🎤 audio on")

    assert made[0].said == ["🎤 audio on"]
    assert host.said == []


def test_an_answer_keeps_its_kind_in_the_shows_corner(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.answer("🎤 no Latest shelf yet", kind=WARNING)

    assert made[0].said_kinds == [WARNING]


def test_a_spoken_word_with_no_show_up_is_answered_on_the_caption(shows):
    director, host, _made = shows()

    director.answer("🎤 audio on")

    assert host.said == ["🎤 audio on"]


def test_a_named_side_holding_nothing_is_an_answer_in_itself(shows):
    # Falling back to the other region's show would act on the picture the
    # speaker did not name.
    director, _host, _made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)

    assert director.surface_for(PORTRAIT) is None
    assert director.surface_for(LANDSCAPE) is not None


def test_the_spoken_favorites_flips_f_mode_rather_than_opening_a_shelf(shows):
    # On a player that word is F-mode, and a show is meant to read the same way.

    class Spoken:
        shelf_key = FAVORITES_KEY
        side = None

    director, host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.play_shelf(Spoken())

    assert made[0].hud_favorites_filter is True
    assert len(made) == 1  # no second show opened
    assert host.said == ["🎤 F-mode on"]


def test_a_spoken_shelf_with_nothing_in_it_opens_nothing(shows):
    class Spoken:
        shelf_key = RECENTS_KEY
        side = None

    director, host, made = shows(browser=FakeBrowser(shelves={}))

    director.play_shelf(Spoken())

    assert made == []
    assert host.said == ["🎤 nothing there to play"]


def test_the_transport_words_step_the_slide_and_say_which_way(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.FORWARD)
    director.run_on_slide(AppCommand.BACK)

    assert made[0].steps == [1, -1]
    assert made[0].said == ["🎤 next", "🎤 back"]
    assert made[0].said_kinds == [NOTICE, NOTICE]


def test_a_favorite_over_a_slide_with_nothing_to_favorite_says_so(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])
    made[0].favoritable = False

    director.run_on_slide(AppCommand.FAVORITE)

    assert made[0].said == ["🎤 nothing here to favorite"]
    assert made[0].said_kinds == [WARNING]


def test_a_favorite_that_lands_says_so_in_the_favorites_green(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.run_on_slide(AppCommand.FAVORITE)

    assert made[0].said == ["🎤 favorited"]
    assert made[0].said_kinds == [FAVORITE]


def test_leaving_a_show_for_an_item_lands_on_the_item(shows):
    # Leaving a show *for* an item is a decision to work on it, and the folder
    # alone under a stale form is not that.
    director, host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    made[0].open_requested.emit("g1")

    assert host.followed == ["g1"]
    assert director.showing is None


def test_a_region_show_is_placed_muted_frameless_and_on_top(shows):
    # The satellite player it covers is topmost itself, and the session's main
    # player owns the room's audio.
    director, _host, made = shows(fun_time=FakeSession())

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].audio_muted is True
    assert made[0].geometry == (1920, 0, 960, 540)
    assert made[0].raised == 1 and made[0].activated == 1
    assert made[0].window_flags & Qt.WindowType.FramelessWindowHint
    assert made[0].window_flags & Qt.WindowType.WindowStaysOnTopHint


def test_a_standalone_show_takes_the_whole_monitor(shows):
    director, _host, made = shows()

    director.open([("a.png", "image", "g1", None)])

    assert made[0].fullscreen == 1
    assert made[0].window_title is None


def test_a_session_that_hands_over_its_players_gets_the_show_on_one(shows):
    # The player IS the surface: the show is handed that side's channel, and no
    # window of this app's is placed, shown or raised over the region.
    channel = object()
    director, _host, made = shows(fun_time=FakeSession(players={PORTRAIT: channel}))

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].opened_with["channel"] is channel
    assert made[0].opened_with["side"] == PORTRAIT
    assert (made[0].shown, made[0].raised, made[0].geometry) == (0, 0, None)
    assert director.region_show(PORTRAIT) is made[0]


def test_a_show_on_a_player_says_its_lines_in_the_gallerys_caption(shows):
    # A player has no corner to flash a line in, and the gallery's own caption
    # is on screen beside the players in a session.
    director, host, made = shows(fun_time=FakeSession(players={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].opened_with["say"] == host.say


def test_a_show_on_a_player_takes_runs_from_what_is_in_flight_not_a_double_clicks_frame(
        shows):
    director, _host, made = shows(fun_time=FakeSession(players={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT, frame=b"frame")

    assert "frame" not in made[0].opened_with


def test_a_side_the_session_named_no_player_for_still_gets_a_window(shows):
    # An older session names no players, and its regions want a window of this
    # app's over them exactly as before.
    director, _host, made = shows(fun_time=FakeSession(players={PORTRAIT: object()}))

    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)

    assert "channel" not in made[0].opened_with
    assert made[0].shown == 1


def test_what_is_on_screen_opens_where_the_last_show_left_off(shows):
    host = FakeHost(location="workflow/a", rows=[_row("g1")])
    director, _host, made = shows(host)
    director.open([("a.png", "image", "g1", None)])
    made[0].close()

    director.start()

    assert made[1].resumed == "where-it-got-to"


def test_nothing_to_play_opens_no_show_at_all(shows):
    director, _host, made = shows(FakeHost(rows=[]))

    director.start()

    assert made == []
    assert director.showing is None


def test_the_queue_plate_comes_up_filled_rather_than_blank(shows):
    # The hold on videos is this opening's own doing, so the corner says what is
    # waiting on it rather than going blank for a second and a half.
    host = FakeHost()
    waiting = _being_made("g-waiting", frame=None)
    host.queue = ([waiting], 3)
    director, _host, made = shows(host)

    director.open([("a.png", "image", "g1", None)])

    assert made[0].queue_set == ([waiting], 3)


def test_the_plate_clear_drops_another_apps_work(shows):
    director, host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    made[0].queue().clear_queue_requested.emit()

    assert host.cleared_queue == 1


def test_the_spoken_filter_narrows_the_show_and_says_what_is_left(shows):
    # A speaker who has just narrowed a show wants to know there is still
    # something in it, and "nothing here is enhanced" is the one answer worth
    # hearing at once.
    show = FakeShow()
    show.enhanced_items = ["a", "b"]
    director, _host, _made = shows()
    director._slideshow = show

    director.filter_enhanced(True)

    assert show.said == ["🎤 enhanced only — 2 to play"]


def test_a_show_with_nothing_enhanced_in_it_says_so(shows):
    show = FakeShow()
    director, _host, _made = shows()
    director._slideshow = show

    director.filter_enhanced(True)

    assert show.said == ["🎤 nothing here is enhanced"]
    assert show.said_kinds == [WARNING]


def test_clearing_the_filter_takes_f_mode_with_it(shows):
    # "clear filter" is the way out of ALL of the narrowing, on every satellite
    # in this family.
    show = FakeShow()
    show.hud_favorites_filter = True
    director, _host, _made = shows()
    director._slideshow = show

    director.filter_enhanced(False)

    assert show.hud_favorites_filter is False
    assert show.said == ["🎤 showing all of them"]


def test_the_filter_with_no_show_up_says_there_is_nothing_to_narrow(shows):
    director, host, _made = shows()

    director.filter_enhanced(True)

    assert host.said == ["🎤 the filter needs a show to narrow"]


def test_every_surface_lets_go_of_a_file_a_delete_is_about_to_move(shows):
    # Windows won't move a file while a handle on it is open.
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.release_media(["one.png"])

    assert [show.released for show in made] == [[["one.png"]], [["one.png"]]]


# --- the map around the slide on screen: what the library says ---------------

def _picture(prompt_id, prompt, *, seed, steps=50, width=100, height=200):
    """A finished picture with real params, shaped by what it asked for —
    which is what places it on a side with no file to measure."""
    params = {"positive_prompt": prompt, "seed": seed, "steps": steps,
              "width": width, "height": height}
    row = _row(prompt_id, params=params)
    row["params_json"] = json.dumps(params)
    return row


def _animation(prompt_id, *, frame, act, width=100, height=200):
    """A finished video animated from the picture that wrote *frame*, showing
    *act* — picked for it in Combine, which is where an act is written down."""
    params = {"positive_prompt": "it moves", "noise_seed": 5, "input_image": frame,
              "width": width, "height": height}
    row = _row(prompt_id, workflow_name="wan22_i2v", params=params,
               files=(f"{prompt_id}.mp4",))
    row["params_json"] = json.dumps(params)
    row["recipe_category"] = act
    return row


def _library(rows):
    """A director over *rows*, its gallery indexing the pictures among them the
    way the real one does."""
    host = FakeHost(rows=rows)
    index = gallery.build_image_config_index(
        [row for row in rows if row["workflow_name"] != "wan22_i2v"])
    host.image_config_index = lambda: index
    return host


def test_the_library_of_the_shows_side_answers_for_the_map_around_a_generation(shows):
    """The same configuration under other seeds is the row and the videos
    animated from the picture are the column, each named for its act — read
    off every generation of that side's shape, whatever set the show itself is
    playing."""
    fox = _picture("g1", "a red fox", seed=1)
    fox["output_files"] = json.dumps([{"filename": "g1.png"}])
    rows = [fox, _picture("g2", "a red fox", seed=2),
            _animation("v1", frame="g1.png", act="alpha"),
            _animation("v2", frame="g1.png", act="beta"),
            _animation("v3", frame="g1.png", act="beta"),
            _picture("w1", "a red fox", seed=3, width=200, height=100)]
    director, _host, _made = shows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", side="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["g2"]
    assert [row.slide.prompt_id for row in around.column] == ["v1", "v2"]
    assert (around.label, tuple(row.label for row in around.column)) == (
        "Source image", ("alpha", "beta"))
    assert [slide.prompt_id for slide in around.group] == ["v1", "v2", "v3"]


def _fox(prompt_id, *, seed):
    picture = _picture(prompt_id, "a red fox", seed=seed)
    picture["output_files"] = json.dumps([{"filename": f"{prompt_id}.png"}])
    return picture


def test_the_column_is_this_seeds_other_configurations_then_the_videos_of_it(shows):
    """Both halves, in that order: the same seed under another configuration,
    named by its folder as the tree names it, and then the videos animated from
    this picture, named by the act each shows."""
    fox = _fox("g1", seed=1)
    tweaked = _picture("g2", "a red fox at dawn", seed=1)
    tweaked["output_files"] = json.dumps([{"filename": "g2.png"}])
    rows = [fox, tweaked, _fox("g3", seed=2),
            _animation("v1", frame="g1.png", act="alpha")]
    director, _host, _made = shows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("g1", side="portrait")

    assert [row.slide.prompt_id for row in around.column] == ["g2", "v1"]
    folder, act = (row.label for row in around.column)
    assert act == "alpha"
    assert folder and folder not in ("alpha", "Source image")   # the tree's name for it


def test_a_video_sits_under_its_pictures_seed_with_the_picture_down_its_column(shows):
    """A video's own sampler seed says nothing about which picture it is of, so
    its row is its act animated from its picture's other seeds, and its column
    opens on the picture it was animated from."""
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", act="alpha"),
            _animation("v2", frame="g2.png", act="alpha"),
            _animation("v3", frame="g1.png", act="beta")]
    director, _host, _made = shows(_library(rows), db=FakeDB(rows))

    around = director.neighbors_of("v1", side="portrait")

    assert [slide.prompt_id for slide in around.seeds] == ["v2"]
    assert [row.slide.prompt_id for row in around.column] == ["g1", "v3"]
    assert (around.label, tuple(row.label for row in around.column)) == (
        "alpha", ("Source image", "beta"))


def test_the_library_says_what_each_generation_an_act_filter_asks_about_is_named_for(shows):
    rows = [_fox("g1", seed=1), _fox("g2", seed=2),
            _animation("v1", frame="g1.png", act="alpha")]
    director, _host, _made = shows(_library(rows), db=FakeDB(rows))

    assert director.acts_of(["g1", "v1", "nobody"], side="portrait") == {
        "g1": "Source image", "v1": "alpha"}


def test_a_picture_taken_away_leaves_the_map_its_row_draws(shows):
    """The map is read off the library every time it is drawn, not off a list
    taken once — so a picture condemned from a show stops being drawn beside its
    siblings instead of offering a thumbnail of something that is gone."""
    rows = [_picture("g1", "a red fox", seed=1), _picture("g2", "a red fox", seed=2)]
    host, db = FakeHost(rows=rows), FakeDB(rows)
    director, _host, _made = shows(host, db=db)
    assert [slide.prompt_id for slide in director.neighbors_of("g1", side="portrait").seeds] == ["g2"]

    db.rows.pop("g2")                                    # condemned: the row goes
    host.rows = [row for row in host.rows if row["prompt_id"] != "g2"]

    assert director.neighbors_of("g1", side="portrait").seeds == ()


def test_beyond_the_row_lies_the_nearest_of_the_models_other_configurations(shows):
    rows = [_picture("g1", "a red fox", seed=1), _picture("g2", "a red fox", seed=2),
            _picture("g3", "a red fox at dawn", seed=7),
            _picture("g4", "a blue car", seed=8, steps=30)]
    director, _host, _made = shows(FakeHost(rows=rows), db=FakeDB(rows))

    beyond = director.beyond_the_row_of("g1", side="portrait")

    assert [slide.prompt_id for slide in beyond] == ["g3", "g4"]
    assert director.beyond_the_row_of("nobody", side="portrait") == ()


def test_a_generation_the_gallery_has_no_row_for_maps_alone(shows):
    director, _host, _made = shows()

    assert director.neighbors_of("nobody", side="portrait").seeds == ()
    assert director.neighbors_of("", side="landscape").column == ()


def test_a_show_is_wired_to_the_library_of_the_side_it_opened_on(shows):
    """What a show asks the gallery on its own behalf now includes what the
    library says about an item — and the star's undoing, for the players'
    "weird" over a favorite."""
    rows = [_picture("g1", "a red fox", seed=1), _picture("g2", "a red fox", seed=2)]
    director, host, made = shows(FakeHost(rows=rows), db=FakeDB(rows))

    director.open(director.items_of(rows), location="a-folder", side="portrait")

    actions = made[0].actions
    assert [slide.prompt_id for slide in actions.neighbors("g1").seeds] == ["g2"]
    assert actions.widen("g1") == ()
    assert actions.acts(["g1"]) == {"g1": ""}
    actions.favorite("g1")
    actions.unfavorite("g1")
    assert host.favorited == []


def _a_sitting():
    """Newest first, as a shelf lists: two seeds of one picture, another picture,
    then two more seeds of the first."""
    return [_picture("g5", "a red fox", seed=5), _picture("g4", "a red fox", seed=4),
            _picture("g3", "a blue car", seed=3),
            _picture("g2", "a red fox", seed=2), _picture("g1", "a red fox", seed=1)]


def _played(show) -> list[str]:
    return [item[2] for item in show.items]


def test_a_show_of_latest_plays_one_of_each_run_of_a_folders_generations(shows):
    rows = _a_sitting()
    director, _host, made = shows(FakeHost(location=LATEST_PORTRAIT, rows=rows))

    director.start()

    assert _played(made[0]) == ["g5", "g3", "g2"]


def test_a_show_of_a_folders_latest_plays_one_of_each_run_newest_first(shows):
    location = oriented_key(FolderShelf(RECENTS_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = shows(FakeHost(location=location, rows=_a_sitting()))

    director.start()

    assert _played(made[0]) == ["g5", "g3", "g2"]


def test_a_show_of_a_folder_plays_every_one_of_its_seeds(shows):
    rows = _a_sitting()
    director, _host, made = shows(FakeHost(location="workflow/a", rows=rows))

    director.start()

    assert _played(made[0]) == ["g5", "g4", "g3", "g2", "g1"]


def test_a_seed_landing_while_latest_plays_reaches_it_as_its_runs_newest(shows):
    sitting = _a_sitting()
    browser = FakeBrowser(shelves={LATEST_PORTRAIT: sitting})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.open(director.items_of(director.rows_at(LATEST_PORTRAIT)),
                  location=LATEST_PORTRAIT, side=PORTRAIT)
    another_seed = _picture("g6", "a red fox", seed=6)
    a_new_picture = _picture("g7", "a green hill", seed=7)

    browser.shelves[LATEST_PORTRAIT] = [another_seed, *sitting]
    director.note_finished(another_seed)
    browser.shelves[LATEST_PORTRAIT] = [a_new_picture, another_seed, *sitting]
    director.note_finished(a_new_picture)

    assert [added[0] for added in made[0].added] == ["g6", "g7"]


def test_a_show_of_favorites_plays_the_sides_whole_library_with_the_filter_on(shows):
    """Favorites is the Shuffle playlist with the favorites switch held down,
    so the switch can be let go to widen and the order pair still means the
    library rather than the bookmarks."""
    rows = [_picture("g1", "a red fox", seed=1), _picture("g2", "a blue car", seed=2)]
    browser = FakeBrowser(shelves={oriented_key(FAVORITES_KEY, PORTRAIT): [rows[0]],
                                   ALL_PORTRAIT: rows})
    director, _host, made = shows(FakeHost(location=oriented_key(FAVORITES_KEY, PORTRAIT),
                                           rows=rows),
                                  browser=browser)

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].hud_favorites_filter is True
    assert director._live_shows == [(made[0], ALL_PORTRAIT)]


def _folder_of(rows):
    return gallery.SettingsGroup("workflow/a", "A", list(rows))


def test_a_show_of_a_folders_favorites_plays_that_folder_with_the_filter_on(shows):
    rows = [_picture("g1", "a red fox", seed=1), _picture("g2", "a blue car", seed=2)]
    folder = oriented_key("workflow/a", PORTRAIT)
    favorites = oriented_key(FolderShelf(FAVORITES_KEY, "workflow/a").key, PORTRAIT)
    director, _host, made = shows(FakeHost(location=favorites, rows=[rows[0]],
                                           groups={folder: _folder_of(rows)}))

    director.start()

    assert _played(made[0]) == ["g1", "g2"]
    assert made[0].hud_favorites_filter is True
    assert director._live_shows == [(made[0], folder)]


def test_a_show_of_latest_opens_on_the_newest_rather_than_where_the_last_one_stopped(shows):
    """Latest is newest-first and the newest is the whole point of opening it,
    so it does not pick up where a Latest show left off."""
    rows = _a_sitting()
    director, _host, made = shows(FakeHost(location=LATEST_PORTRAIT, rows=rows))
    director._show_state = ShowState(order=["g1"], current="g1")

    director.start()

    assert made[0].resumed is None


def test_a_show_of_a_folder_still_picks_up_where_the_last_one_stopped(shows):
    director, _host, made = shows(FakeHost(location="workflow/a",
                                           rows=[_picture("g1", "a red fox", seed=1)]))
    director._show_state = ShowState(order=["g1"], current="g1")

    director.start()

    assert made[0].resumed is director._show_state



# --- what is being made while a show is up --------------------------------------

def _being_made(key, frame=b"frame"):
    return SimpleNamespace(key=key, reading=SimpleNamespace(frame=frame))


def test_how_the_enhancements_are_going_reaches_every_show_that_is_up(shows):
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.note_enhancing({"g1": "running"})

    assert [show.enhancing for show in made] == [{"g1": "running"}] * 2


def test_a_show_opens_knowing_what_is_being_enhanced(shows):
    director, _host, made = shows()
    director.note_enhancing({"g1": "running"})

    director.open([("a.png", "image", "g1", None)])

    assert made[0].hud.enhancing == {"g1": "running"}


def test_a_show_opened_with_no_slide_named_leads_with_the_run_being_generated(shows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    host.queue = ([_being_made("g-run")], 0)
    director, _host, made = shows(host=host, db=FakeDB([_row("g1"), _row("g-run")]))

    director.open([("a.png", "image", "g1", None)])

    assert made[0].generating == [("g-run", b"frame")]
    assert made[0].leads == 1


def test_a_show_opened_on_a_named_slide_is_led_nowhere_else(shows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    host.queue = ([_being_made("g-run")], 0)
    director, _host, made = shows(host=host, db=FakeDB([_row("g1"), _row("g-run")]))

    director.open([("a.png", "image", "g1", None)], start=0)

    assert (made[0].generating, made[0].leads) == ([], 0)


def test_a_landed_enhancement_hands_every_show_the_pictures_new_versions(
        shows, tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "better.png").write_bytes(b"pixels")
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output)
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)
    director.versions_of = lambda rows: {"better.png": ["newer", "older"]}

    director.note_enhanced(_row("g1", files=("better.png",)))

    assert [show.levels_added for show in made] == [[{"better.png": ["newer", "older"]}]] * 2


def test_the_frames_of_the_enhancements_being_made_reach_every_show_that_is_up(shows):
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.note_enhancing({"g1": "running"}, frames={"g1": b"frame"})

    assert [show.enhancing_frames for show in made] == [{"g1": b"frame"}] * 2


def test_a_run_reaches_each_show_whose_own_set_holds_it(shows):
    browser = FakeBrowser(shelves={"shelf/a": [_row("g1"), _row("g-run")],
                                   "shelf/b": [_row("g2")]})
    director, _host, made = shows(browser=browser, db=FakeDB([_row("g-run")]),
                                  fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="shelf/a", side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="shelf/b", side=PORTRAIT)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == [("g-run", b"frame")]
    assert made[1].generating == []


def test_every_show_that_is_up_hears_which_runs_are_still_being_made(shows):
    browser = FakeBrowser(shelves={"shelf/a": [_row("g1")], "shelf/b": [_row("g2")]})
    director, _host, made = shows(browser=browser, fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location="shelf/a", side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], location="shelf/b", side=PORTRAIT)

    director.note_in_flight([_being_made("g-run", frame=None)])

    assert [show.in_flight for show in made] == [{"g-run"}, {"g-run"}]


def test_a_latest_show_takes_a_new_run_after_the_browser_has_moved_on(shows):
    browser = FakeBrowser(shelves={LATEST_LANDSCAPE: [_row("g1")]}, recents=False)
    director, _host, made = shows(browser=browser, db=FakeDB([_row("g-run")]),
                                  fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_LANDSCAPE,
                  side=LANDSCAPE)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == [("g-run", b"frame")]


def test_a_latest_show_turns_down_a_run_asked_for_in_the_other_shape(shows):
    run = _row("g-run")
    run["params_json"] = json.dumps({"width": 1024, "height": 768})
    browser = FakeBrowser(shelves={LATEST_PORTRAIT: [_row("g1")]})
    director, _host, made = shows(browser=browser, db=FakeDB([run]),
                                  fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], location=LATEST_PORTRAIT,
                  side=PORTRAIT)

    director.note_generating("g-run", b"frame")

    assert made[0].generating == []


def test_a_run_double_clicked_while_hosted_opens_its_folder_on_a_player_leading_with_it(shows):
    host = FakeHost(rows=[_row("g1"), _row("g-run")])
    director, host, made = shows(host, db=FakeDB([_row("g-run")]), fun_time=FakeSession(
        players={PORTRAIT: object(), LANDSCAPE: object()}))
    host.queue = ([_being_made("g-run")], 0)

    director.open([], folder_items=[("a.png", "image", "g1", None)], start=0,
                  frame=b"frame")

    assert made[0].items == [("a.png", "image", "g1", None)]
    assert made[0].generating == [("g-run", b"frame")]
    assert made[0].leads == 1
