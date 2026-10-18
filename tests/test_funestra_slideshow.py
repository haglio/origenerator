"""The slideshow, driving a Funestra over its channel.

What this covers is the channel between the two: the list the Funestra is handed,
the verbs a press sends it, the panel this app publishes for it, and the slide
on screen — which is the Funestra's answer, read back, not this app's own.
"""
from __future__ import annotations

import ast
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from funestra.file_channel import consume_command_file
from funestra.funestra_verbs import play_file
from funestra.hud_title import LATEST_LABEL
from funestra.playlist import PlaylistItem, read_playlist
from funestra.satellite_hud import parse_hud
from funestra.status import FunestraStatus, status_fields

from origenerator.fun_time_mode import FunestraChannel
from origenerator.funscript import funscript_path_for
from origenerator.gui import slideshow_pass
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_slideshow import FunestraSlideshow
from origenerator.gui.notice_overlay import HEARD_MARK
from origenerator.gui.slideshow_map import MapNeighbors, MapRow
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.output_places import OutputPlaces
from origenerator.slideshow import Slide, SlideshowFilters, SlideshowState, in_order
from origenerator.slideshow_buttons import answer
from tests.slideshow_support import slides_named

_ITEMS = [("one.png", "image", "id-1"), ("two.png", "image", "id-2"),
          ("three.png", "image", "id-3")]
FRAME = b"\x89PNG\r\n\x1a\n a fabricated frame"

ROOT = Path(__file__).resolve().parent.parent
DRIVERS = ("origenerator/gui/slideshow_panel.py", "origenerator/fun_time_bridge.py",
           "origenerator/gui/console.py")


def _into(said: list):
    return lambda message, *, mark: said.append(message)


def _marked_into(said: list):
    return lambda message, *, mark: said.append((mark, message))


def _channel(tmp_path: Path) -> FunestraChannel:
    return FunestraChannel(
        playlist=tmp_path / "portrait.tsv",
        command_file=tmp_path / "portrait_cmd.txt",
        status_file=tmp_path / "portrait_status.txt",
        hud_file=tmp_path / "origenerator_portrait_hud.json",
    )


def _slideshow(qtbot, tmp_path, items=_ITEMS, **fields) -> FunestraSlideshow:
    """A slideshow driving a Funestra whose files are this test's own.

    Its poll timer is stopped and :meth:`FunestraSlideshow.tick` called by hand, so a
    test says when the Funestra is next read rather than racing it.
    """
    slideshow = FunestraSlideshow(items, side="portrait", channel=_channel(tmp_path),
                      frames=FrameFiles(tmp_path / "frames"), shuffle=in_order, **fields)
    slideshow._timer.stop()
    return slideshow


def _sent(slideshow: FunestraSlideshow) -> list[str]:
    """The verbs waiting on the Funestra's command file, drained as it drains
    them — its own reader, so a spelling this app got wrong cannot pass."""
    return consume_command_file(slideshow.channel.command_file, uppercase=False)


def _says(slideshow: FunestraSlideshow, **fields) -> None:
    """The Funestra publishing what it is showing, as its status writer does."""
    _funestra_says(slideshow.channel, **fields)


def _funestra_says(channel: FunestraChannel, *, loads: int = 1, idle: bool = False,
                   **fields) -> None:
    lines = {**status_fields(FunestraStatus(**fields)), "loads": str(loads),
             "idle": "1" if idle else "0"}
    channel.status_file.write_text(
        "".join(f"{key}={value}\n" for key, value in lines.items()), encoding="utf-8")


def _slideshow_with_the_funestra_on(qtbot, tmp_path, **status) -> FunestraSlideshow:
    slideshow = _slideshow(qtbot, tmp_path)
    _says(slideshow, **status)
    slideshow.tick()
    _sent(slideshow)
    return slideshow


def _slideshow_locked_on(qtbot, tmp_path, video: str) -> FunestraSlideshow:
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video=video)
    slideshow.set_locked(True)
    _sent(slideshow)
    return slideshow


@contextmanager
def _held_open_for(path: Path, seconds: float):
    reader = path.open(encoding="utf-8")
    release = threading.Timer(seconds, reader.close)
    release.start()
    try:
        yield
    finally:
        release.join()


def _public(cls) -> set[str]:
    return {name for name in vars(cls) if not name.startswith("_") and not name.endswith("Event")}


def test_the_window_answers_only_what_a_window_has_and_the_slideshow_in_it_the_rest():
    assert _public(SlideshowView) & _public(FunestraSlideshow) == set()


def _probes_in(relative_path: str) -> list[str]:
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    names = _public(FunestraSlideshow)
    return [
        f"{relative_path}:{node.lineno} {node.func.id}(…, {node.args[1].value!r})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in ("hasattr", "getattr") and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant) and node.args[1].value in names
    ]


@pytest.mark.parametrize("driver", DRIVERS)
def test_no_driver_asks_the_slideshow_what_it_can_do_by_probing_for_it(driver):
    assert _probes_in(driver) == []


def test_a_locked_slide_is_not_taken_off_the_screen_for_what_is_being_made(qtbot, tmp_path):
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")
    slideshow.note_enhancing({"id-3": "running"})

    slideshow.lead_with_what_is_being_made()

    assert slideshow._set.current_prompt_id() == "id-1"


def test_a_request_and_the_lock_each_let_go_only_of_themselves(qtbot, tmp_path):
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")

    slideshow.pause_for_request(True, "🎤 listening…")
    slideshow.pause_for_request(False)
    assert slideshow.locked is True and "LOCK_OFF" not in _sent(slideshow)

    slideshow.pause_for_request(True, "🎤 listening…")
    slideshow.slideshow_step(1)
    assert slideshow._funestra_pace() == 0  # a step lets go of the lock, not of the request


def test_a_funestra_that_says_nothing_leaves_the_slideshow_as_it_was(qtbot, tmp_path):
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")
    slideshow.channel.status_file.unlink()

    slideshow.tick()

    assert slideshow.locked is True
    assert _sent(slideshow) == []


def test_a_file_the_funestra_would_not_open_is_stepped_past(qtbot, tmp_path):
    """A clip carries no pace of its own -- its length is its pace -- so a file the
    Funestra cannot open would be a black screen for the rest of the slideshow."""
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()

    assert _sent(slideshow) == ["NEXT"]


