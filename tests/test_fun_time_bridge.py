"""The hosted app's file channels: Fun Time's verbs in, occupancy out.

Fun Time speaks to its satellite players through a command file, a paused
flag and a status file; a hosted Origenerator answers the same idioms so the
session's hotkeys reach the region shows and its choreography can see them.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PIL import Image
from player_core.file_channel import consume_command_file
from player_core.playlist import read_playlist
from player_core.satellite_hud import parse_hud

from origenerator import fun_time_mode as contract
from origenerator.fun_time_bridge import FunTimeBridge
from origenerator.fun_time_mode import FunTimeSession, PlayerChannel, Rect
from origenerator.gui import omnipause, show_director
from origenerator.gui.gallery_tree import FAVORITES_KEY
from origenerator.gui.gallery_view import GalleryView
from origenerator.show_buttons import answer
from tests.test_gallery_view import FakeDB, _enhanced_image, _image, _row


def _will_move_on(view) -> bool:
    """Whether the show pages on by itself when the item on screen runs out.

    The engine holds a picture for the pace and ends it the way it ends a
    finished clip, so there is no clock of the view's own to ask: what decides
    is the same three things that decided whether one was armed -- the room is
    not frozen, the slide is not locked, and the pace is not nought."""
    return (not view._paused and not view._playlist.locked_or_paused()
            and bool(view._dwell_s))


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
    """The fixture's rows as a show's items — a tuple passed through, a row
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
    still = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(still)
    items = [(str(still), "image", f"id{n}", str(still)) for n in range(count)]
    monkeypatch.setattr(view, "rows_to_play",
                        lambda: [{"prompt_id": item[2]} for item in items])
    monkeypatch.setattr(view._shows, "items_of", lambda rows: list(items))
    monkeypatch.setattr(view, "slideshow_subject", lambda: "a folder")
    view._shows.start()
    show = view.region_show("portrait")
    qtbot.addWidget(show)
    return show


