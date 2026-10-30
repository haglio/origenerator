"""The hosted app's file channels: Fun Time's verbs in, occupancy out.

Fun Time speaks to its Satellite Funestras through a command file, a paused
flag and a status file; a hosted Origenerator answers the same idioms so the
session's hotkeys reach the region slideshows and its choreography can see them.
"""
from __future__ import annotations

import json
import re
import time
from unittest.mock import MagicMock

import pytest
from funestra.file_channel import consume_command_file
from funestra.funestra_verbs import play_file
from funestra.hud_placement import HudCorner
from funestra.playlist import PlaylistItem, read_playlist
from funestra.radio import radio_file_for, read_radio
from funestra.satellite_hud import parse_hud
from PIL import Image

from origenerator import fun_time_mode as contract
from origenerator import gallery
from origenerator.fun_time_bridge import FunTimeBridge
from origenerator.fun_time_mode import FunestraChannel, FunTimeSession, Rect
from origenerator.gallery.collection import FAVORITES_KEY
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui import omnipause, slideshow_director
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.hud_queue import CANCEL
from origenerator.gui.slideshow_pace import DEFAULT_S
from origenerator.slideshow_buttons import answer
from tests.slideshow_hud_support import funestra_of, open_both_sides
from tests.test_gallery_view import (
    _REROLL_HISTORY,
    FakeDB,
    _enhanced_image,
    _generating_tile,
    _image,
    _png_bytes,
    _preview_of,
    _reroll_client,
    _row,
    _running_reroll,
    _seeded_db,
    _will_move_on,
)
from tests.test_slideshow_hud import _inflight


def _session(tmp_path):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=tmp_path / "origenerator_cmd.txt",
        paused_file=tmp_path / "origenerator_paused.txt",
        status_file=tmp_path / "origenerator_status.txt",
        dashboard_cmd_file=tmp_path / "dashboard_cmd.txt",
    )


def _as_items(rows):
    """The fixture's rows as a slideshow's items — a tuple passed through, a row
    stood in for by a tuple named after it — where a test hands the director a
    library of ready-made items rather than files to resolve."""
    return [row if isinstance(row, tuple)
            else (f"{row['prompt_id']}.png", "image", row["prompt_id"], None)
            for row in rows]


def _view_with_bridge(qtbot, tmp_path, rows=()):
    view = GalleryView(FakeDB(list(rows)), fun_time=_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    return view, bridge


def _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path, count=3):
    items = []
    for n in range(count):  # a file each, since a Funestra says what it shows by its file
        still = tmp_path / f"tall{n}.png"
        Image.new("RGB", (100, 200)).save(still)
        items.append((str(still), "image", f"id{n}", str(still)))
    monkeypatch.setattr(view, "rows_to_play",
                        lambda: [{"prompt_id": item[2]} for item in items])
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: list(items))
    monkeypatch.setattr(view, "slideshow_subject", lambda: "a folder")
    view._slideshows.start()
    slideshow = view.region_slideshow("portrait")
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)
    return slideshow