def test_each_file_that_would_not_open_is_stepped_past_once(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()
    slideshow.tick()

    _says(slideshow, video="two.png", loads=2, idle=True)
    slideshow.tick()

    assert _sent(slideshow) == ["NEXT", "NEXT"]


def test_a_file_that_would_not_open_is_stepped_past_even_while_locked(qtbot, tmp_path):
    """A lock replays what it holds, so a locked file that cannot play would hold
    the black screen for good; the item stays in the set, the lock comes off."""
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")

    _says(slideshow, video="one.png", locked=True, idle=True)
    slideshow.tick()

    assert _sent(slideshow) == ["LOCK_OFF", "NEXT"]


def test_a_file_that_would_not_open_waits_out_a_paused_room_before_it_is_stepped_past(
        qtbot, tmp_path):
    """A slideshow hunting through its set for something it can play is the room
    moving while it is held, so the black screen waits for the room to play on."""
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    _says(slideshow, video="one.png", paused=True, idle=True)
    slideshow.tick()
    held = _sent(slideshow)

    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()

    assert (held, _sent(slideshow)) == ([], ["NEXT"])


def test_a_slideshow_hands_the_funestra_the_pass_it_is_to_play(qtbot, tmp_path):
    """The set, in the order this slideshow plays it, is the Funestra's playlist —
    read back through the very reader the Funestra reads it with."""
    slideshow = _slideshow(qtbot, tmp_path)

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "two.png", "three.png"]


def _scripted(monkeypatch, tmp_path, *clips: str) -> dict[str, Path]:
    output = tmp_path / "output"
    monkeypatch.setattr(slideshow_pass, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    scripts = {}
    for clip in clips:
        script = funscript_path_for(clip, places=OutputPlaces.in_one_folder(output))
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("{}", encoding="utf-8")
        scripts[clip] = script
    return scripts


def test_a_clip_is_handed_over_with_the_script_the_funestra_drives_the_osr2_by(
        qtbot, tmp_path, monkeypatch):
    scripts = _scripted(monkeypatch, tmp_path, "clip.mp4")
    items = [("one.png", "image", "id-1"), ("clip.mp4", "video", "id-2"),
             ("bare.mp4", "video", "id-3")]

    slideshow = _slideshow(qtbot, tmp_path, items=items)

    handed = [item.funscript for item in read_playlist(slideshow.channel.playlist)]
    assert handed == [None, scripts["clip.mp4"], None]


def test_a_video_the_session_s_funestra_plays_is_none_on_this_app_s_own_screen(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, items=[("clip.mp4", "video", "id-1")])

    assert slideshow.video_on_screen() is None


def test_the_funestra_is_told_to_read_the_list_and_how_long_a_picture_holds(qtbot, tmp_path):
    """Two verbs make the hand-over: read this list, and hold each picture for
    the pace this app's console sets — the Funestra owning the advance from
    there, as it does for its own clips."""
    slideshow = _slideshow(qtbot, tmp_path, image_dwell_ms=6000)

    assert _sent(slideshow) == ["SET_PACE 6", "RELOAD_PLAYLIST"]


def test_the_slideshow_follows_the_funestra_onto_whatever_it_moved_to(qtbot, tmp_path):
    """The Funestra walks the list by itself — a picture's pace runs out, a clip
    ends — so which item the map lights, the star answers about and a spoken
    "this one" means is the Funestra's answer, read back."""
    slideshow = _slideshow(qtbot, tmp_path)

    _says(slideshow, video="two.png")
    slideshow.tick()

    assert slideshow.hud_prompt_id == "id-2"
    assert slideshow.hud_map().corner.prompt_id == "id-2"


def test_the_padlock_is_the_slideshows_own_lock_whatever_the_funestra_says(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.slideshow_toggle_lock()
    told = _sent(slideshow)
    _says(slideshow, video="one.png", locked=False)
    slideshow.tick()
    still_locked = slideshow.locked
    slideshow.slideshow_toggle_lock()
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert (told, still_locked, slideshow.locked) == (["LOCK_ON"], True, False)


def test_stepping_lets_go_of_a_locked_slide_first(qtbot, tmp_path):
    """Moving off a locked slide releases the lock, the way the Funestras' own
    prev/next cancel a lock — else the Funestra would repeat the next one too."""
    slideshow = _slideshow(qtbot, tmp_path)
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.slideshow_step(1)

    assert _sent(slideshow) == ["LOCK_OFF", "NEXT"]


def test_a_lock_favorites_the_item_and_asks_for_a_better_version(qtbot, tmp_path):
    """Locking is the whole gesture it is in a window: the Funestra repeats it,
    and the slideshow favorites it, asks for the better version, and hands it to the
    gallery to open."""
    asked = []
    actions = SlideshowActions(favorite=lambda pid: asked.append(("star", pid)),
                               enhance=lambda pid: asked.append(("enhance", pid)) or True,
                               lock=lambda pid: asked.append(("lock", pid)))
    slideshow = _slideshow(qtbot, tmp_path, actions=actions)

    slideshow.slideshow_toggle_lock()

    assert asked == [("star", "id-1"), ("enhance", "id-1"), ("lock", "id-1")]


def test_locking_an_item_whose_enhancement_is_waiting_still_asks_so_it_goes_first(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path,
                           actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or False))
    slideshow.note_enhancing({"id-1": "queued"})

    slideshow.slideshow_toggle_lock()

    assert asked == ["id-1"]


def test_culling_tells_the_funestra_to_drop_it_before_deleting_it(qtbot, tmp_path):
    """The Funestra is playing that very file, and Windows will not move a file a
    process still has open — so the Funestra is told to drop it before the
    generation is condemned."""
    queued_at_delete, deleted = [], []

    def delete(prompt_id):
        queued_at_delete.extend(_sent(slideshow))
        deleted.append(prompt_id)

    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(delete=delete))
    _sent(slideshow)

    slideshow.slideshow_cull()

    assert deleted == ["id-1"]
    assert queued_at_delete[:2] == ["LOCK_OFF", "TRASH"]
    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["two.png", "three.png"]  # and it is off the list


def test_the_delete_a_cull_starts_does_not_skip_a_second_item(qtbot, tmp_path):
    """The recovery bin asks every surface to let go of the files it moves; the
    Funestra is already letting go of this one, so asking again would move it on
    past the item after it as well."""
    released = []

    def delete(_prompt_id):
        slideshow.release_media(["one.png"])
        released.extend(_sent(slideshow))

    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(delete=delete))
    _says(slideshow, video="one.png")
    slideshow.tick()

    slideshow.slideshow_cull()

    assert "NEXT" not in released


def test_a_file_the_funestra_will_not_let_go_of_is_said_rather_than_raised(qtbot, tmp_path):
    """A Funestra with nothing else to move on to keeps its file open for good —
    a delete refused, said where the speaker can see it, not an error only the
    log ever hears of."""
    said = []

    def delete(_prompt_id):
        raise PermissionError("the file is in use")

    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(delete=delete),
                           say=_marked_into(said), items=_ITEMS[:1])

    slideshow.slideshow_cull()

    mark, line = said[-1]
    assert mark == "trash" and "couldn't delete" in line


def test_narrowing_hands_the_funestra_what_is_left(qtbot, tmp_path):
    """A switch is a narrowing of what the Funestra may reach, so the list it is
    playing is written again with what survives."""
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-3"}))
    _sent(slideshow)

    assert slideshow.toggle_favorites_filter() is True

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["three.png"]
    assert "RELOAD_PLAYLIST" in _sent(slideshow)


