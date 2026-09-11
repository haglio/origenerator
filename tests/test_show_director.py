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

import pytest
from PyQt6.QtCore import Qt

from origenerator import gallery
from origenerator.gui import show_director as module
from origenerator.gui.orientation import oriented_key
from origenerator.gui.show_director import ShowDirector
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.show_commands import ShowCommand

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
# What a region plays with nothing else asked for: the whole library,
# narrowed to that region's shape.
ALL_PORTRAIT = oriented_key(gallery.ALL_KEY, PORTRAIT)
ALL_LANDSCAPE = oriented_key(gallery.ALL_KEY, LANDSCAPE)


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
        self.runs_said = []
        self.levels = None
        self.playlist = None
        self.resumed = None
        self.retuned = None
        self.dwell_s = None
        self.session_paused = None
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
        self.held = set()
        self.hud_f_mode = False
        self.steps = []
        self.culled = 0
        self.starrable = True
        self.stars = 0
        self.hud_panel = None
        self.released = []
        self.pause_raises = False
        self.state_at_close = "where-it-got-to"

    # what a show is, and what it holds
    def queue(self):
        return self._queue

    def is_live(self):
        return self.live

    def holds(self, prompt_id):
        return prompt_id in self.held

    def state(self):
        return self.state_at_close

    def isVisible(self):
        return self.visible

    # what the director tells it
    def set_playlist(self, items, index):
        self.playlist = (list(items), index)

    def set_levels(self, levels):
        self.levels = levels

    def resume(self, state):
        self.resumed = state

    def retune(self, items, *, enhanced_ids):
        self.retuned = (list(items), set(enhanced_ids))

    def note_added(self, path, media_type, prompt_id, thumb, *, starred, enhanced):
        self.added.append((prompt_id, starred, enhanced))

    def note_generating(self, prompt_id, frame):
        self.generating.append((prompt_id, frame))

    def note_in_flight(self, keys):
        self.in_flight = set(keys)

    def note_enhanced(self, prompt_id, path, media_type, *, still):
        self.enhanced.append((prompt_id, media_type, still))

    def note_enhancing(self, statuses):
        self.enhancing = dict(statuses)

    def note_voice_command(self, message):
        self.said.append(message)

    def note_voice_run(self, prompt_id, message):
        self.runs_said.append((prompt_id, message))

    def set_queue(self, items, foreign_total):
        self.queue_set = (list(items), foreign_total)

    def set_dwell_s(self, seconds):
        self.dwell_s = seconds

    def set_session_paused(self, paused):
        if self.pause_raises:
            raise RuntimeError("this show will not freeze")
        self.session_paused = paused

    def set_audio_muted(self, muted):
        self.audio_muted = muted

    def release_media(self, paths):
        self.released.append(list(paths))

    def reset_in_place(self):
        self.retuned = "in place"

    def osr2_drive_target(self):
        return self.opened_with.get("drive_target")

    def toggle_f_mode(self):
        self.hud_f_mode = not self.hud_f_mode

    def step(self, delta):
        self.steps.append(delta)

    def cull(self):
        self.culled += 1

    def star(self):
        self.stars += 1
        return self.starrable

    def set_held(self, held):
        return held

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
    """A hosting Fun Time session reduced to the two things a show asks of one."""

    dashboard_cmd_file = None

    def region_rect(self, side):
        return FakeRect(0 if side == LANDSCAPE else 1920, 0, 960, 540)


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
        self.starred = []
        self.enhanced = []
        self.drive_toggles = 0
        self.reconciles = 0
        self.cleared_queue = 0
        self.queue = ([], 0)
        self.playlists = {"a.png": [("a.png", "image", "v1")]}
        self.media = [("m.png", "image", "m1", None)]
        self.media_index = 0
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

    def level_playlists(self):
        return self.playlists

    def folder_media(self):
        return self.media

    def folder_media_playlist(self):
        return list(self.media), self.media_index

    def queue_now(self):
        return self.queue

    def clear_foreign_queue(self):
        self.cleared_queue += 1

    def follow_link(self, prompt_id):
        self.followed.append(prompt_id)

    def trash_generation(self, prompt_id):
        self.trashed.append(prompt_id)

    def star_generation(self, prompt_id):
        self.starred.append(prompt_id)

    def enhance_from_slideshow(self, prompt_id):
        self.enhanced.append(prompt_id)
        return True

    def toggle_osr2_drive(self):
        self.drive_toggles += 1

    def reconcile_osr2(self):
        self.reconciles += 1

    def say(self, message):
        self.said.append(message)