def test_side_verbs_drive_the_slideshow_holding_that_region(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    before = slideshow._set.playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()
    slideshow.tick()  # it reads its Funestra, as its poll does a moment later

    assert slideshow._set.playlist.index == (before + 1) % 3


def test_a_verb_for_an_empty_region_is_dropped(qtbot, tmp_path):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_cmd.txt").write_text("LANDSCAPE_TRASH\n", encoding="utf-8")

    bridge._tick()  # nothing holds the landscape region

    # Dropped, not queued: the verb is taken off the channel like any other, and
    # nothing was opened to answer it with.
    assert not (tmp_path / "origenerator_cmd.txt").exists()
    assert view.region_slideshow("landscape") is None


def test_lock_verb_locks_the_slide(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_LOCK\n", encoding="utf-8")
    bridge._tick()

    assert slideshow.locked


def test_the_spoken_lock_and_unlock_each_leave_the_slide_the_way_they_name(
        qtbot, tmp_path, monkeypatch):
    """Said twice, "portrait lock" stays locked where the key's flip would let
    go: the session sends the words as the state they ask for."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    held = []

    for line in ("portrait_lock_on", "portrait_lock_on", "portrait_lock_off",
                 "portrait_lock_off"):
        _press(bridge, tmp_path, line)
        held.append(slideshow.locked)

    assert held == [True, True, False, False]


def test_reset_verb_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    """The reset on the shared control band, spoken to a slideshow: the lock
    releases and the top of the set comes back."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    slideshow._set.playlist.jump_to(2)
    slideshow.slideshow_toggle_lock()
    assert slideshow.locked

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_RESET\n", encoding="utf-8")
    bridge._tick()

    assert not slideshow.locked
    assert slideshow._set.playlist.index == 0


def test_the_order_verbs_play_the_side_newest_first_or_shuffled(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    still = str(tmp_path / "tall.png")
    library = {key: [(still, "image", f"{key}-{n}", still) for n in range(3)]
               for key in ("__recents__::portrait", "__all__::portrait")}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: [_row_of(item) for item in library.get(key, [])])
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    orders = []

    for verb in ("PORTRAIT_LATEST", "PORTRAIT_SHUFFLE"):
        (tmp_path / "origenerator_cmd.txt").write_text(f"{verb}\n", encoding="utf-8")
        bridge._tick()
        orders.append((slideshow.hud_order_label, slideshow._set.playlist.current()[2].split("-")[0]))

    assert orders == [("Latest", "__recents__::portrait"),
                      ("Shuffle", "__all__::portrait")]


def test_a_spoken_phrase_from_the_session_runs_here(qtbot, tmp_path, monkeypatch):
    """The session owns the room's microphone, so it hears "landscape
    favorites" and posts the WORDS on this channel — matched here, against this
    app's own vocabulary, because only this app knows what its collections are."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    spoken = []
    monkeypatch.setattr(view, "run_spoken_command",
                        lambda text, said_at: spoken.append((text, said_at)))

    (tmp_path / "origenerator_cmd.txt").write_text(
        "LANDSCAPE_SAY:favorites\nPORTRAIT_SAY:fix teeth\n", encoding="utf-8")
    bridge._tick()

    assert spoken == [("landscape favorites", None), ("portrait fix teeth", None)]


def test_a_spoken_phrase_goes_with_when_the_session_heard_it_said(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    commanded = []
    monkeypatch.setattr(view._voice, "on_command",
                        lambda matched, said_at=None: commanded.append(said_at))
    five_seconds_ago = time.time() - 5.0

    (tmp_path / "origenerator_cmd.txt").write_text(
        f"PORTRAIT_SAY:fix teeth @{five_seconds_ago:.3f}\n", encoding="utf-8")
    bridge._tick()

    assert commanded == [pytest.approx(time.monotonic() - 5.0, abs=1.0)]


class _SaidOverShow:
    def __init__(self):
        self.done = []

    def back_to_what_was_said_over(self, said_at):
        self.done.append(("back to", said_at))

    def slideshow_cull(self):
        self.done.append(("weird",))

    def set_locked(self, locked):
        self.done.append(("locked", locked))


def test_a_spoken_weird_goes_back_to_the_slide_it_was_said_over_first(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _SaidOverShow()
    monkeypatch.setattr(view, "region_slideshow", lambda side: show)
    five_seconds_ago = time.time() - 5.0

    (tmp_path / "origenerator_cmd.txt").write_text(
        f"portrait_trash @{five_seconds_ago:.3f}\n", encoding="utf-8")
    bridge._tick()

    assert show.done == [("back to", pytest.approx(time.monotonic() - 5.0, abs=1.0)), ("weird",)]


def test_a_lock_the_session_sends_is_taken_on_the_slide_it_brought_back(qtbot, tmp_path,
                                                                        monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _SaidOverShow()
    monkeypatch.setattr(view, "region_slideshow", lambda side: show)

    (tmp_path / "origenerator_cmd.txt").write_text(
        f"portrait_lock_on @{time.time() - 5.0:.3f}\n", encoding="utf-8")
    bridge._tick()

    assert show.done == [("locked", True)]


def test_a_spoken_phrase_is_matched_by_this_apps_own_vocabulary(qtbot, tmp_path, monkeypatch):
    """End to end from the words: the phrase the session heard becomes the
    command this app would have matched had it heard it itself."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    played = []
    monkeypatch.setattr(view._slideshows, "play_collection", played.append)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "LANDSCAPE_SAY:favorites\n", encoding="utf-8")
    bridge._tick()

    assert [(c.collection_key, c.side) for c in played] == [(FAVORITES_KEY, "landscape")]


def test_a_side_handed_over_on_its_own_is_filled_on_its_own(qtbot, tmp_path, monkeypatch):
    """Each of the session's Satellite Funestras goes into Origenerator mode by
    itself, so the session hands this app one side at a time."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    filled = []
    monkeypatch.setattr(view, "fill_the_region", filled.append)

    (tmp_path / "origenerator_cmd.txt").write_text("portrait_open_slideshow\n", encoding="utf-8")
    bridge._tick()

    assert filled == ["portrait"]


def test_release_asks_for_the_app_back_from_the_session(qtbot, tmp_path):
    _view, bridge = _view_with_bridge(qtbot, tmp_path)
    released = []
    bridge.released.connect(lambda: released.append(True))

    (tmp_path / "origenerator_cmd.txt").write_text("RELEASE\n", encoding="utf-8")
    bridge._tick()

    assert released == [True]


def test_a_released_bridge_answers_the_session_no_further(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    paused = []
    monkeypatch.setattr(view, "set_room_paused", paused.append)

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    (tmp_path / "origenerator_cmd.txt").write_text("RELEASE\nportrait_open_slideshow\n",
                                                 encoding="utf-8")
    monkeypatch.setattr(view, "fill_the_region", lambda side: paused.append("filled"))
    bridge._tick()

    assert paused == []
    assert not (tmp_path / "origenerator_status.txt").exists()


def test_close_slideshows_clears_both_regions(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("CLOSE_SLIDESHOWS\n", encoding="utf-8")
    bridge._tick()

    assert not slideshow.shown.isVisible()
    assert view.region_slideshow("portrait") is None


def test_a_side_taken_back_on_its_own_closes_that_sides_slideshow_alone(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("landscape_close_slideshow\n", encoding="utf-8")
    bridge._tick()
    assert slideshow.shown.isVisible()

    (tmp_path / "origenerator_cmd.txt").write_text("portrait_close_slideshow\n", encoding="utf-8")
    bridge._tick()
    assert not slideshow.shown.isVisible()
    assert view.region_slideshow("portrait") is None


def _fill_both_regions(qtbot, view, monkeypatch, tmp_path, portrait, landscape):
    """Both regions on their base state, each playing the ids named for it —
    what the session's two opens put up, and the arrangement one switch has to move.

    The ids are the fabricated rows' own, so the slideshow can tell which of its
    items carry an enhancement; the items above carry ids no row has.
    """
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    library = {
        "__all__::portrait": [(str(tall), "image", pid, str(tall)) for pid in portrait],
        "__all__::landscape": [(str(wide), "image", pid, str(wide)) for pid in landscape],
    }
    # The library's own row under the fabricated still, so whether an image
    # carries an enhancement is read where the app reads it.
    monkeypatch.setattr(view._slideshows, "rows_at", lambda key: [
        {**(view.row_for(item[2]) or {}), **_row_of(item)}
        for item in library.get(key, [])])
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    open_both_sides(view)
    slideshows = [view.region_slideshow(side) for side in ("portrait", "landscape")]
    for slideshow in slideshows:
        qtbot.addWidget(slideshow.shown)
    return slideshows


def _press_filter_enhanced(bridge, tmp_path):
    (tmp_path / "origenerator_cmd.txt").write_text("FILTER_ENHANCED\n", encoding="utf-8")
    bridge._tick()


def test_filter_enhanced_narrows_both_regions_and_widens_them_again(
        qtbot, tmp_path, monkeypatch):
    """The session's console carries the enhanced-only switch a slideshow's own HUD
    carries, so a press there has to reach the slideshows here — answered nowhere, it
    left the console lit over regions still playing all of them."""
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("p1", "a cat", 50, 1), _enhanced_image("p2", "a cat", 50, 2),
        _image("l1", "a boat", 40, 3), _enhanced_image("l2", "a boat", 40, 4)])
    portrait, landscape = _fill_both_regions(
        qtbot, view, monkeypatch, tmp_path, ["p1", "p2"], ["l1", "l2"])

    _press_filter_enhanced(bridge, tmp_path)

    assert [slideshow.hud_enhanced_mode for slideshow in (portrait, landscape)] == [True, True]
    # Each region down to the one enhanced image it was playing.
    assert [slideshow.pass_size() for slideshow in (portrait, landscape)] == [1, 1]

    _press_filter_enhanced(bridge, tmp_path)

    assert [slideshow.hud_enhanced_mode for slideshow in (portrait, landscape)] == [False, False]
    assert [slideshow.pass_size() for slideshow in (portrait, landscape)] == [2, 2]


def test_filter_enhanced_takes_a_split_pair_of_regions_the_same_way(
        qtbot, tmp_path, monkeypatch):
    """Each region's own HUD carries this switch too, so the two can already
    disagree when the session's one is pressed.  The press reads the pair to
    pick its direction — anything narrowed widens — because flipping each in
    place would only swap which region was narrowed, and one lit switch cannot
    say that a room is half narrowed."""
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("p1", "a cat", 50, 1), _enhanced_image("p2", "a cat", 50, 2),
        _image("l1", "a boat", 40, 3), _enhanced_image("l2", "a boat", 40, 4)])
    portrait, landscape = _fill_both_regions(
        qtbot, view, monkeypatch, tmp_path, ["p1", "p2"], ["l1", "l2"])
    portrait.toggle_enhanced_mode()  # narrowed from its own HUD, the other not

    _press_filter_enhanced(bridge, tmp_path)

    assert [slideshow.hud_enhanced_mode for slideshow in (portrait, landscape)] == [False, False]


def test_filter_enhanced_leaves_a_region_with_nothing_enhanced_playing_it_all(
        qtbot, tmp_path, monkeypatch):
    """A set with nothing enhanced in it refuses the narrowing rather than
    emptying itself, exactly as it does when its own HUD button is pressed."""
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("p1", "a cat", 50, 1), _enhanced_image("p2", "a cat", 50, 2),
        _image("l1", "a boat", 40, 3), _image("l2", "a boat", 40, 4)])
    portrait, landscape = _fill_both_regions(
        qtbot, view, monkeypatch, tmp_path, ["p1", "p2"], ["l1", "l2"])

    _press_filter_enhanced(bridge, tmp_path)

    assert [slideshow.hud_enhanced_mode for slideshow in (portrait, landscape)] == [True, False]
    assert [slideshow.pass_size() for slideshow in (portrait, landscape)] == [1, 2]


def test_filter_enhanced_with_no_slideshow_up_is_dropped(qtbot, tmp_path):
    """Nothing to narrow and nothing armed for later: the verb comes off the
    channel like any other and the mode is left as it was."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)

    _press_filter_enhanced(bridge, tmp_path)

    assert not (tmp_path / "origenerator_cmd.txt").exists()
    assert view.region_slideshow("portrait") is None
    assert view.region_slideshow("landscape") is None


def test_the_paused_flag_freezes_and_resumes_an_open_slideshow(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    assert _will_move_on(slideshow)  # an image slide dwells on its timer

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    assert not _will_move_on(slideshow)

    (tmp_path / "origenerator_paused.txt").write_text("0", encoding="utf-8")
    bridge._tick()
    assert _will_move_on(slideshow)


def test_omnipause_stops_the_gallerys_own_moving_thumbnails(qtbot, tmp_path):
    """Every video tile loops a little clip of itself and the generate tabs
    play the real thing, so a paused room with the gallery in it was a wall of
    clips still going. OmniPause stops the room, not only its slideshows, and one
    freeze covers every one of them — wherever drawn, and whenever built."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    assert omnipause.frozen() is False

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    assert omnipause.frozen() is True

    (tmp_path / "origenerator_paused.txt").write_text("0", encoding="utf-8")
    bridge._tick()
    assert omnipause.frozen() is False


def test_the_status_file_says_this_app_is_up(qtbot, tmp_path):
    """All the session asks of this file, and all it has ever asked: that it is
    there and reads.  It waits on it before opening the mode, because a mode
    opened over an app still booting has nothing under it."""
    _view, bridge = _view_with_bridge(qtbot, tmp_path)

    bridge._tick()

    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert text.strip() == FunTimeBridge.READY


def test_a_status_file_cleared_under_it_is_written_again(qtbot, tmp_path):
    """The session clears this file as it opens the mode, so that last
    session's does not answer for this one.  A signal written once and
    remembered would never come back for the session that cleared it, and the
    mode would sit closed forever."""
    _view, bridge = _view_with_bridge(qtbot, tmp_path)
    bridge._tick()
    (tmp_path / "origenerator_status.txt").unlink()

    bridge._tick()

    assert (tmp_path / "origenerator_status.txt").read_text(
        encoding="utf-8").strip() == FunTimeBridge.READY


def test_a_slideshow_opened_mid_pause_opens_frozen(qtbot, tmp_path, monkeypatch):
    """The room being OmniPaused must hold a slideshow the user opens DURING the
    pause too — the flag edged onto already-open slideshows once, so a slideshow
    started mid-pause played while everything else in the session stood."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()

    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    assert not _will_move_on(slideshow)  # no dwell armed: it opened frozen


def test_a_step_while_paused_lands_on_a_slide_that_stays_frozen(qtbot, tmp_path, monkeypatch):
    """Stepping a frozen slideshow moves it to a new slide, but the new slide must
    arrive frozen — re-arming the dwell was the slideshow quietly unpausing
    itself while the rest of the room stayed frozen."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    before = slideshow._set.playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()
    slideshow.tick()  # it reads its Funestra, as its poll does a moment later

    assert slideshow._set.playlist.index == (before + 1) % 3  # the step still lands
    assert not _will_move_on(slideshow)                # but the slide stays frozen


def test_a_spoken_request_from_the_session_is_collected_here(qtbot, tmp_path, monkeypatch):
    """The one spoken input with no phrase to match: the words between
    "request" and "over" are the speaker's own, so the session forwards each
    utterance verbatim and this app's own dictation assembles them — the same
    one its mic feeds, since the two never listen at once.

    Fabricated request wording, like every fixture here.
    """
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    begun = []
    monkeypatch.setattr(view._voice, "_begin_request",
                        lambda target, spoken, side=None: begun.append((spoken.text, side)))

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:request no feet\n", encoding="utf-8")
    bridge._tick()
    assert not begun  # still being said — the slideshow pauses rather than acting

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:over\n", encoding="utf-8")
    bridge._tick()

    # The side is the region it was said to, not the first word of the request.
    assert begun == [("no feet", "portrait")]
    assert slideshow is view.region_slideshow("portrait")


def test_the_words_of_a_request_are_not_read_as_commands(qtbot, tmp_path, monkeypatch):
    """While one is open the dictation swallows what it hears — half a sentence
    must not fire a command because two of its words happened to be one."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    played = []
    monkeypatch.setattr(view._slideshows, "play_collection", played.append)
    monkeypatch.setattr(view._voice, "_begin_request", lambda *a, **kw: None)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:request no feet\nPORTRAIT_SAY:favorites\nPORTRAIT_SAY:over\n",
        encoding="utf-8")
    bridge._tick()

    assert played == []


def _the_room_was_told(tmp_path) -> list[str]:
    return consume_command_file(tmp_path / "dashboard_cmd.txt", uppercase=False)


def _said_to_this_app(bridge, tmp_path, *lines: str) -> None:
    (tmp_path / "origenerator_cmd.txt").write_text(
        "".join(f"{line}\n" for line in lines), encoding="utf-8")
    bridge._tick()


def test_the_room_is_told_a_request_has_opened_on_the_side_it_was_said_to(
        qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _said_to_this_app(bridge, tmp_path, "PORTRAIT_SAY:request")

    assert _the_room_was_told(tmp_path) == ["portrait_request_open"]


def test_the_room_is_told_the_request_is_over_once_over_is_said(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    monkeypatch.setattr(view._voice, "_begin_request", lambda *a, **kw: None)
    _said_to_this_app(bridge, tmp_path, "PORTRAIT_SAY:request", "PORTRAIT_SAY:no feet")

    _said_to_this_app(bridge, tmp_path, "PORTRAIT_SAY:over")

    told = _the_room_was_told(tmp_path)
    assert told == ["portrait_request_open", "portrait_request_closed"]
    assert set(told) <= set(contract.declaration()["request_lines"])


def test_a_request_said_in_one_breath_leaves_the_room_nothing_to_hear(
        qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    monkeypatch.setattr(view._voice, "_begin_request", lambda *a, **kw: None)

    _said_to_this_app(bridge, tmp_path, "PORTRAIT_SAY:request no feet over")

    assert _the_room_was_told(tmp_path) == []


def test_closing_the_slideshow_a_request_was_said_to_drops_the_request(
        qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    played = []
    monkeypatch.setattr(view._slideshows, "play_collection", played.append)
    _said_to_this_app(bridge, tmp_path, "PORTRAIT_SAY:request")

    _said_to_this_app(bridge, tmp_path, "PORTRAIT_CLOSE_SLIDESHOW")
    _said_to_this_app(bridge, tmp_path, "PORTRAIT_SAY:favorites")

    assert _the_room_was_told(tmp_path) == ["portrait_request_open", "portrait_request_closed"]
    assert len(played) == 1


def _press(bridge, tmp_path, line: str) -> None:
    """A press the session routed back here, as a Funestra's HUD posted it."""
    (tmp_path / "origenerator_cmd.txt").write_text(f"{line}\n", encoding="utf-8")
    bridge._tick()


def test_a_funestras_filter_presses_reach_the_slideshow_on_that_side(qtbot, tmp_path, monkeypatch):
    """A session hands a Funestra's presses back verbatim, spelled the way the
    HUD posted them — so the slideshow's own two switches answer them here."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    monkeypatch.setattr(view._slideshows, "_favorite_prompt_ids", lambda: {"id1"})
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_fmode")

    assert slideshow.hud_favorites_filter is True
    assert slideshow.pass_size() == 1


def test_a_press_on_a_funestras_clip_seconds_paces_the_slideshow_on_that_side(
        qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_clip_seconds_up")
    assert slideshow.dwell_s == DEFAULT_S + 1

    _press(bridge, tmp_path, "portrait_clip_seconds_down")
    assert slideshow.dwell_s == DEFAULT_S


def test_a_thumbnail_press_carries_its_path_through_the_colon_in_it(qtbot, tmp_path, monkeypatch):
    """A path rides after the "|", and a Windows path has a colon of its own —
    which must not be read as the start of a spoken phrase."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    jumps = []
    monkeypatch.setattr(slideshow, "show_item", lambda path, *, lock=False: jumps.append((path, lock)))

    _press(bridge, tmp_path, r"portrait_lock_video|C:\fixtures\scene one.png")

    assert jumps == [(r"C:\fixtures\scene one.png", True)]


def test_a_press_no_slideshow_answers_is_dropped_on_the_log(qtbot, tmp_path, monkeypatch, caplog):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_wrong_action")

    assert "portrait_wrong_action" in caplog.text
    assert not (tmp_path / "origenerator_cmd.txt").exists()


def _funestras_session(tmp_path):
    def channel(side):
        return FunestraChannel(
            playlist=tmp_path / f"{side}.tsv",
            command_file=tmp_path / f"{side}_cmd.txt",
            status_file=tmp_path / f"{side}_status.txt",
            hud_file=tmp_path / f"origenerator_{side}_hud.json",
        )
    session = _session(tmp_path)
    return FunTimeSession(
        main_rect=session.main_rect, portrait_rect=session.portrait_rect,
        landscape_rect=session.landscape_rect, command_file=session.command_file,
        paused_file=session.paused_file, status_file=session.status_file,
        dashboard_cmd_file=session.dashboard_cmd_file,
        portrait_funestra=channel("portrait"), landscape_funestra=channel("landscape"),
    )


def test_a_session_that_hands_over_its_funestras_gets_both_sides_on_them(
        qtbot, tmp_path, monkeypatch):
    """Entering the mode with the Funestras handed over: each Funestra is given the
    list of its own side's shape, and no window of this app's opens at all."""
    def no_window(*args, **kwargs):
        raise AssertionError("a window of this app's opened over a region")

    monkeypatch.setattr(slideshow_director, "SlideshowView", no_window)
    view = GalleryView(FakeDB([]), fun_time=_funestras_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    library = {"__all__::portrait": [(str(tall), "image", "id-tall", str(tall))],
               "__all__::landscape": [(str(wide), "image", "id-wide", str(wide))]}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: [_row_of(item) for item in library.get(key, [])])
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)

    _press(bridge, tmp_path, "portrait_open_slideshow")
    _press(bridge, tmp_path, "landscape_open_slideshow")

    assert [str(item.path) for item in read_playlist(tmp_path / "portrait.tsv")] == [str(tall)]
    assert [str(item.path) for item in read_playlist(tmp_path / "landscape.tsv")] == [str(wide)]
    assert view.region_slideshow("portrait").is_showing()


class _MinimizedCore:
    def isVisible(self) -> bool:
        return True

    def isMinimized(self) -> bool:
        return True


def test_the_document_names_each_press_on_the_job_queue_a_funestra_draws():
    lines = contract.declaration()["command_lines"]

    assert {"portrait_foot_press|{x}|{y}", "landscape_foot_wheel|{steps}|{x}|{y}"} <= set(lines)


def test_a_press_on_the_job_queue_a_funestra_draws_reaches_that_job(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_funestras_session(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "window", _MinimizedCore)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    monkeypatch.setattr(view._slideshows, "rows_at", lambda key: [_row_of(
        (str(tall), "image", "id-tall", str(tall)))] if key == "__all__::portrait" else [])
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    _press(bridge, tmp_path, "portrait_open_slideshow")
    shown = view.region_slideshow("portrait").shown
    stopped = []
    shown.set_queue([_inflight("j1", cancel=lambda: stopped.append("j1"), typical_seconds=30)])
    x, y, width, height = shown.queue_foot.pointer.where(f"{CANCEL}|j1")

    _press(bridge, tmp_path, f"portrait_foot_press|{x + width // 2}|{y + height // 2}")

    assert stopped == ["j1"]


def _stills(tmp_path, prefix, count, size):
    items = []
    for n in range(count):
        path = tmp_path / f"{prefix}-{n}.png"
        Image.new("RGB", size).save(path)
        items.append((str(path), "image", f"id-{prefix}-{n}", str(path)))
    return items


def _row_of(item) -> dict:
    """An item of ``_stills`` as the row the gallery lists it from.

    Rows and items are different things — a slideshow is built from items and armed
    with the versions read off rows — so the stubs hand over each in its own
    shape rather than one standing in for both.
    """
    return {"prompt_id": item[2], "output_files": "[]", "thumbnail_path": item[3]}


def _items_of(rows) -> list:
    return [(row["thumbnail_path"], "image", row["prompt_id"], row["thumbnail_path"])
            for row in rows]


def _funestras_playing_their_libraries(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_funestras_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    library = {"__all__::landscape": _stills(tmp_path, "library-wide", 3, (200, 100)),
               "__all__::portrait": _stills(tmp_path, "library-tall", 1, (100, 200))}
    monkeypatch.setattr(view._slideshows, "rows_at",
                        lambda key: [_row_of(item) for item in library.get(key, [])])
    monkeypatch.setattr(view._slideshows, "items_of", _items_of)
    _press(bridge, tmp_path, "portrait_open_slideshow")
    _press(bridge, tmp_path, "landscape_open_slideshow")
    for side in ("landscape", "portrait"):
        _told(tmp_path, side)
    return view


def _told(tmp_path, side):
    return consume_command_file(tmp_path / f"{side}_cmd.txt", uppercase=False)


def test_a_preview_double_click_takes_over_the_funestra_of_its_shape_for_good(
        qtbot, tmp_path, monkeypatch):
    view = _funestras_playing_their_libraries(qtbot, tmp_path, monkeypatch)
    folder = _stills(tmp_path, "scene-wide", 2, (200, 100))
    clicked = folder[1]
    monkeypatch.setattr(view, "listed_rows", lambda: [_row_of(item) for item in folder])
    monkeypatch.setattr(view, "row_for", lambda pid: next(
        (_row_of(item) for item in folder if item[2] == pid), None))
    monkeypatch.setattr(view._slideshows, "items_of", lambda rows: [
        row if isinstance(row, tuple)
        else (row["thumbnail_path"], "image", row["prompt_id"], row["thumbnail_path"])
        for row in rows])

    view._slideshows.open_on_preview((clicked[0], "image"), clicked[2])

    played = [str(item.path) for item in read_playlist(tmp_path / "landscape.tsv")]
    assert played == [clicked[0], folder[0][0]]
    told = _told(tmp_path, "landscape")
    assert [verb for verb in told if verb.startswith("SET_PACE")][-1] == \
        f"SET_PACE {DEFAULT_S}"
    hud = parse_hud((tmp_path / "origenerator_landscape_hud.json").read_text(encoding="utf-8"))
    assert hud.corner.path == clicked[0]
    assert _told(tmp_path, "portrait") == []


def test_a_double_click_over_frames_of_no_run_in_flight_leaves_the_funestras_alone(
        qtbot, tmp_path, monkeypatch):
    view = _funestras_playing_their_libraries(qtbot, tmp_path, monkeypatch)
    playing = (tmp_path / "landscape.tsv").read_text(encoding="utf-8")

    assert view._slideshows.open_on_preview(None, None) is None

    assert (tmp_path / "landscape.tsv").read_text(encoding="utf-8") == playing
    assert _told(tmp_path, "landscape") == []
    assert _told(tmp_path, "portrait") == []


def _a_run_watched_on_a_funestra(qtbot, tmp_path, monkeypatch, *, alone_in_its_folder=False,
                                 tall=False):
    """A session with its Funestras handed over, a run going in the tab in front,
    and that tab's preview double-clicked on the run's first frame."""
    def by_id(row, places):
        if row.get("status") != "completed":
            return None
        return str(tmp_path / f"{row['prompt_id']}.png"), "image"

    monkeypatch.setattr(gallery, "resolve_preview", by_id)
    monkeypatch.setattr(gcp_module, "resolve_preview", by_id)
    db = _seeded_db(tmp_path)
    if tall:
        params = json.loads(db.get_generation("orig")["params_json"])
        db.set_params_json("orig", json.dumps({**params, "width": 720, "height": 1280}))
    client = _reroll_client()
    view = GalleryView(db, client=client, fun_time=_funestras_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    view.refresh()
    _press(bridge, tmp_path, "portrait_open_slideshow")
    _press(bridge, tmp_path, "landscape_open_slideshow")
    _key, job = _running_reroll(view, PORTRAIT if tall else LANDSCAPE)
    if alone_in_its_folder:
        db.delete_generation("orig")
    view.refresh()  # the poll's rebuild, which puts the run in its folder
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    _preview_of(view).open_fullscreen()
    return client, job


def test_a_run_alone_in_its_folder_double_clicked_goes_to_the_funestra_of_its_shape(
        qtbot, tmp_path, monkeypatch):
    _a_run_watched_on_a_funestra(qtbot, tmp_path, monkeypatch, alone_in_its_folder=True,
                                 tall=True)

    shown = read_playlist(tmp_path / "portrait.tsv")[0].path
    assert shown.is_file() and shown.read_bytes() == _png_bytes()


def test_a_run_watched_on_a_funestra_is_held_there_while_it_is_made_still_moving(
        qtbot, tmp_path, monkeypatch):
    _a_run_watched_on_a_funestra(qtbot, tmp_path, monkeypatch)

    told = _told(tmp_path, "landscape")
    locks = [verb for verb in told if verb.startswith("LOCK_")]
    assert (locks[-1], "SET_PACE 0" in told) == ("LOCK_ON", False)


def test_a_run_watched_on_a_funestra_lands_there_as_its_finished_item(
        qtbot, tmp_path, monkeypatch):
    client, job = _a_run_watched_on_a_funestra(qtbot, tmp_path, monkeypatch)
    _told(tmp_path, "landscape")

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    finished = PlaylistItem(tmp_path / f"{job.prompt_id}.png")
    assert play_file(finished) in _told(tmp_path, "landscape")
    assert read_playlist(tmp_path / "landscape.tsv")[0].path == finished.path


def test_a_run_watched_on_a_funestra_lands_at_the_clip_seconds(qtbot, tmp_path, monkeypatch):
    client, job = _a_run_watched_on_a_funestra(qtbot, tmp_path, monkeypatch)
    _told(tmp_path, "landscape")

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    paces = [verb for verb in _told(tmp_path, "landscape") if verb.startswith("SET_PACE")]
    assert paces[-1] == f"SET_PACE {DEFAULT_S}"


def test_the_sessions_loop_key_reaches_the_slideshow_on_that_side(qtbot, tmp_path, monkeypatch):
    """Home and E are the session's loop keys, one per satellite; in
    origenerator mode they arrive here as the side's loop verb and step the
    slideshow's loop.  A slideshow of items no library maps has nothing to loop, so the
    press is the lock — and the next lets go, the way a lone clip's is."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_loop")
    assert slideshow.locked

    _press(bridge, tmp_path, "portrait_loop")
    assert not slideshow.locked


def test_the_maps_own_verbs_all_reach_the_slideshow(qtbot, tmp_path, monkeypatch):
    """Every press the Funestras' map posts — the two loop buttons, the expand
    mark, a map key — has an answer here, so none is dropped on the log."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    dropped = []
    monkeypatch.setattr(bridge, "_apply_side", lambda side, action, argument, line, said_at:
                        dropped.append(line) if not answer(view.region_slideshow(side), action, argument)
                        else None)

    for verb in ("portrait_seed_loop", "portrait_action_loop", "portrait_no_loop",
                 "portrait_more_seeds", "portrait_nav_right", "portrait_cycle_seed"):
        _press(bridge, tmp_path, verb)

    assert dropped == []


def test_a_rows_filter_press_is_spelled_the_other_way_round_and_still_reaches_the_slideshow(
        qtbot, tmp_path, monkeypatch):
    """The HUD posts a row's filter button as ``filter_<side>_<row>`` —
    the side in the middle — and a session hands it back verbatim."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    slideshow = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(slideshow, "slideshow_filter", asked.append)

    _press(bridge, tmp_path, "filter_portrait_red_fox")

    assert asked == ["red_fox"]


def test_a_verb_said_to_neither_side_is_dropped_on_the_log(qtbot, tmp_path, caplog):
    _view, bridge = _view_with_bridge(qtbot, tmp_path)

    _press(bridge, tmp_path, "sideways_next")

    assert "Unknown Fun Time verb dropped: sideways_next" in caplog.text


def _told_on_a_fresh_bridge(tmp_path, line: str) -> None:
    """*line* on the command file of a bridge over a gallery that has every
    answer, so a line dropped is dropped by the bridge itself."""
    session = _session(tmp_path)
    bridge = FunTimeBridge(session, MagicMock())
    session.command_file.write_text(f"{line}\n", encoding="utf-8")
    bridge._tick()


def _a_line_like(template: str, tmp_path) -> str:
    return template.format(
        file=r"C:\library\scene one.png", row="alpha", words="favorites",
        corner="lower_right", on="1", x="10", y="5", steps="-1",
        frames=str(tmp_path / "frame.bin"), input=str(tmp_path / "input.txt"))


def test_every_line_the_published_document_names_is_answered_here(qtbot, tmp_path, caplog):
    """A host sends what the document names, so a named line dropped here is a
    key that does nothing in the session -- in whichever case the host spells
    it, which the document leaves to the host."""
    document = contract.declaration()
    assert document["command_case_blind"]

    for template in document["command_lines"]:
        line = _a_line_like(template, tmp_path)
        for spelled in (line.lower(), line.upper()):
            _told_on_a_fresh_bridge(tmp_path, spelled)

    assert "dropped" not in caplog.text


def test_a_host_matches_each_line_the_document_names_by_its_published_pattern(tmp_path):
    document = contract.declaration()
    lines = [_a_line_like(template, tmp_path) for template in document["command_lines"]]

    unmatched = [spelled
                 for line, pattern in zip(lines, document["command_patterns"], strict=True)
                 for spelled in (line.lower(), line.upper())
                 if not re.fullmatch(pattern, spelled)]

    assert unmatched == []


def _said_aloud(template: str, tmp_path) -> str:
    said_at = contract.declaration()["said_at_suffix"].format(
        said_at_epoch_seconds="1761390000.250")
    return _a_line_like(template, tmp_path) + ("" if "|" in template else said_at)


def test_every_line_said_aloud_is_answered_with_when_it_was_said_on_its_end(
        qtbot, tmp_path, caplog):
    for template in contract.declaration()["command_lines"]:
        _told_on_a_fresh_bridge(tmp_path, _said_aloud(template, tmp_path))

    assert "dropped" not in caplog.text


def test_a_host_matches_each_line_said_aloud_with_its_time_by_its_published_pattern(tmp_path):
    document = contract.declaration()
    lines = [_said_aloud(template, tmp_path) for template in document["command_lines"]]

    unmatched = [line for line, pattern in zip(lines, document["command_patterns"], strict=True)
                 if not re.fullmatch(pattern, line)]

    assert unmatched == []


@pytest.mark.parametrize("line", ["sideways_next", "GO_TO|", "portrait_say:", "HAND_OVER||"])
def test_a_line_naming_nothing_here_or_carrying_nothing_where_it_must_matches_no_pattern(line):
    assert not any(re.fullmatch(pattern, line)
                   for pattern in contract.declaration()["command_patterns"])


def test_a_clip_the_session_names_lands_the_gallery_on_the_generation_it_copies(
        qtbot, tmp_path):
    """Genau locking, in the session, on a loop this app made: the gallery goes
    to that loop -- its folder, its tile, its tab -- as a lock on one of this
    app's own slideshows takes it there."""
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("i1", "a cat", 50, 1),
        _row("v7", "wan22_i2v", {"seed": 7}, "wan22_i2v_00007_.mp4")])
    view.refresh()

    _press(bridge, tmp_path, r"GO_TO|C:\library\genau\clips\wan22_i2v_00007__topaz.mp4")

    assert view.selected_prompt_ids() == ["v7"]


def test_a_clip_this_app_did_not_make_leaves_the_gallery_where_it_stands(qtbot, tmp_path):
    """Genau's folder holds the clips carved by hand as well: one of those is
    none of this app's to show."""
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("i1", "a cat", 50, 1),
        _row("v7", "wan22_i2v", {"seed": 7}, "wan22_i2v_00007_.mp4")])
    view.refresh()
    view.follow_link("i1")

    _press(bridge, tmp_path, r"GO_TO|C:\library\genau\clips\scene one 0012.mp4")

    assert view.selected_prompt_ids() == ["i1"]
    assert _the_room_was_told(tmp_path) == []


def test_a_clip_the_session_names_that_this_app_made_asks_the_room_to_show_this_app(
        qtbot, tmp_path):
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("i1", "a cat", 50, 1),
        _row("v7", "wan22_i2v", {"seed": 7}, "wan22_i2v_00007_.mp4")])
    view.refresh()

    _press(bridge, tmp_path, r"GO_TO|C:\library\videos\wan22_i2v_00007_.mp4")

    assert _the_room_was_told(tmp_path) == ["origenerator_activate"]


def test_the_session_says_where_each_sides_hud_sits(qtbot, tmp_path):
    """The keys that move a HUD are the room's, so the session keeps the
    answer and tells this app; a slideshow opened into that region later wears it."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)

    view._fun_time.command_file.write_text(
        "portrait_hud_corner|lower_right\nportrait_hud_minimized|1\n", encoding="utf-8")
    bridge._drain_commands()

    assert view.hud_place("portrait") == (HudCorner.LOWER_RIGHT, True)
    assert view.hud_place("landscape") == (HudCorner.UPPER_LEFT, False)


def _radio_clips(tmp_path, count=6):
    clips = tmp_path / "radio"
    clips.mkdir()
    for index in range(count):
        (clips / f"clip{index}.mp4").touch()
    return clips


def _view_with_funestras_and_bridge(qtbot, tmp_path):
    view = GalleryView(FakeDB([]), fun_time=_funestras_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view, radio_dir=_radio_clips(tmp_path))
    return view, bridge


def _stations_dealt(tmp_path) -> list[int]:
    return [len(read_radio(radio_file_for(tmp_path / f"{side}.tsv")))
            for side in ("portrait", "landscape")]


def test_the_moment_this_app_is_up_each_funestra_it_was_handed_is_dealt_its_radio(
        qtbot, tmp_path):
    _view, bridge = _view_with_funestras_and_bridge(qtbot, tmp_path)
    assert not radio_file_for(tmp_path / "portrait.tsv").exists()

    bridge._tick()

    assert _stations_dealt(tmp_path) == [3, 3]


def test_the_radio_is_dealt_once_however_often_this_app_says_it_is_up(qtbot, tmp_path):
    _view, bridge = _view_with_funestras_and_bridge(qtbot, tmp_path)
    bridge._tick()
    dealt = radio_file_for(tmp_path / "portrait.tsv").read_text(encoding="utf-8")
    (tmp_path / "origenerator_status.txt").unlink()  # the session opening the mode again

    for _ in range(5):
        bridge._tick()

    assert radio_file_for(tmp_path / "portrait.tsv").read_text(encoding="utf-8") == dealt


def test_an_app_handed_back_takes_its_funestras_radio_with_it(qtbot, tmp_path):
    _view, bridge = _view_with_funestras_and_bridge(qtbot, tmp_path)
    bridge._tick()

    bridge._apply(contract.RELEASE)

    assert not radio_file_for(tmp_path / "portrait.tsv").exists()
    assert not radio_file_for(tmp_path / "landscape.tsv").exists()


def test_an_app_closing_takes_its_funestras_radio_with_it(qtbot, tmp_path):
    _view, bridge = _view_with_funestras_and_bridge(qtbot, tmp_path)
    bridge._tick()

    bridge.take_the_radio_back()

    assert _stations_dealt(tmp_path) == [0, 0]
    assert not radio_file_for(tmp_path / "portrait.tsv").exists()