def test_narrowing_reaches_a_funestra_partway_through_reading_the_last_list(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-3"}))

    with _held_open_for(slideshow.channel.playlist, 0.1):
        assert slideshow.toggle_favorites_filter() is True

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["three.png"]


def test_the_panel_this_app_publishes_is_the_slideshows_own_band(qtbot, tmp_path):
    """The session draws the panel on the Funestra, so this app publishes the
    model for it: the slideshow's map, its title and the buttons it answers —
    and not the mode pair, which is the session's own to add."""
    slideshow = _slideshow(qtbot, tmp_path)

    model = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))

    assert model.funestra == "portrait"
    assert model.corner.path == "one.png"
    assert model.seed_count == 1     # a set with no library under it maps the slide alone
    assert [button.command for row in model.rows for button in row] == [
        "portrait_prev", "portrait_next", "portrait_lock", "portrait_trash",
        "portrait_fmode", "portrait_enhanced", "portrait_reset",
        "portrait_shuffle", "portrait_latest", "portrait_cycle_version"]


def test_a_map_click_plays_that_item_and_a_double_click_locks_it(qtbot, tmp_path):
    """The same jump a click makes on a Funestra's own map, and the same lock its
    double-click takes."""
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.show_item("three.png", lock=True)

    assert _sent(slideshow) == ["PLAY_FILE three.png", "LOCK_ON"]


def test_a_new_pace_reaches_the_funestra(qtbot, tmp_path):
    """The pace is the Funestra's to keep — it holds a picture that long and then
    ends the file, which is how a slide moves on at all."""
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.set_dwell_s(9)

    assert _sent(slideshow) == ["SET_PACE 9"]


def test_a_slideshow_that_is_over_gives_the_side_back(qtbot, tmp_path):
    """The panel goes with it, so the session draws its own again on that
    Funestra rather than leaving this app's last one up."""
    slideshow = _slideshow(qtbot, tmp_path)

    slideshow.close()

    assert slideshow.is_showing() is False
    assert slideshow.channel.hud_file.read_text(encoding="utf-8") == ""