def _row(prompt_id, *, workflow_name="sdxl_t2i", starred=False, params=None,
         files=("one.png",)):
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "workflow": workflow_name,
        "starred": starred,
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
    monkeypatch.setattr(module, "_shared_hud_widget", lambda: None)
    monkeypatch.setattr(module, "place_window_in_device_pixels",
                        lambda *args: None)

    def build(host=None, *, db=None, browser=None, fun_time=None):
        host = host or FakeHost()
        director = ShowDirector(
            host, db=db or FakeDB(), browser=browser or FakeBrowser(),
            reroll=FakeReroll(), pace=FakePace(), motion=None,
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

    assert director._reroll.holds == [True]


def test_the_last_show_closing_lets_the_videos_go(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    made[0].close()

    assert director.showing is None
    assert director._reroll.holds == [True, False]


def test_one_of_two_shows_closing_keeps_the_hold_and_the_other(shows):
    # Hosted, two run at once: closing the portrait one must not forget the
    # landscape one, and the videos stay held while it is still playing them.
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    made[1].close()

    assert director.showing is made[0]
    assert director._reroll.holds == [True, True]


def test_a_landing_reaches_the_show_whose_own_folder_holds_it(shows):
    # Asked of each show's OWN location rather than of the browser, which has
    # usually moved on by the time a generation lands.
    browser = FakeBrowser(shelves={"shelf/a": [_row("g9")], "shelf/b": []})
    director, _host, made = shows(browser=browser)
    director.open([("a.png", "image", "g1", None)], location="shelf/a")
    director.open([("b.png", "image", "g2", None)], location="shelf/b")

    director.note_finished(_row("g9", starred=True))

    assert made[0].added == [("g9", True, False)]
    assert made[1].added == []


def test_a_run_in_another_folder_is_turned_down_once_and_not_asked_again(shows):
    # A frame arrives every second or so, and the question costs a row lookup
    # and a walk of what is on screen.
    host = FakeHost(rows=[_row("g1")])
    director, _host, made = shows(host, db=FakeDB([_row("g7")]))
    director.open([("a.png", "image", "g1", None)])

    director.note_generating("g7", b"frame-one")
    director.note_generating("g7", b"frame-two")

    assert made[0].generating == []
    assert director._show_refused == {"g7"}


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

    assert made[1].session_paused is True


def test_a_show_opened_while_the_room_is_frozen_opens_frozen(shows):
    # The room's OmniPause holds this surface from its first frame, not from
    # whenever the flag next changes.
    director, _host, made = shows(fun_time=FakeSession())
    director.set_session_paused(True)

    director.open([("a.png", "image", "g1", None)], side=PORTRAIT)

    assert made[0].session_paused is True


def test_the_spoken_close_with_no_show_up_says_so(shows):
    director, host, made = shows()

    director.run_show_command(ShowCommand.STOP, None)

    assert host.said == ["🎤 no slideshow to close"]
    assert made == []


def test_the_spoken_pause_with_no_show_sets_what_the_next_one_opens_at(shows):
    # A show that never moves on is exactly what a held picture is here.
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
    from origenerator.gui.gallery_tree import STARRED_KEY

    class Spoken:
        shelf_key = STARRED_KEY
        side = None

    director, host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    director.play_shelf(Spoken())

    assert made[0].hud_f_mode is True
    assert len(made) == 1  # no second show opened
    assert host.said == ["🎤 F-mode on"]


def test_a_spoken_shelf_with_nothing_in_it_opens_nothing(shows):
    from origenerator.gui.gallery_tree import RECENTS_KEY

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


def test_a_star_over_a_slide_with_nothing_to_star_says_so(shows):
    director, _host, made = shows()
    director.open([("a.png", "image", "g1", None)])
    made[0].starrable = False

    director.run_on_slide(AppCommand.STAR)

    assert made[0].said == ["🎤 nothing here to star"]


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
    host.queue = (["a card"], 3)
    director, _host, made = shows(host)

    director.open([("a.png", "image", "g1", None)])

    assert made[0].queue_set == (["a card"], 3)


def test_the_plate_clear_drops_another_apps_work(shows):
    director, host, made = shows()
    director.open([("a.png", "image", "g1", None)])

    made[0].queue().clear_queue_requested.emit()

    assert host.cleared_queue == 1


def test_every_surface_lets_go_of_a_file_a_delete_is_about_to_move(shows):
    # Windows won't move a file while a handle on it is open.
    director, _host, made = shows(fun_time=FakeSession())
    director.open([("a.png", "image", "g1", None)], side=LANDSCAPE)
    director.open([("b.png", "image", "g2", None)], side=PORTRAIT)

    director.release_media(["one.png"])

    assert [show.released for show in made] == [[["one.png"]], [["one.png"]]]
