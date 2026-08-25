"""The hosted app's file channels: Fun Time's verbs in, occupancy out.

Fun Time speaks to its satellite players through a command file, a paused
flag and a status file; a hosted Origenerator answers the same idioms so the
session's hotkeys reach the region shows and its choreography can see them.
"""

from PIL import Image

from origenerator.fun_time_mode import FunTimeSession, Rect
from origenerator.gui.fun_time_bridge import FunTimeBridge
from origenerator.gui.gallery_view import GalleryView

from tests.test_gallery_view import FakeDB


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


def _view_with_bridge(qtbot, tmp_path):
    view = GalleryView(FakeDB([]), fun_time=_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    return view, bridge


def _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path, count=3):
    still = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(still)
    items = [(str(still), "image", f"id{n}", str(still)) for n in range(count)]
    monkeypatch.setattr(view, "_slideshow_rows", lambda: [object()])
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(items))
    monkeypatch.setattr(view, "_slideshow_subject", lambda: "a folder")
    view._start_slideshow()
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


def test_lock_verb_holds_the_slide(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_LOCK\n", encoding="utf-8")
    bridge._tick()

    assert show.locked


def test_reset_verb_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    """The reset on the shared control band, spoken to a show: the hold
    releases and the top of the set comes back."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    show._playlist.jump_to(2)
    show._toggle_lock()
    assert show.locked

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_RESET\n", encoding="utf-8")
    bridge._tick()

    assert not show.locked
    assert show._playlist.index == 0


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
    from origenerator.gui.gallery_tree import STARRED_KEY

    view, bridge = _view_with_bridge(qtbot, tmp_path)
    played = []
    monkeypatch.setattr(view, "_play_shelf_aloud", played.append)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "LANDSCAPE_SAY:favorites\n", encoding="utf-8")
    bridge._tick()

    assert [(c.shelf_key, c.side) for c in played] == [(STARRED_KEY, "landscape")]


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


def test_close_shows_clears_both_regions(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("CLOSE_SHOWS\n", encoding="utf-8")
    bridge._tick()

    assert not show.isVisible()
    assert view.region_show("portrait") is None


def test_the_paused_flag_freezes_and_resumes_an_open_show(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    assert show._timer.isActive()  # an image slide dwells on its timer

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    assert not show._timer.isActive()

    (tmp_path / "origenerator_paused.txt").write_text("0", encoding="utf-8")
    bridge._tick()
    assert show._timer.isActive()


def test_omnipause_stops_the_gallerys_own_moving_pictures(qtbot, tmp_path, monkeypatch):
    """Every video tile loops a little clip of itself and the generate tabs
    play the real thing, so a paused room with the gallery in it was a wall of
    clips still going.  OmniPause stops the room, not only its shows — the
    looping previews app-wide, wherever they are drawn, and the tabs' videos
    through the tabs."""
    import origenerator.gui.gallery_view as gallery_view_module
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    tiles, tabs = [], []
    monkeypatch.setattr(gallery_view_module, "set_previews_paused", tiles.append)
    monkeypatch.setattr(view._info_tabs, "set_previews_paused", tabs.append)

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    assert tiles == [True] and tabs == [True]

    (tmp_path / "origenerator_paused.txt").write_text("0", encoding="utf-8")
    bridge._tick()
    assert tiles == [True, False] and tabs == [True, False]


def test_status_reports_which_regions_are_occupied(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    bridge._tick()
    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert "portrait_active=0" in text
    assert "landscape_active=0" in text

    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    bridge._tick()
    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert "portrait_active=1" in text
    assert "tall.png" in text  # the current item's path rides along
    assert "landscape_active=0" in text

    show.close()
    bridge._tick()
    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert "portrait_active=0" in text


def test_a_show_opened_mid_pause_opens_frozen(qtbot, tmp_path, monkeypatch):
    """The room being OmniPaused must hold a show the user opens DURING the
    pause too — the flag edged onto already-open shows once, so a slideshow
    started mid-pause played while everything else in the session stood."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()

    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    assert not show._timer.isActive()  # no dwell armed: it opened frozen


def test_a_step_while_paused_lands_on_a_slide_that_holds(qtbot, tmp_path, monkeypatch):
    """Stepping a frozen show moves it to a new slide, but the new slide must
    arrive holding — re-arming the dwell was the show quietly unpausing
    itself while the rest of the room stayed frozen."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    before = show._playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()

    assert show._playlist.index == (before + 1) % 3  # the step still lands
    assert not show._timer.isActive()                # but the slide holds


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
    monkeypatch.setattr(view, "_begin_request",
                        lambda target, spoken, side=None: begun.append((spoken.text, side)))

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:request no feet\n", encoding="utf-8")
    bridge._tick()
    assert not begun  # still being said — the show holds rather than acting

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
    monkeypatch.setattr(view, "_play_shelf_aloud", played.append)
    monkeypatch.setattr(view, "_begin_request", lambda *a, **kw: None)

    (tmp_path / "origenerator_cmd.txt").write_text(
        "PORTRAIT_SAY:request no feet\nPORTRAIT_SAY:favorites\nPORTRAIT_SAY:over\n",
        encoding="utf-8")
    bridge._tick()

    assert played == []