def test_a_slideshow_that_is_over_takes_its_panel_down_though_the_funestra_is_reading_it(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    with _held_open_for(slideshow.channel.hud_file, 0.1):
        slideshow.close()

    assert slideshow.channel.hud_file.read_text(encoding="utf-8") == ""


def test_a_slideshow_on_the_funestras_hands_its_slide_over_as_it_closes(qtbot, tmp_path):
    # The same promise as the full-screen slideshow: whichever way a slideshow ends,
    # the picture it was on is the one to find in the gallery afterwards.
    slideshow = _slideshow(qtbot, tmp_path)
    handed = []
    slideshow.open_requested.connect(handed.append)
    on_screen = slideshow.state().current

    slideshow.close()

    assert slideshow.is_showing() is False
    assert handed == [on_screen]


def test_a_new_set_lands_the_funestra_on_its_slide_over_another_item_of_it(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.play(_ITEMS, start=2, shuffle=in_order, image_dwell_ms=0)

    assert _sent(slideshow) == ["SET_PACE 0", "PLAY_FILE three.png", "RELOAD_PLAYLIST"]


def test_a_new_set_does_not_reload_a_funestra_already_on_its_slide(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="three.png")

    slideshow.play(_ITEMS, start=2, shuffle=in_order, image_dwell_ms=0)

    assert _sent(slideshow) == ["SET_PACE 0", "RELOAD_PLAYLIST"]


def test_the_slideshow_names_the_generation_it_is_locked_on(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
    assert slideshow.locked_on is None

    slideshow.set_locked(True)

    assert slideshow.locked_on == "id-2"


def test_a_new_set_lets_go_of_the_lock_the_last_one_had(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.set_locked(True)
    _sent(slideshow)

    slideshow.play(_ITEMS, start=1, shuffle=in_order)

    assert _sent(slideshow)[0] == "LOCK_OFF"
    assert slideshow.locked is False


def test_a_side_reset_lands_the_funestra_on_the_top_of_its_base_set(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")

    slideshow.retune([("four.png", "image", "id-4"), ("five.png", "image", "id-5")])

    top = slideshow._set.playlist.current()
    assert _sent(slideshow)[:3] == [f"SET_PACE {slideshow.dwell_s}", f"PLAY_FILE {top.path}",
                                    "RELOAD_PLAYLIST"]
    assert slideshow.hud_prompt_id == top.prompt_id


def test_a_reset_with_no_base_set_lands_the_funestra_on_the_top_of_its_own(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")

    slideshow.reset_in_place()

    assert "PLAY_FILE one.png" in _sent(slideshow)
    assert slideshow.hud_prompt_id == "id-1"


def test_a_slideshow_picked_back_up_lands_the_funestra_where_the_last_one_left_off(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    assert slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-3"))

    assert _sent(slideshow)[:2] == [f"SET_PACE {slideshow.dwell_s}", "PLAY_FILE three.png"]


def test_a_slideshow_picked_back_up_locked_locks_the_funestra_on_its_slide(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-3", locked=True))

    sent = _sent(slideshow)
    assert sent.index("PLAY_FILE three.png") < sent.index("LOCK_ON")
    assert slideshow.locked


def test_a_lock_picked_back_up_is_the_lock_alone(qtbot, tmp_path):
    asked = []
    actions = SlideshowActions(favorite=lambda pid: asked.append(("star", pid)),
                               enhance=lambda pid: asked.append(("enhance", pid)) or True,
                               lock=lambda pid: asked.append(("lock", pid)))
    slideshow = _slideshow(qtbot, tmp_path, actions=actions)

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-2", locked=True))

    assert asked == []


_ONE_LISTED_AT_ITS_NEWEST = {"one.png": [("one.png", "image", "Enhancement 1/1"),
                                          ("one_original.png", "image", "Original")]}


def test_a_slideshow_picked_back_up_on_another_version_plays_that_version_locked(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
    slideshow.set_levels(_ONE_LISTED_AT_ITS_NEWEST)

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-1",
                                    locked=True, level_index=1))

    assert _sent(slideshow)[-2:] == ["PLAY_FILE one_original.png", "LOCK_ON"]
    assert slideshow.state().level_index == 1


def test_the_funestra_reaching_the_slide_a_slideshow_resumed_on_keeps_its_version(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
    slideshow.set_levels(_ONE_LISTED_AT_ITS_NEWEST)
    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-1", level_index=1))

    _says(slideshow, video="one.png")
    slideshow.tick()

    assert slideshow.state().level_index == 1


def test_a_slideshow_on_a_funestra_hands_it_the_filters_it_takes_up(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhanced_ids={"id-2", "id-3"}))

    slideshow.take_up(SlideshowFilters(enhanced=True))

    assert slideshow.hud_enhanced_mode
    assert [str(item.path) for item in read_playlist(slideshow.channel.playlist)] == [
        "two.png", "three.png"]


def test_what_a_slideshow_hands_over_is_the_whole_set_standing_where_the_funestra_is(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")

    assert [str(item.path) for item in slideshow.whole_set()] == ["one.png", "two.png", "three.png"]
    assert slideshow.state().current == "id-2"


def test_a_slideshow_opened_on_a_slide_lands_the_funestra_on_it(qtbot, tmp_path):
    _funestra_says(_channel(tmp_path), video="one.png")

    slideshow = _slideshow(qtbot, tmp_path, start=2)

    assert _sent(slideshow)[:2] == [f"SET_PACE {slideshow.dwell_s}", "PLAY_FILE three.png"]
    assert slideshow.hud_prompt_id == "id-3"


def test_a_file_about_to_be_deleted_is_let_go_of(qtbot, tmp_path):
    """The Funestra holds the file open, so the way to let go is to move on —
    what the gallery asks of every surface before it moves files."""
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.release_media(["one.png"])

    assert _sent(slideshow) == ["NEXT"]


def test_the_order_pair_asks_the_gallery_for_the_side_in_that_order(qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(
        reorder=lambda items, latest: asked.append((items, latest))))

    slideshow.slideshow_order(latest=True)
    slideshow.slideshow_order(latest=False)

    assert asked == [(slideshow, True), (slideshow, False)]


def test_a_reorder_lets_go_and_hands_the_funestra_the_new_list_from_its_top(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.reorder([("five.png", "image", "id-5"), ("four.png", "image", "id-4")],
                      latest=True)

    assert _sent(slideshow) == ["LOCK_OFF", f"SET_PACE {slideshow.dwell_s}",
                                "PLAY_FILE five.png", "RELOAD_PLAYLIST"]
    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["five.png", "four.png"]
    assert slideshow.hud_order_label == LATEST_LABEL


def test_a_reorder_keeping_the_slide_leaves_the_funestra_on_the_picture_it_has(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.reorder([("nine.png", "image", "id-9"), ("one.png", "image", "id-1")],
                      latest=True, keep_slide=True)

    assert _sent(slideshow) == [f"SET_PACE {slideshow.dwell_s}", "RELOAD_PLAYLIST"]
    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "nine.png"]


def test_a_reorder_of_a_slideshow_not_locked_sends_no_unlock(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")

    slideshow.reorder(_ITEMS, latest=True)

    assert _sent(slideshow)[:3] == [f"SET_PACE {slideshow.dwell_s}", "PLAY_FILE one.png",
                                    "RELOAD_PLAYLIST"]


def test_a_hosted_reset_lets_go_of_the_lock_before_handing_over_the_base_set(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.retune([("five.png", "image", "id-5")])

    assert _sent(slideshow)[0] == "LOCK_OFF"
    assert slideshow.locked is False


_LEVELS = {"one.png": [("one_enhanced.png", "image", "Enhancement 1/1"),
                       ("one.png", "image", "Original")]}


class TestVersions:
    """Stepping an item's own versions on the Funestra, the axis the shifted keys
    and the band's versions button share with a slideshow in a window."""

    def test_a_step_holds_the_funestra_and_opens_the_other_version_still(self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_levels(_LEVELS)

        slideshow.slideshow_step_version(1)

        assert _sent(slideshow) == ["SET_PACE 0", "PLAY_FILE one.png"]

    @pytest.mark.parametrize(("move", "verb"), [
        (lambda slideshow: slideshow.slideshow_step(1), "NEXT"),
        (lambda slideshow: slideshow.slideshow_step(-1), "PREV"),
        (lambda slideshow: slideshow.slideshow_cull(), "TRASH"),
        (lambda slideshow: slideshow.show_item("three.png"), "PLAY_FILE three.png"),
        (lambda slideshow: slideshow.reorder([("five.png", "image", "id-5")], latest=True),
         "PLAY_FILE five.png"),
        (lambda slideshow: slideshow.release_media(["one.png"]), "NEXT"),
    ], ids=["next", "previous", "a cull", "a click on the map", "a new order",
            "letting go of the file"])
    def test_leaving_the_versions_hands_the_funestra_its_pace_before_it_opens_the_next(
            self, qtbot, tmp_path, move, verb):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_levels(_LEVELS)
        slideshow.slideshow_step_version(1)
        _sent(slideshow)

        move(slideshow)

        sent = _sent(slideshow)
        assert sent.index(f"SET_PACE {slideshow.dwell_s}") < sent.index(verb)

    def test_a_version_landing_while_they_are_compared_holds_the_funestra_on_the_new_one(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_levels(_LEVELS)
        slideshow.slideshow_step_version(1)
        _sent(slideshow)

        slideshow.note_enhanced("id-1", "one_better.png")
        slideshow.add_levels({"one_better.png": [
            ("one_better.png", "image", "Enhancement 2/2"),
            ("one_enhanced.png", "image", "Enhancement 1/2"),
            ("one.png", "image", "Original")]})

        assert f"SET_PACE {slideshow.dwell_s}" not in _sent(slideshow)
        assert _panel(slideshow).item_note == "Enhancement 2/2"

    def test_a_videos_other_version_is_played_with_its_script(
            self, qtbot, tmp_path, monkeypatch):
        scripts = _scripted(monkeypatch, tmp_path, "clip.mp4")
        slideshow = _slideshow(qtbot, tmp_path, items=[("clip.mp4", "video", "id-1")])
        _says(slideshow, video="clip.mp4")
        slideshow.tick()
        _sent(slideshow)
        slideshow.set_levels({"clip.mp4": [("clip_upscaled.mp4", "video", "Upscale"),
                                           ("clip.mp4", "video", "Original")]})

        slideshow.slideshow_step_version(1)

        assert _sent(slideshow)[-1] == f"PLAY_FILE clip.mp4	{scripts['clip.mp4']}"

    def test_stepping_on_and_back_walks_the_versions_in_order(self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_levels(_LEVELS)

        slideshow.slideshow_step_version(1)
        _sent(slideshow)
        slideshow.slideshow_step_version(-1)

        assert _sent(slideshow) == ["PLAY_FILE one_enhanced.png"]

    def test_the_sessions_shift_left_counts_the_enhancements_down_and_shift_right_up(
            self, qtbot, tmp_path):
        """The session sends Shift+Left as cycle_version_back, and Shift+Right as
        cycle_version, which the band's versions button sends too."""
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_levels({"one.png": [("one_2.png", "image", "Enhancement 2/2"),
                                          ("one_1.png", "image", "Enhancement 1/2"),
                                          ("one.png", "image", "Original")]})

        opened = []
        for press in ("cycle_version_back", "cycle_version_back",
                      "cycle_version", "cycle_version"):
            answer(slideshow, press)
            opened += [line for line in _sent(slideshow) if line.startswith("PLAY_FILE")]

        assert opened == ["PLAY_FILE one_1.png", "PLAY_FILE one.png",
                          "PLAY_FILE one_1.png", "PLAY_FILE one_2.png"]

    def test_an_item_filed_once_is_left_alone_rather_than_stepping_the_set(
            self, qtbot, tmp_path):
        """Nothing to compare it against, and the shift was the whole point of
        the press — so it does nothing rather than walking to the neighbor."""
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
        slideshow.set_levels(_LEVELS)

        slideshow.slideshow_step_version(1)

        assert _sent(slideshow) == []

    def test_the_band_lights_its_versions_button_only_where_there_are_some(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        assert slideshow.has_other_versions is False

        slideshow.set_levels(_LEVELS)

        assert slideshow.has_other_versions is True

    def test_moving_to_another_item_starts_that_ones_versions_from_the_top(
            self, qtbot, tmp_path):
        """A step on the new item must offer its own newest version, not carry the
        place the last item was stepped to."""
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_levels({**_LEVELS,
                              "two.png": [("two_enhanced.png", "image", "Enhancement 1/1"),
                                          ("two.png", "image", "Original")]})
        slideshow.slideshow_step_version(1)
        _sent(slideshow)

        _says(slideshow, video="two.png")
        slideshow.tick()
        _sent(slideshow)
        slideshow.slideshow_step_version(1)

        assert _sent(slideshow) == ["SET_PACE 0", "PLAY_FILE two.png"]


# --- the map, and the loops along it ------------------------------------------

def _around(prompt_id):
    """A library in which the first item has one seed sibling and one other
    act down its column, and the rest have nobody."""
    if prompt_id != "id-1":
        return MapNeighbors()
    other_act = Slide("one-x.png", "image", "id-1x")
    return MapNeighbors(seeds=(Slide("one-b.png", "image", "id-1b"),),
                        column=(MapRow(other_act, "dawn"),), label="fox",
                        group=(other_act,))


def test_the_panel_maps_the_item_on_screen_against_the_library(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))

    model = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))

    assert [cell.path for cell in model.seeds] == ["one-b.png"]
    assert [(cell.path, cell.label) for cell in model.actions] == [("one-x.png", "dawn")]
    assert (model.current_action, model.seed_count, model.action_count) == ("fox", 2, 2)


def test_a_loop_hands_the_funestra_the_row_to_play_and_its_ending_hands_back_the_set(qtbot, tmp_path):
    """The row becomes the Funestra's list, the item on screen first so it keeps
    playing; the loop key ends it and the set comes back the same way."""
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around), say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop("seed")

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "one-b.png"]
    assert "RELOAD_PLAYLIST" in _sent(slideshow)
    assert said == ["Looping seeds: 2"]
    assert parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8")).active_loop == "seed"

    slideshow.slideshow_loop_cycle()          # seeds -> configs
    slideshow.slideshow_loop_cycle()          # configs -> off

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "two.png", "three.png"]
    assert said[-1] == "Loop off"


def test_a_slideshow_closed_looping_actions_reopens_looping_them_where_it_stood(qtbot, tmp_path):
    library = SlideshowActions(neighbors=_around, slides=slides_named(
        Slide("one.png", "image", "id-1"), Slide("one-x.png", "image", "id-1x")))
    closed = _slideshow(qtbot, tmp_path, actions=library)
    closed.slideshow_loop("action")
    closed.show_item("one-x.png")

    elsewhere = tmp_path / "reopened"
    elsewhere.mkdir()
    reopened = _slideshow(qtbot, elsewhere, actions=library)
    reopened.resume(closed.state())

    played = [str(item.path) for item in read_playlist(reopened.channel.playlist)]
    assert played == ["one-x.png", "one.png"]
    assert parse_hud(reopened.channel.hud_file.read_text(encoding="utf-8")).active_loop == "action"
    assert reopened.hud_map() == closed.hud_map()


def test_a_cull_that_leaves_one_picture_in_the_row_locks_it(qtbot, tmp_path):
    """A row worn down to one picture plays that picture over and over, which
    is the lock — so the cull that wore it down ends the loop and tells the
    Funestra to lock what is left.  Only the lock: none of what a pressed lock
    also does, since nobody pressed one."""
    asked, starred, opened = [], [], []
    slideshow = _slideshow(qtbot, tmp_path,
                           actions=SlideshowActions(neighbors=_around, delete=lambda prompt_id: None,
                                                    favorite=starred.append, lock=opened.append,
                                                    enhance=lambda prompt_id: asked.append(prompt_id) or True))
    slideshow.slideshow_loop("seed")                       # the row: one.png and one-b.png
    _sent(slideshow)

    slideshow.slideshow_cull()                             # weird the picture on screen

    assert "LOCK_ON" in _sent(slideshow)
    assert (slideshow.locked, slideshow.hud_map().loop) == (True, "")
    assert (asked, starred, opened) == ([], [], [])


def test_a_forward_step_in_a_row_down_to_one_picture_hands_the_set_back(qtbot, tmp_path):
    """A cull can leave the row holding only the picture on screen, and a
    Funestra stepping round a list of one plays that picture again — so the step
    ends the loop first, and what it steps into is the set coming back."""
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    slideshow.slideshow_loop("seed")                      # the row: one.png and one-b.png
    slideshow.slideshow_cull()                            # down to the one picture left
    _sent(slideshow)

    slideshow.slideshow_step(1)

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one-b.png", "two.png", "three.png"]
    assert _sent(slideshow)[-1] == "NEXT"
    assert slideshow.hud_map().loop == ""


def test_a_map_cell_the_set_never_held_is_played_by_the_one_verb_that_splices(qtbot, tmp_path):
    """PLAY_FILE jumps to a file in the list and splices in one that is not —
    which is where the pass put the cell too, so no list is handed over."""
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    _sent(slideshow)

    slideshow.show_item("one-x.png")

    assert _sent(slideshow) == ["PLAY_FILE one-x.png", "LOCK_OFF"]
    assert slideshow.hud_prompt_id == "id-1x"


def _plays(slideshow) -> list[str]:
    return [verb for verb in _sent(slideshow) if verb.startswith("PLAY_FILE")]


_NAMED_FOR = {"id-1": "Source image, alpha", "id-2": "beta", "id-3": "alpha"}


def _acts(prompt_ids):
    return {prompt_id: _NAMED_FOR.get(prompt_id, "") for prompt_id in prompt_ids}


def test_a_rows_button_narrows_the_slideshow_to_that_act_and_hands_the_funestra_what_is_left(
        qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(acts=_acts), say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_filter("alpha")

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "three.png"]
    assert _plays(slideshow) == []                       # the item on screen shows that act
    assert said == ["Filter: 'alpha' (2)"]


def test_filter_said_of_its_side_narrows_to_what_the_item_on_screen_is_named_for(
        qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(acts=_acts), say=_into(said))

    slideshow.slideshow_filter_to_the_act_on_screen()

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert (played, said) == (["one.png"], ["Filter: 'source image, alpha' (1)"])


def test_filter_said_over_an_item_named_for_no_act_says_so(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))

    slideshow.slideshow_filter_to_the_act_on_screen()

    assert said == ["No act for this one"]


def test_a_row_naming_two_acts_is_posted_with_its_spaces_as_underscores(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(acts=_acts), say=_into(said))

    slideshow.slideshow_filter("source_image,_alpha")

    assert said == ["Filter: 'source image, alpha' (1)"]
    assert parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8")).filter_query == (
        "source image, alpha")


def test_a_configuration_rows_button_plays_it_and_loops_its_seeds(qtbot, tmp_path):
    """Half the column is configurations, and their buttons mean what they
    meant before the acts joined them: go to that configuration and play its
    seeds round and round, rather than narrowing the slideshow to an act."""
    said = []
    a_configuration = Slide("one-x.png", "image", "id-1x")
    around = lambda pid: MapNeighbors(  # noqa: E731
        column=(MapRow(a_configuration, "E629425B", configuration=True),)
        if pid == "id-1" else (),
        seeds=(Slide("one-y.png", "image", "id-1y"),) if pid == "id-1x" else ())
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=around, acts=_acts),
                           say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_filter("e629425b")

    assert slideshow.hud_prompt_id == "id-1x"
    assert slideshow.hud_act_filter == ""            # a jump, not a narrowing
    assert said == ["Looping seeds: 2"]


def test_a_filter_past_the_item_on_screen_sends_the_funestra_to_what_is_left(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(acts=_acts))
    _sent(slideshow)

    slideshow.slideshow_filter("beta")

    assert _plays(slideshow) == ["PLAY_FILE two.png"]


def test_an_act_nothing_here_shows_says_so_and_moves_nothing(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(acts=_acts), say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_filter("gamma")

    assert (_sent(slideshow), said) == ([], ["Filter: no matches for 'gamma'"])


def test_clearing_the_filters_lifts_the_act_filter_with_the_other_two(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(acts=_acts))
    slideshow.slideshow_filter("beta")

    assert slideshow.clear_modes() is True

    assert slideshow.pass_size() == 3


def test_the_pass_is_as_long_as_what_the_funestra_was_handed(qtbot, tmp_path):
    assert _slideshow(qtbot, tmp_path).pass_size() == 3


def test_ending_a_loop_says_so_and_ending_none_says_nothing(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around), say=_into(said))
    slideshow.slideshow_loop("seed")

    slideshow.slideshow_loop("")
    slideshow.slideshow_loop("")

    assert said == ["Looping seeds: 2", "Loop off"]


def test_a_loop_button_for_a_row_of_one_picture_locks_it_instead(qtbot, tmp_path):
    """A row holding only the picture on screen cannot be looped, and the press
    still means "this one" — so the Funestra is told to lock it, the way its own
    loop button locks a clip whose group holds only that clip."""
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop("seed")

    assert (_sent(slideshow), said) == (["LOCK_ON"], ["Locked"])
    assert slideshow.locked is True


def test_the_loop_key_is_the_lock_where_there_is_nothing_to_loop(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop_cycle()
    slideshow.slideshow_loop_cycle()

    assert [verb for verb in _sent(slideshow) if verb.startswith("LOCK")] == ["LOCK_ON", "LOCK_OFF"]
    assert said == ["Locked", "Unlocked"]


def test_a_press_is_answered_plain_and_a_spoken_word_after_the_mic(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_marked_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop("seed")
    slideshow.note_voice_command("favorited")

    assert said == [("", "Locked"), (HEARD_MARK, "favorited")]


def test_more_seeds_hands_the_funestra_the_wider_row(qtbot, tmp_path):
    said = []
    beyond = (Slide("far.png", "image", "id-far"),)
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said), actions=SlideshowActions(
        neighbors=_around, widen=lambda pid: beyond if pid == "id-1" else ()))

    slideshow.slideshow_more_seeds()

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "one-b.png", "far.png"]
    assert said == ["More seeds"]


def test_more_seeds_with_nothing_beyond_the_row_says_so(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said), actions=SlideshowActions(neighbors=_around))
    _sent(slideshow)

    slideshow.slideshow_more_seeds()

    assert (_sent(slideshow), said) == ([], ["Widening net failed"])


def test_a_walk_along_the_map_plays_the_next_cell(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    _sent(slideshow)

    slideshow.slideshow_nav("right")

    assert _sent(slideshow) == ["PLAY_FILE one-b.png"]
    assert slideshow.hud_prompt_id == "id-1b"


def test_a_walk_off_a_locked_item_lets_go_of_it_first(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.slideshow_nav("down")

    assert _sent(slideshow) == ["LOCK_OFF", "PLAY_FILE one-x.png"]


def test_a_walk_with_nothing_that_way_says_so_and_stays(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_nav("right")

    assert (_sent(slideshow), said) == ([], ["Nothing that way"])


def test_weird_over_a_favorite_takes_its_star_and_moves_on(qtbot, tmp_path):
    """The Funestras' own "weird": a favorite loses its star and the Funestra is
    told to move on — nothing is dropped and nothing deleted."""
    unfavorited, deleted = [], []
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-1"}),
                           actions=SlideshowActions(unfavorite=unfavorited.append, delete=deleted.append))
    _sent(slideshow)

    slideshow.slideshow_cull()

    assert (unfavorited, deleted) == (["id-1"], [])
    assert _sent(slideshow) == ["LOCK_OFF", "NEXT"]
    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "two.png", "three.png"]   # still in the list


def test_entering_a_loop_lets_go_of_a_locked_item_as_a_funestra_does(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.slideshow_loop("seed")

    assert _sent(slideshow)[0] == "LOCK_OFF"
    assert slideshow.locked is False
    assert parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8")).locked is False


def test_the_loop_key_lets_go_of_a_locked_item_when_it_finds_a_row_to_loop(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.slideshow_loop_cycle()

    assert "LOCK_OFF" in _sent(slideshow)
    assert (slideshow.locked, slideshow.hud_map().loop) == (False, "seed")


def test_a_folder_handed_to_a_funestra_publishes_its_seed_loop_lit(qtbot, tmp_path):
    folder = [("one.png", "image", "id-1"), ("one-b.png", "image", "id-1b")]
    slideshow = _slideshow(qtbot, tmp_path, items=folder, actions=SlideshowActions(neighbors=_around))

    model = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))

    assert (model.active_loop, model.filter_query) == ("seed", "fox")


# --- what is being made of the item on screen ---------------------------------

def _panel(slideshow: FunestraSlideshow):
    return parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))


def test_the_panel_names_the_version_of_the_item_on_screen(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.set_levels(_LEVELS)

    assert _panel(slideshow).item_note == "Enhancement 1/1"


def test_the_panel_says_whether_a_better_version_is_being_made_or_waiting(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.note_enhancing({"id-1": "queued"})
    assert _panel(slideshow).item_note == "Enhancement queued"
    slideshow.note_enhancing({"id-1": "running"})
    assert _panel(slideshow).item_note == "Enhancing…"


def test_a_lock_that_asks_for_a_better_version_says_so_on_the_panel(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(enhance=lambda pid: True))

    slideshow.slideshow_toggle_lock()

    assert _panel(slideshow).item_note == "Enhancement queued"


def test_a_better_version_that_landed_leaves_nothing_in_flight_on_the_panel(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_enhancing({"id-1": "running"})

    slideshow.note_enhanced("id-1", "one_enhanced.png")

    assert _panel(slideshow).item_note == ""


def test_a_slideshow_opened_while_an_item_of_it_is_being_enhanced_plays_that_item_first(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhancing={"id-3": "running"}))

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["three.png", "one.png", "two.png"]


def test_a_slideshow_picked_back_up_plays_what_is_being_made_before_where_it_left_off(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhancing={"id-3": "running"}))
    _sent(slideshow)

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-2"))

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["three.png", "two.png", "one.png"]
    assert "PLAY_FILE three.png" in _sent(slideshow)


def test_a_slideshow_picked_back_up_on_a_locked_slide_stays_on_it(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhancing={"id-3": "running"}))

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-2", locked=True))

    assert slideshow.locked_on == "id-2"


def test_a_slideshow_opened_on_a_slide_and_picked_back_up_there_puts_nothing_in_front_of_it(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, start=1, hud=HudFacts(enhancing={"id-3": "running"}))

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-2"),
                     opened_on_it=True)

    assert slideshow.hud_prompt_id == "id-2"


def test_a_slideshow_opened_on_a_slide_and_picked_back_up_there_has_the_funestra_play_it_once(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, start=2)

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-3"),
                     opened_on_it=True)

    assert _sent(slideshow).count("PLAY_FILE three.png") == 1


def _being_enhanced_on_screen(qtbot, tmp_path, image_dwell_ms=4000) -> FunestraSlideshow:
    slideshow = _slideshow(qtbot, tmp_path, image_dwell_ms=image_dwell_ms,
                           hud=HudFacts(enhancing={"id-1": "running"}))
    _says(slideshow, video="one.png")
    slideshow.tick()
    return slideshow


def test_an_item_being_enhanced_is_held_for_half_the_pace_on_the_funestra(qtbot, tmp_path):
    """So the Funestra moves on from it early, and its scrubber counts that half."""
    slideshow = _being_enhanced_on_screen(qtbot, tmp_path)

    assert "HOLD_PICTURE 2" in _sent(slideshow)


def test_an_item_being_made_makes_its_move_at_the_ordinary_pace(qtbot, tmp_path):
    slideshow = _being_enhanced_on_screen(qtbot, tmp_path)

    assert [verb for verb in _sent(slideshow) if verb.startswith("SET_PACE")] == ["SET_PACE 4"]


def test_an_item_nothing_is_being_made_of_holds_for_the_whole_pace(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    _says(slideshow, video="two.png")
    slideshow.tick()

    assert not any(verb.startswith("HOLD_PICTURE") for verb in _sent(slideshow))


def test_an_item_being_made_under_a_pace_of_nought_is_held_like_any_other(qtbot, tmp_path):
    slideshow = _being_enhanced_on_screen(qtbot, tmp_path, image_dwell_ms=0)

    assert not any(verb.startswith("HOLD_PICTURE") for verb in _sent(slideshow))


def test_a_slide_a_request_is_spoken_over_stays_held_through_a_new_list(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.pause_for_request(True)

    slideshow.note_added("four.png", "image", "id-4")

    assert _paces(_sent(slideshow))[-1] == "SET_PACE 0"


def _following_a_run(qtbot, tmp_path) -> FunestraSlideshow:
    slideshow = _slideshow(qtbot, tmp_path, image_dwell_ms=4000)
    slideshow.note_generating("id-run", FRAME)
    slideshow.follow_what_is_being_made()
    _says(slideshow, video=str(read_playlist(slideshow.channel.playlist)[0].path))
    slideshow.tick()
    return slideshow


def _slideshow_following_a_run(qtbot, tmp_path) -> FunestraSlideshow:
    slideshow = _following_a_run(qtbot, tmp_path)
    _sent(slideshow)
    return slideshow


def test_a_run_the_slideshow_follows_is_held_on_the_funestra_while_it_is_made(qtbot, tmp_path):
    slideshow = _following_a_run(qtbot, tmp_path)

    assert _paces(_sent(slideshow))[-1] == "SET_PACE 0"


def _paces(sent: list[str]) -> list[str]:
    return [verb for verb in sent if verb.startswith("SET_PACE")]


def test_a_run_the_slideshow_follows_that_stops_leaves_it_paging_at_its_pace(qtbot, tmp_path):
    slideshow = _slideshow_following_a_run(qtbot, tmp_path)

    slideshow.note_in_flight(set())

    assert _paces(_sent(slideshow))[-1] == f"SET_PACE {slideshow.dwell_s}"


def test_a_run_the_slideshow_follows_lets_go_once_the_funestra_is_stepped_off_it(
        qtbot, tmp_path):
    slideshow = _slideshow_following_a_run(qtbot, tmp_path)

    slideshow.slideshow_step(1)
    _says(slideshow, video="one.png")
    slideshow.tick()

    assert _paces(_sent(slideshow)) == [f"SET_PACE {slideshow.dwell_s}"]


def test_a_slideshow_told_to_lead_with_what_is_being_made_sends_the_funestra_there(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    slideshow.note_enhancing({"id-3": "running"})
    _sent(slideshow)

    slideshow.lead_with_what_is_being_made()

    assert "PLAY_FILE three.png" in _sent(slideshow)


def test_an_item_whose_enhancement_starts_while_it_is_up_keeps_its_whole_time(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.note_enhancing({"id-1": "running"})
    slideshow.tick()

    assert not any(verb.startswith("HOLD_PICTURE") for verb in _sent(slideshow))


def test_a_picture_enhanced_during_the_slideshow_steps_its_versions_on_the_funestra(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_enhanced("id-1", "one_enhanced.png")
    _says(slideshow, video="one_enhanced.png")
    slideshow.tick()
    _sent(slideshow)

    slideshow.add_levels({"one_enhanced.png": [("one_enhanced.png", "image", "Enhancement 1/1"),
                                               ("one.png", "image", "Original")]})
    slideshow.slideshow_step_version(1)

    assert _sent(slideshow) == ["SET_PACE 0", "PLAY_FILE one.png"]


def test_a_run_being_made_joins_the_funestras_list_on_its_first_frame(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.note_generating("id-run", FRAME)

    played = [item.path for item in read_playlist(slideshow.channel.playlist)]
    assert [str(path) for path in played[:1] + played[2:]] == ["one.png", "two.png",
                                                              "three.png"]
    assert played[1].read_bytes() == FRAME
    assert "RELOAD_PLAYLIST" in _sent(slideshow)


def test_the_funestra_is_sent_to_a_run_being_made_as_its_first_frame(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_generating("id-run", FRAME)
    _sent(slideshow)

    slideshow.lead_with_what_is_being_made()

    first_frame = read_playlist(slideshow.channel.playlist)[0].path
    assert first_frame.read_bytes() == FRAME
    assert play_file(PlaylistItem(first_frame)) in _sent(slideshow)


def _frame_shown(sent: list[str]) -> bytes | None:
    """What the last SHOW_FRAME among *sent* has the Funestra paint, read off
    the file it names."""
    shown = [line.removeprefix("SHOW_FRAME ") for line in sent
             if line.startswith("SHOW_FRAME ")]
    return Path(shown[-1]).read_bytes() if shown else None


def test_a_funestra_that_reaches_a_run_being_made_is_told_to_show_its_frame(qtbot,
                                                                          tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_generating("id-run", FRAME)
    first_frame = read_playlist(slideshow.channel.playlist)[1].path
    _sent(slideshow)

    _says(slideshow, video=str(first_frame))
    slideshow.tick()

    assert slideshow.hud_prompt_id == "id-run"
    assert _frame_shown(_sent(slideshow)) == FRAME


def _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path) -> FunestraSlideshow:
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_generating("id-run", FRAME)
    _says(slideshow, video=str(read_playlist(slideshow.channel.playlist)[1].path))
    slideshow.tick()
    _sent(slideshow)
    return slideshow


def test_a_newer_frame_of_the_run_on_the_funestra_goes_to_it_at_once(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path)

    slideshow.note_generating("id-run", FRAME + b" one step further")

    assert _frame_shown(_sent(slideshow)) == FRAME + b" one step further"


def test_a_run_that_lands_is_its_file_on_the_funestra_from_then_on(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path)
    first_frame = read_playlist(slideshow.channel.playlist)[1].path

    slideshow.note_added("run.png", "image", "id-run")

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["run.png", "two.png", "three.png", "one.png"]
    assert play_file(PlaylistItem(Path("run.png"))) in _sent(slideshow)
    assert not first_frame.exists()


def test_a_run_that_stops_being_made_leaves_the_funestras_list(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path)
    first_frame = read_playlist(slideshow.channel.playlist)[1].path

    slideshow.note_in_flight(set())

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["two.png", "three.png", "one.png"]
    assert play_file(PlaylistItem(Path("two.png"))) in _sent(slideshow)
    assert not first_frame.exists()


def test_a_slideshow_left_with_nothing_once_its_run_stops_is_over(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, items=[("one.png", "image", "id-1")])
    slideshow.note_generating("id-run", FRAME)
    slideshow.slideshow_cull()

    slideshow.note_in_flight(set())

    assert slideshow.is_showing() is False


def test_a_slideshow_that_closes_takes_its_frames_with_it(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path)

    slideshow.close()

    assert list((tmp_path / "frames").iterdir()) == []


def test_a_picture_being_enhanced_on_the_funestra_shows_the_enhancement_coming_in(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.note_enhancing({"id-1": "running"}, {"id-1": FRAME})

    assert _frame_shown(_sent(slideshow)) == FRAME


def test_a_better_version_landing_on_the_funestras_picture_goes_up_on_its_move(qtbot,
                                                                          tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_enhancing({"id-1": "running"}, {"id-1": FRAME})
    _sent(slideshow)

    slideshow.note_enhanced("id-1", "one_enhanced.png")
    landing = _sent(slideshow)
    slideshow.note_enhancing({}, {})

    assert landing[0] == "SHOW_FRAME one_enhanced.png"
    assert "RELOAD_PLAYLIST" in landing[1:]
    assert _sent(slideshow) == []


def test_an_enhancement_that_stops_takes_its_frame_off_the_funestra(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_enhancing({"id-1": "running"}, {"id-1": FRAME})
    _sent(slideshow)

    slideshow.note_enhancing({}, {})

    assert _sent(slideshow) == ["CLEAR_FRAME"]


def test_a_run_culled_from_the_funestra_does_not_come_back_on_its_next_frame(qtbot,
                                                                          tmp_path):
    slideshow = _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path)
    slideshow.slideshow_cull()

    slideshow.note_generating("id-run", FRAME + b" one step further")

    assert not slideshow.holds("id-run")
    assert list((tmp_path / "frames").iterdir()) == []


def test_a_run_that_lands_after_the_funestra_moved_on_is_the_funestras_next_item(qtbot,
                                                                             tmp_path):
    slideshow = _slideshow_with_the_funestra_on_a_run(qtbot, tmp_path)
    _says(slideshow, video="two.png")
    slideshow.tick()

    slideshow.note_added("run.png", "image", "id-run")

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played[:2] == ["two.png", "run.png"]


def _row_only(prompt_id):
    """A library holding one folder's row and nothing made of it, so the loop
    key's stop after the seeds is off."""
    return (MapNeighbors(seeds=(Slide("one-b.png", "image", "id-1b"),), label="fox")
            if prompt_id == "id-1" else MapNeighbors())


def test_taking_the_loop_off_a_folder_on_a_funestra_asks_for_the_regions_library(
        qtbot, tmp_path):
    said, widened = [], []
    folder = [("one.png", "image", "id-1"), ("one-b.png", "image", "id-1b")]
    slideshow = _slideshow(qtbot, tmp_path, items=folder, say=_into(said), actions=SlideshowActions(
        neighbors=_row_only, browse_all=lambda s: widened.append(s) or True))

    slideshow.slideshow_loop("")

    assert (widened, said) == ([slideshow], ["Loop off"])


def test_the_loop_key_off_a_folder_on_a_funestra_leaves_it_in_one_press(qtbot, tmp_path):
    said, widened = [], []
    folder = [("one.png", "image", "id-1"), ("one-b.png", "image", "id-1b")]
    slideshow = _slideshow(qtbot, tmp_path, items=folder, say=_into(said), actions=SlideshowActions(
        neighbors=_row_only, browse_all=lambda s: widened.append(s) or True))

    slideshow.slideshow_loop_cycle()

    assert (widened, said) == ([slideshow], ["Loop off"])


FACE = ((0.4, 0.1, 0.6, 0.3),)
_PLACED = {"one.png": [("one.png", "image", "Enhance 1", FACE), ("one-base.png", "image", "Original")]}


def test_a_picture_goes_to_the_funestra_with_the_places_its_fixes_found(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    slideshow.set_levels(_PLACED)

    handed = {str(item.path): item.points_of_interest
              for item in read_playlist(slideshow.channel.playlist)}
    assert handed == {"one.png": FACE, "two.png": (), "three.png": ()}


def test_versions_that_bring_no_places_leave_the_pass_where_it_was(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.set_levels(_LEVELS)

    assert "RELOAD_PLAYLIST" not in _sent(slideshow)


def test_an_older_version_stepped_to_goes_with_its_own_places(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.set_levels({"one.png": [("one.png", "image", "Enhance 2", FACE),
                                      ("one-v1.png", "image", "Enhance 1", ((0.0, 0.0, 0.5, 0.5),))]})
    _sent(slideshow)

    slideshow.slideshow_step_version(1)

    assert _sent(slideshow) == ["SET_PACE 0", "PLAY_FILE one-v1.png\t\t0,0,0.5,0.5"]