def test_side_verbs_drive_the_show_holding_that_region(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    before = show._playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()

    assert show._playlist.index == (before + 1) % 3


def test_a_verb_for_an_empty_region_is_dropped(qtbot, tmp_path):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_cmd.txt").write_text("LANDSCAPE_TRASH\n", encoding="utf-8")

    bridge._tick()  # nothing holds the landscape region

    # Dropped, not queued: the verb is taken off the channel like any other, and
    # nothing was opened to answer it with.
    assert not (tmp_path / "origenerator_cmd.txt").exists()
    assert view.region_show("landscape") is None


def test_lock_verb_locks_the_slide(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_LOCK\n", encoding="utf-8")
    bridge._tick()

    assert show.locked


def test_the_spoken_lock_and_unlock_each_leave_the_slide_the_way_they_name(
        qtbot, tmp_path, monkeypatch):
    """Said twice, "portrait lock" stays locked where the key's flip would let
    go: the session sends the words as the state they ask for."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    held = []

    for line in ("portrait_lock_on", "portrait_lock_on", "portrait_lock_off",
                 "portrait_lock_off"):
        _press(bridge, tmp_path, line)
        held.append(show.locked)

    assert held == [True, True, False, False]


def test_reset_verb_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    """The reset on the shared control band, spoken to a show: the lock
    releases and the top of the set comes back."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    show._playlist.jump_to(2)
    show._flip_lock()
    assert show.locked

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_RESET\n", encoding="utf-8")
    bridge._tick()

    assert not show.locked
    assert show._playlist.index == 0


def test_the_order_verbs_play_the_side_newest_first_or_shuffled(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    still = str(tmp_path / "tall.png")
    library = {key: [(still, "image", f"{key}-{n}", still) for n in range(3)]
               for key in ("__recents__::portrait", "__all__::portrait")}
    monkeypatch.setattr(view._shows, "rows_at",
                        lambda key: [_row_of(item) for item in library.get(key, [])])
    monkeypatch.setattr(view._shows, "items_of", _items_of)
    orders = []

    for verb in ("PORTRAIT_LATEST", "PORTRAIT_SHUFFLE"):
        (tmp_path / "origenerator_cmd.txt").write_text(f"{verb}\n", encoding="utf-8")
        bridge._tick()
        orders.append((show.hud_order_label, show._playlist.current()[2].split("-")[0]))

    assert orders == [("Latest", "__recents__::portrait"),
                      ("Shuffle", "__all__::portrait")]


def test_a_spoken_phrase_from_the_session_runs_here(qtbot, tmp_path, monkeypatch):
    """The session owns the room's microphone, so it hears "landscape
    favorites" and posts the WORDS on this channel — matched here, against this
    app's own vocabulary, because only this app knows what its shelves are."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    spoken = []
    monkeypatch.setattr(view, "run_spoken_command", spoken.append)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "LANDSCAPE_SAY:favorites\nPORTRAIT_SAY:fix teeth\n", encoding="utf-8")
    bridge._tick()

    assert spoken == ["landscape favorites", "portrait fix teeth"]


def test_a_spoken_phrase_is_matched_by_this_apps_own_vocabulary(qtbot, tmp_path, monkeypatch):
    """End to end from the words: the phrase the session heard becomes the
    command this app would have matched had it heard it itself."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    played = []
    monkeypatch.setattr(view._shows, "play_shelf", played.append)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "LANDSCAPE_SAY:favorites\n", encoding="utf-8")
    bridge._tick()

    assert [(c.shelf_key, c.side) for c in played] == [(FAVORITES_KEY, "landscape")]


def test_open_shows_fills_both_regions(qtbot, tmp_path, monkeypatch):
    """Entering the mode opens it PLAYING, the way entering player mode leaves
    two players playing — two empty rectangles asked the user to start the mode
    they had just asked for."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    filled = []
    monkeypatch.setattr(view, "fill_the_regions", lambda: filled.append(True))

    (tmp_path / "origenerator_cmd.txt").write_text("OPEN_SHOWS\n", encoding="utf-8")
    bridge._tick()

    assert filled == [True]


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
    monkeypatch.setattr(view, "set_session_paused", paused.append)

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    (tmp_path / "origenerator_cmd.txt").write_text("RELEASE\nOPEN_SHOWS\n", encoding="utf-8")
    monkeypatch.setattr(view, "fill_the_regions", lambda: paused.append("filled"))
    bridge._tick()

    assert paused == []
    assert not (tmp_path / "origenerator_status.txt").exists()


def test_close_shows_clears_both_regions(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("CLOSE_SHOWS\n", encoding="utf-8")
    bridge._tick()

    assert not show.isVisible()
    assert view.region_show("portrait") is None


def _fill_both_regions(qtbot, view, monkeypatch, tmp_path, portrait, landscape):
    """Both regions on their base state, each playing the ids named for it —
    what OPEN_SHOWS puts up, and the arrangement one switch has to move.

    The ids are the fabricated rows' own, so the show can tell which of its
    items carry an enhancement; the items above carry ids no row has.
    """
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    library = {
        "__all__::portrait": [(str(tall), "image", pid, str(tall)) for pid in portrait],
        "__all__::landscape": [(str(wide), "image", pid, str(wide)) for pid in landscape],
    }
    # The library's own row under the fabricated still, so whether a picture
    # carries an enhancement is read where the app reads it.
    monkeypatch.setattr(view._shows, "rows_at", lambda key: [
        {**(view.row_for(item[2]) or {}), **_row_of(item)}
        for item in library.get(key, [])])
    monkeypatch.setattr(view._shows, "items_of", _items_of)
    view.fill_the_regions()
    shows = [view.region_show(side) for side in ("portrait", "landscape")]
    for show in shows:
        qtbot.addWidget(show)
    return shows


def _press_filter_enhanced(bridge, tmp_path):
    (tmp_path / "origenerator_cmd.txt").write_text("FILTER_ENHANCED\n", encoding="utf-8")
    bridge._tick()


def test_filter_enhanced_narrows_both_regions_and_widens_them_again(
        qtbot, tmp_path, monkeypatch):
    """The session's console carries the enhanced-only switch a show's own HUD
    carries, so a press there has to reach the shows here — answered nowhere, it
    left the console lit over regions still playing all of them."""
    view, bridge = _view_with_bridge(qtbot, tmp_path, rows=[
        _image("p1", "a cat", 50, 1), _enhanced_image("p2", "a cat", 50, 2),
        _image("l1", "a boat", 40, 3), _enhanced_image("l2", "a boat", 40, 4)])
    portrait, landscape = _fill_both_regions(
        qtbot, view, monkeypatch, tmp_path, ["p1", "p2"], ["l1", "l2"])

    _press_filter_enhanced(bridge, tmp_path)

    assert [show.hud_enhanced_mode for show in (portrait, landscape)] == [True, True]
    # Each region down to the one enhanced picture it was playing.
    assert [show.pass_size() for show in (portrait, landscape)] == [1, 1]

    _press_filter_enhanced(bridge, tmp_path)

    assert [show.hud_enhanced_mode for show in (portrait, landscape)] == [False, False]
    assert [show.pass_size() for show in (portrait, landscape)] == [2, 2]


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

    assert [show.hud_enhanced_mode for show in (portrait, landscape)] == [False, False]


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

    assert [show.hud_enhanced_mode for show in (portrait, landscape)] == [True, False]
    assert [show.pass_size() for show in (portrait, landscape)] == [1, 2]


def test_filter_enhanced_with_no_show_up_is_dropped(qtbot, tmp_path):
    """Nothing to narrow and nothing armed for later: the verb comes off the
    channel like any other and the mode is left as it was."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)

    _press_filter_enhanced(bridge, tmp_path)

    assert not (tmp_path / "origenerator_cmd.txt").exists()
    assert view.region_show("portrait") is None
    assert view.region_show("landscape") is None


def test_the_paused_flag_freezes_and_resumes_an_open_show(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    assert _will_move_on(show)  # an image slide dwells on its timer

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    assert not _will_move_on(show)

    (tmp_path / "origenerator_paused.txt").write_text("0", encoding="utf-8")
    bridge._tick()
    assert _will_move_on(show)


def test_omnipause_stops_the_gallerys_own_moving_pictures(qtbot, tmp_path):
    """Every video tile loops a little clip of itself and the generate tabs
    play the real thing, so a paused room with the gallery in it was a wall of
    clips still going. OmniPause stops the room, not only its shows, and one
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


def test_a_show_opened_mid_pause_opens_frozen(qtbot, tmp_path, monkeypatch):
    """The room being OmniPaused must hold a show the user opens DURING the
    pause too — the flag edged onto already-open shows once, so a slideshow
    started mid-pause played while everything else in the session stood."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()

    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    assert not _will_move_on(show)  # no dwell armed: it opened frozen


def test_a_step_while_paused_lands_on_a_slide_that_stays_frozen(qtbot, tmp_path, monkeypatch):
    """Stepping a frozen show moves it to a new slide, but the new slide must
    arrive frozen — re-arming the dwell was the show quietly unpausing
    itself while the rest of the room stayed frozen."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    before = show._playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()

    assert show._playlist.index == (before + 1) % 3  # the step still lands
    assert not _will_move_on(show)                # but the slide stays frozen


def test_a_spoken_request_from_the_session_is_collected_here(qtbot, tmp_path, monkeypatch):
    """The one spoken input with no phrase to match: the words between
    "request" and "over" are the speaker's own, so the session forwards each
    utterance verbatim and this app's own dictation assembles them — the same
    one its mic feeds, since the two never listen at once.

    Fabricated request wording, like every fixture here.
    """
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    begun = []
    monkeypatch.setattr(view._voice, "_begin_request",
                        lambda target, spoken, side=None: begun.append((spoken.text, side)))

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:request no feet\n", encoding="utf-8")
    bridge._tick()
    assert not begun  # still being said — the show pauses rather than acting

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:over\n", encoding="utf-8")
    bridge._tick()

    # The side is the region it was said to, not the first word of the request.
    assert begun == [("no feet", "portrait")]
    assert show is view.region_show("portrait")


def test_the_words_of_a_request_are_not_read_as_commands(qtbot, tmp_path, monkeypatch):
    """While one is open the dictation swallows what it hears — half a sentence
    must not fire a command because two of its words happened to be one."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    played = []
    monkeypatch.setattr(view._shows, "play_shelf", played.append)
    monkeypatch.setattr(view._voice, "_begin_request", lambda *a, **kw: None)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:request no feet\nPORTRAIT_SAY:favorites\nPORTRAIT_SAY:over\n",
        encoding="utf-8")
    bridge._tick()

    assert played == []


def _press(bridge, tmp_path, line: str) -> None:
    """A press the session routed back here, as a player's panel posted it."""
    (tmp_path / "origenerator_cmd.txt").write_text(f"{line}\n", encoding="utf-8")
    bridge._tick()


def test_a_players_filter_presses_reach_the_show_on_that_side(qtbot, tmp_path, monkeypatch):
    """A session hands a player's presses back verbatim, spelled the way the
    panel posted them — so the show's own two switches answer them here."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    monkeypatch.setattr(view._shows, "_favorite_prompt_ids", lambda: {"id1"})
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_fmode")

    assert show.hud_favorites_filter is True
    assert show.pass_size() == 1


def test_a_thumbnail_press_carries_its_path_through_the_colon_in_it(qtbot, tmp_path, monkeypatch):
    """A path rides after the "|", and a Windows path has a colon of its own —
    which must not be read as the start of a spoken phrase."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    jumps = []
    monkeypatch.setattr(show, "show_item", lambda path, *, lock=False: jumps.append((path, lock)))

    _press(bridge, tmp_path, r"portrait_lock_video|C:\fixtures\scene one.png")

    assert jumps == [(r"C:\fixtures\scene one.png", True)]


def test_a_press_no_show_answers_is_dropped_on_the_log(qtbot, tmp_path, monkeypatch, caplog):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_wrong_action")

    assert "portrait_wrong_action" in caplog.text
    assert not (tmp_path / "origenerator_cmd.txt").exists()


def _players_session(tmp_path):
    def channel(side):
        return PlayerChannel(
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
        portrait_player=channel("portrait"), landscape_player=channel("landscape"),
    )


def test_a_session_that_hands_over_its_players_gets_both_sides_on_them(
        qtbot, tmp_path, monkeypatch):
    """Entering the mode with the players handed over: each player is given the
    list of its own side's shape, and no window of this app's opens at all."""
    def no_window(*args, **kwargs):
        raise AssertionError("a window of this app's opened over a region")

    monkeypatch.setattr(show_director, "SlideshowView", no_window)
    view = GalleryView(FakeDB([]), fun_time=_players_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    library = {"__all__::portrait": [(str(tall), "image", "id-tall", str(tall))],
               "__all__::landscape": [(str(wide), "image", "id-wide", str(wide))]}
    monkeypatch.setattr(view._shows, "rows_at",
                        lambda key: [_row_of(item) for item in library.get(key, [])])
    monkeypatch.setattr(view._shows, "items_of", _items_of)

    _press(bridge, tmp_path, "OPEN_SHOWS")

    assert [str(item.path) for item in read_playlist(tmp_path / "portrait.tsv")] == [str(tall)]
    assert [str(item.path) for item in read_playlist(tmp_path / "landscape.tsv")] == [str(wide)]
    assert view.region_show("portrait").is_showing()


def _stills(tmp_path, prefix, count, size):
    items = []
    for n in range(count):
        path = tmp_path / f"{prefix}-{n}.png"
        Image.new("RGB", size).save(path)
        items.append((str(path), "image", f"id-{prefix}-{n}", str(path)))
    return items


def _row_of(item) -> dict:
    """An item of ``_stills`` as the row the gallery lists it from.

    Rows and items are different things — a show is built from items and armed
    with the versions read off rows — so the stubs hand over each in its own
    shape rather than one standing in for both.
    """
    return {"prompt_id": item[2], "output_files": "[]", "thumbnail_path": item[3]}


def _items_of(rows) -> list:
    return [(row["thumbnail_path"], "image", row["prompt_id"], row["thumbnail_path"])
            for row in rows]


def _players_playing_their_libraries(qtbot, tmp_path, monkeypatch):
    view = GalleryView(FakeDB([]), fun_time=_players_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    library = {"__all__::landscape": _stills(tmp_path, "library-wide", 3, (200, 100)),
               "__all__::portrait": _stills(tmp_path, "library-tall", 1, (100, 200))}
    monkeypatch.setattr(view._shows, "rows_at",
                        lambda key: [_row_of(item) for item in library.get(key, [])])
    monkeypatch.setattr(view._shows, "items_of", _items_of)
    _press(bridge, tmp_path, "OPEN_SHOWS")
    for side in ("landscape", "portrait"):
        _told(tmp_path, side)
    return view


def _told(tmp_path, side):
    return consume_command_file(tmp_path / f"{side}_cmd.txt", uppercase=False)


def test_a_preview_double_click_takes_over_the_player_of_its_shape_for_good(
        qtbot, tmp_path, monkeypatch):
    view = _players_playing_their_libraries(qtbot, tmp_path, monkeypatch)
    folder = _stills(tmp_path, "scene-wide", 2, (200, 100))
    clicked = folder[1]
    monkeypatch.setattr(view, "visible_prompt_ids", lambda: [item[2] for item in folder])
    monkeypatch.setattr(view, "row_for", lambda pid: next(
        (_row_of(item) for item in folder if item[2] == pid), None))
    monkeypatch.setattr(view, "selected_prompt_id", lambda: clicked[2])
    monkeypatch.setattr(view._shows, "items_of", lambda rows: [
        row if isinstance(row, tuple)
        else (row["thumbnail_path"], "image", row["prompt_id"], row["thumbnail_path"])
        for row in rows])

    view._shows.open_on_preview((clicked[0], "image"), None)

    played = [str(item.path) for item in read_playlist(tmp_path / "landscape.tsv")]
    assert played == [clicked[0], folder[0][0]]
    told = _told(tmp_path, "landscape")
    assert [verb for verb in told if verb.startswith("SET_PACE")][-1] == "SET_PACE 0"
    panel = parse_hud((tmp_path / "origenerator_landscape_hud.json").read_text(encoding="utf-8"))
    assert panel.corner.path == clicked[0]
    assert _told(tmp_path, "portrait") == []


def test_a_double_click_over_a_run_still_being_made_leaves_the_players_alone(
        qtbot, tmp_path, monkeypatch):
    view = _players_playing_their_libraries(qtbot, tmp_path, monkeypatch)
    playing = (tmp_path / "landscape.tsv").read_text(encoding="utf-8")

    assert view._shows.open_on_preview(None, b"a frame of the run") is None

    assert (tmp_path / "landscape.tsv").read_text(encoding="utf-8") == playing
    assert _told(tmp_path, "landscape") == []
    assert _told(tmp_path, "portrait") == []


def test_the_sessions_loop_key_reaches_the_show_on_that_side(qtbot, tmp_path, monkeypatch):
    """Home and E are the session's loop keys, one per satellite; in
    origenerator mode they arrive here as the side's loop verb and step the
    show's loop.  A show of items no library maps has nothing to loop, so the
    press is the lock — and the next lets go, the way a lone clip's is."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    _press(bridge, tmp_path, "portrait_loop")
    assert show.locked

    _press(bridge, tmp_path, "portrait_loop")
    assert not show.locked


def test_the_maps_own_verbs_all_reach_the_show(qtbot, tmp_path, monkeypatch):
    """Every press the players' map posts — the two loop buttons, the expand
    mark, a map key — has an answer here, so none is dropped on the log."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    dropped = []
    monkeypatch.setattr(bridge, "_apply_side", lambda side, action, argument, line:
                        dropped.append(line) if not answer(view.region_show(side), action, argument)
                        else None)

    for verb in ("portrait_seed_loop", "portrait_action_loop", "portrait_no_loop",
                 "portrait_more_seeds", "portrait_nav_right", "portrait_cycle_seed"):
        _press(bridge, tmp_path, verb)

    assert dropped == []


def test_a_rows_filter_press_is_spelled_the_other_way_round_and_still_reaches_the_show(
        qtbot, tmp_path, monkeypatch):
    """The panel posts a row's filter button as ``filter_<side>_<row>`` —
    the side in the middle — and a session hands it back verbatim."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(show, "show_filter", asked.append)

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


def test_every_line_the_published_document_names_is_answered_here(qtbot, tmp_path, caplog):
    """A host sends what the document names, so a named line dropped here is a
    key that does nothing in the session -- in whichever case the host spells
    it, which the document leaves to the host."""
    document = contract.declaration()
    assert document["command_case_blind"]

    for template in document["command_lines"]:
        line = template.format(file=r"C:\library\scene one.png", row="alpha", words="favorites")
        for spelled in (line.lower(), line.upper()):
            _told_on_a_fresh_bridge(tmp_path, spelled)

    assert "dropped" not in caplog.text


def test_a_clip_the_session_names_lands_the_gallery_on_the_generation_it_copies(
        qtbot, tmp_path):
    """Genau locking, in the session, on a loop this app made: the gallery goes
    to that loop -- its folder, its tile, its tab -- as a lock on one of this
    app's own shows takes it there."""
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
