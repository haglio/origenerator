from __future__ import annotations

import ast
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from funestra.file_channel import consume_command_file
from funestra.funestra_verbs import play_file, set_speed
from funestra.hud_title import LATEST_LABEL
from funestra.playback_rate import NORMAL_RATE
from funestra.playlist import PlaylistItem, read_playlist
from funestra.satellite_hud import parse_hud
from funestra.status import FunestraStatus, status_fields

from origenerator import osr2_driver
from origenerator.fun_time_mode import FunestraChannel
from origenerator.funscript import funscript_path_for, synthesize_actions, write_funscript
from origenerator.gui import slideshow_pass
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_slideshow import FunestraSlideshow, Hosting, Playing, Seat
from origenerator.gui.hud_nav_map import NavMapNeighbors, NavMapRow
from origenerator.gui.hud_queue import OPEN
from origenerator.gui.message import HEARD_MARK
from origenerator.gui.region_openings import RegionOpening
from origenerator.gui.slideshow_pace import DEFAULT_S, SlideshowPace
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.one_look import one_look
from origenerator.output_places import OutputPlaces
from origenerator.slideshow import Slide, SlideshowFilters, SlideshowState, in_order
from origenerator.slideshow_buttons import answer
from tests.slideshow_support import slides_named, stop_the_poll_to_tick_by_hand
from tests.test_slideshow_hud import _inflight

_ITEMS = [("one.png", "image", "id-1"), ("two.png", "image", "id-2"),
          ("three.png", "image", "id-3")]
FRAME = b"\x89PNG\r\n\x1a\n a fabricated frame"

ROOT = Path(__file__).resolve().parent.parent
DRIVERS = ("origenerator/gui/slideshow_hud.py", "origenerator/fun_time_bridge.py",
           "origenerator/gui/osr2_controls_state.py")


def _into(said: list):
    def say(message, *, mark):
        assert isinstance(mark, str)
        said.append(message)

    return say


def _marked_into(said: list):
    return lambda message, *, mark: said.append((mark, message))


def _channel(tmp_path: Path) -> FunestraChannel:
    return FunestraChannel(
        playlist=tmp_path / "portrait.tsv",
        command_file=tmp_path / "portrait_cmd.txt",
        status_file=tmp_path / "portrait_status.txt",
        hud_file=tmp_path / "origenerator_portrait_hud.json",
    )


def _seat(tmp_path) -> Seat:
    return Seat("portrait", _channel(tmp_path), FrameFiles(tmp_path / "frames"))


_NO_HOSTING = Hosting()


def _slideshow(qtbot, tmp_path, items=_ITEMS, *, say=None, hosting=_NO_HOSTING,
               **playing) -> FunestraSlideshow:
    slideshow = FunestraSlideshow(Playing(items, shuffle=in_order, **playing), _seat(tmp_path),
                                  replace(hosting, say=say or hosting.say))
    stop_the_poll_to_tick_by_hand(slideshow)
    return slideshow


def _sent(slideshow: FunestraSlideshow) -> list[str]:
    return consume_command_file(slideshow.channel.command_file, uppercase=False)


def _says(slideshow: FunestraSlideshow, **fields) -> None:
    _funestra_says(slideshow.channel, **fields)


def _funestra_says(channel: FunestraChannel, *, loads: int = 1, idle: bool = False,
                   has_funscript: bool = False, showing: str | None = None, **fields) -> None:
    lines = {**status_fields(FunestraStatus(**fields)), "loads": str(loads),
             "idle": "1" if idle else "0", "has_funscript": "1" if has_funscript else "0",
             "showing": fields.get("video", "") if showing is None else showing}
    channel.status_file.write_text(
        "".join(f"{key}={value}\n" for key, value in lines.items()), encoding="utf-8")


def _recording_the_lock_into(asked: list) -> SlideshowActions:
    return SlideshowActions(favorite=lambda pid: asked.append(("star", pid)),
                            enhance=lambda pid: asked.append(("enhance", pid)) or True,
                            lock=lambda pid: asked.append(("lock", pid)))


def _the_whole_lock_on(prompt_id: str) -> list[tuple[str, str]]:
    return [("star", prompt_id), ("enhance", prompt_id), ("lock", prompt_id)]


def _lists_handed_to_a_funestra(monkeypatch) -> list[int]:
    written = []
    write = FunestraChannel.write_playlist
    monkeypatch.setattr(FunestraChannel, "write_playlist",
                        lambda channel, items: written.append(len(items)) or write(channel, items))
    return written


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
    assert slideshow.locked is True
    assert "LOCK_OFF" not in _sent(slideshow)

    slideshow.pause_for_request(True, "🎤 listening…")
    _sent(slideshow)
    slideshow.slideshow_step(1)
    assert (slideshow.locked, "LOCK_OFF" in _sent(slideshow)) == (False, False)


def test_a_funestra_that_says_nothing_leaves_the_slideshow_as_it_was(qtbot, tmp_path):
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")
    slideshow.channel.status_file.unlink()

    slideshow.tick()

    assert slideshow.locked is True
    assert _sent(slideshow) == []


def test_a_file_the_funestra_would_not_open_is_stepped_past(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()

    assert _sent(slideshow) == ["NEXT"], (
        "a video carries no pace of its own, its length is its pace, so a file the Funestra "
        "cannot open would be a black screen for the rest of the slideshow")


def test_each_file_that_would_not_open_is_stepped_past_once(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()
    slideshow.tick()

    _says(slideshow, video="two.png", loads=2, idle=True)
    slideshow.tick()

    assert _sent(slideshow) == ["NEXT", "NEXT"]


def test_a_file_that_would_not_open_is_stepped_past_even_while_locked(qtbot, tmp_path):
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")

    _says(slideshow, video="one.png", locked=True, idle=True)
    slideshow.tick()

    assert _sent(slideshow) == ["LOCK_OFF", "NEXT"], (
        "a lock replays what it holds, so a locked file that cannot play would hold the black "
        "screen for good: the item stays in the set and the lock comes off")


def test_a_file_that_would_not_open_waits_out_a_paused_room_before_it_is_stepped_past(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    _says(slideshow, video="one.png", paused=True, idle=True)
    slideshow.tick()
    held = _sent(slideshow)

    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()

    assert (held, _sent(slideshow)) == ([], ["NEXT"]), (
        "a slideshow hunting through its set for something it can play is the room moving while "
        "it is held")


def test_a_slideshow_hands_the_funestra_the_pass_it_is_to_play(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "two.png", "three.png"]


def _scripted(monkeypatch, tmp_path, *videos: str) -> dict[str, Path]:
    output = tmp_path / "output"
    monkeypatch.setattr(slideshow_pass, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    scripts = {}
    for video in videos:
        script = funscript_path_for(video, places=OutputPlaces.in_one_folder(output))
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("{}", encoding="utf-8")
        scripts[video] = script
    return scripts


def test_a_clip_is_handed_over_with_the_script_the_funestra_drives_the_osr2_by(
        qtbot, tmp_path, monkeypatch):
    scripts = _scripted(monkeypatch, tmp_path, "clip.mp4")
    items = [("one.png", "image", "id-1"), ("clip.mp4", "video", "id-2"),
             ("bare.mp4", "video", "id-3")]

    slideshow = _slideshow(qtbot, tmp_path, items=items)

    handed = [item.funscript for item in read_playlist(slideshow.channel.playlist)]
    assert handed == [None, scripts["clip.mp4"], None]


def test_a_slideshow_opened_in_one_look_finds_its_videos_scripts_by_listing_their_folders(
        qtbot, tmp_path, monkeypatch):
    scripts = _scripted(monkeypatch, tmp_path, "clip.mp4")
    items = [("clip.mp4", "video", "id-1"), ("bare.mp4", "video", "id-2")]
    is_file = Path.is_file

    def refused(path):
        if tmp_path in path.parents:
            pytest.fail(f"asked after {path.name} alone")
        return is_file(path)

    with monkeypatch.context() as asked, one_look():
        asked.setattr(Path, "is_file", refused)
        slideshow = _slideshow(qtbot, tmp_path, items=items)

    handed = [item.funscript for item in read_playlist(slideshow.channel.playlist)]
    assert handed == [scripts["clip.mp4"], None]


def test_a_video_the_session_s_funestra_plays_is_none_on_this_app_s_own_screen(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, items=[("clip.mp4", "video", "id-1")])

    assert slideshow.video_on_screen() is None


def test_the_osr2_follows_nothing_on_a_session_s_funestra(qtbot, tmp_path, monkeypatch):
    places = OutputPlaces.in_one_folder(tmp_path / "output")
    monkeypatch.setattr(osr2_driver, "OUTPUT_PLACES", places)
    script = funscript_path_for("clip.mp4", places=places)
    script.parent.mkdir(parents=True)
    write_funscript(script, synthesize_actions(2.0, hz=1.0))
    slideshow = _slideshow(qtbot, tmp_path, items=[("clip.mp4", "video", "id-1")])

    assert slideshow.osr2_drive_target() is None, (
        "on a session's Funestra the OSR2 is the Main Funestra's, so this app's switch drives nothing")


def test_a_pause_of_the_room_sends_a_session_s_funestra_nothing(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.set_paused(True)

    assert _sent(slideshow) == [], (
        "the session pauses its own Funestras, so a slideshow on one of them leaves the pause "
        "to the session")


def test_the_funestra_is_told_how_long_an_image_holds_that_nothing_holds_it_and_to_read_the_list(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hosting=Hosting(pace=SlideshowPace(seconds=6)))

    assert _sent(slideshow) == ["SET_PACE 6", "LOCK_OFF", "RELOAD_PLAYLIST"]


def test_the_slideshow_follows_the_funestra_onto_whatever_it_moved_to(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    _says(slideshow, video="two.png")
    slideshow.tick()

    assert slideshow.hud_prompt_id == "id-2"
    assert slideshow.hud_map().corner.prompt_id == "id-2"


def test_a_word_said_at_no_known_time_is_about_the_slide_on_screen(qtbot, tmp_path):
    now = [10.0]
    slideshow = _slideshow(qtbot, tmp_path, hosting=Hosting(clock=lambda: now[0]))
    _says(slideshow, video="one.png")
    slideshow.tick()
    now[0] = 12.0
    _says(slideshow, video="two.png")
    slideshow.tick()
    _sent(slideshow)

    assert slideshow.back_to_what_was_said_over(None) == "id-2"
    assert _sent(slideshow) == []


def test_a_word_said_over_a_slide_since_left_puts_that_slide_back_on_screen(qtbot, tmp_path):
    now = [10.0]
    slideshow = _slideshow(qtbot, tmp_path, hosting=Hosting(clock=lambda: now[0]))
    _says(slideshow, video="one.png")
    slideshow.tick()
    now[0] = 12.0
    _says(slideshow, video="two.png")
    slideshow.tick()
    _sent(slideshow)

    assert slideshow.back_to_what_was_said_over(10.5) == "id-1"
    assert _sent(slideshow) == ["PLAY_FILE one.png"]
    assert slideshow.back_to_what_was_said_over(10.5) == "id-1"
    assert _sent(slideshow) == []


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
    slideshow = _slideshow(qtbot, tmp_path)
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)

    slideshow.slideshow_step(1)

    assert _sent(slideshow) == ["LOCK_OFF", "NEXT"], (
        "the way the Funestras' own previous and next cancel a lock: still locked, the Funestra "
        "would repeat the next one too")


def test_a_lock_favorites_the_item_and_asks_for_a_better_version(qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))

    slideshow.slideshow_toggle_lock()
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert asked == _the_whole_lock_on("id-1")


def test_a_slideshow_opened_locked_neither_favorites_nor_enhances(qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, start=0, locked=True,
                           actions=_recording_the_lock_into(asked))

    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert (slideshow.locked, "LOCK_ON" in _sent(slideshow), asked) == (True, True, [])


def test_a_lock_the_funestra_took_after_moving_on_gives_the_item_it_locked_the_whole_lock(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    _says(slideshow, video="one.png")
    slideshow.tick()

    slideshow.set_locked(True)
    _says(slideshow, video="two.png", locked=True)
    slideshow.tick()
    slideshow.tick()

    assert asked == _the_whole_lock_on("id-2")


def test_a_lock_asked_for_after_the_funestra_said_it_locked_gets_the_whole_lock_at_once_and_once(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    _says(slideshow, video="two.png", locked=True)
    slideshow.tick()

    first = slideshow.set_locked(True)
    given_at_once = list(asked)
    again = slideshow.set_locked(True)
    slideshow.tick()

    assert (first, again) == (True, False)
    assert given_at_once == asked == _the_whole_lock_on("id-2")


def test_a_lock_asked_for_twice_before_the_funestra_said_it_locked_is_given_once(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))

    first, again = slideshow.set_locked(True), slideshow.set_locked(True)
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()
    slideshow.tick()

    assert (first, again) == (True, False)
    assert asked == _the_whole_lock_on("id-1")


def test_a_lock_pressed_while_a_request_holds_the_slide_gets_the_whole_lock_at_once(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    slideshow.pause_for_request(True)
    _says(slideshow, video="two.png", locked=True)
    slideshow.tick()
    _sent(slideshow)

    slideshow.set_locked(True)

    assert (_sent(slideshow), asked) == ([], _the_whole_lock_on("id-2"))


def test_a_lock_let_go_of_and_pressed_again_gets_the_whole_lock_again(qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    slideshow.set_locked(True)
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()
    slideshow.set_locked(False)
    _says(slideshow, video="one.png", locked=False)
    slideshow.tick()
    _sent(slideshow)

    asked_again = slideshow.set_locked(True)
    sent = _sent(slideshow)
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert (asked_again, sent) == (True, ["LOCK_ON"])
    assert asked == _the_whole_lock_on("id-1") * 2


def test_a_step_off_a_lock_the_funestra_has_not_said_it_took_takes_the_lock_back(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    _says(slideshow, video="one.png")
    slideshow.tick()
    slideshow.set_locked(True)
    slideshow.tick()
    _sent(slideshow)

    slideshow.slideshow_step(1)
    sent = _sent(slideshow)
    _says(slideshow, video="two.png", locked=True)
    slideshow.tick()

    assert sent == ["LOCK_OFF", "NEXT"]
    assert asked == [], (
        "the Funestra says two.png is locked, as it would had the lock gone with the step")


def test_locking_an_item_whose_enhancement_is_waiting_still_asks_so_it_goes_first(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path,
                           actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or False))
    slideshow.note_enhancing({"id-1": "queued"})

    slideshow.slideshow_toggle_lock()
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert asked == ["id-1"]


def test_culling_tells_the_funestra_to_drop_it_before_deleting_it(qtbot, tmp_path):
    queued_at_delete, deleted = [], []

    def delete(prompt_id):
        queued_at_delete.extend(_sent(slideshow))
        deleted.append(prompt_id)

    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(delete=delete))
    _sent(slideshow)

    slideshow.slideshow_cull()

    assert deleted == ["id-1"]
    assert queued_at_delete[:1] == ["TRASH"], (
        "the Funestra is playing the condemned file and holds it open, so it is told to drop"
        " it before the generation is deleted")
    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["two.png", "three.png"]


def test_the_delete_a_cull_starts_does_not_skip_a_second_item(qtbot, tmp_path):
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
    said = []

    def delete(_prompt_id):
        raise PermissionError("the file is in use")

    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(delete=delete),
                           say=_marked_into(said), items=_ITEMS[:1])

    slideshow.slideshow_cull()

    mark, line = said[-1]
    assert mark == "trash"
    assert "couldn't delete" in line


def test_narrowing_hands_the_funestra_what_is_left(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-3"}))
    _sent(slideshow)

    assert slideshow.toggle_favorites_filter() is True

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["three.png"]
    assert "RELOAD_PLAYLIST" in _sent(slideshow)


def test_an_item_favorited_from_the_slideshow_is_one_f_mode_keeps(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path,
                           actions=SlideshowActions(favorite=lambda prompt_id: None))
    on_screen = slideshow._set.current_prompt_id()

    assert slideshow.favorite() is True
    slideshow.toggle_favorites_filter()

    assert [slide.prompt_id for slide in slideshow._set.playlist.items] == [on_screen], (
        "the star readout and F-mode follow a favorite made here")


def test_narrowing_reaches_a_funestra_partway_through_reading_the_last_list(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-3"}))

    with _held_open_for(slideshow.channel.playlist, 0.1):
        assert slideshow.toggle_favorites_filter() is True

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["three.png"]


def test_the_hud_this_app_publishes_is_the_slideshows_own_band(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    model = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))

    assert model.funestra == "portrait"
    assert model.corner.path == "one.png"
    assert model.seed_count == 1, (
        "a set with no library under it maps the slide alone")
    assert [[button.command for button in row] for row in model.rows] == [
        ["portrait_prev", "portrait_nudge_prev", "portrait_nudge_next", "portrait_next",
         "portrait_funscript_jump", "portrait_lock", "portrait_trash", "portrait_fmode",
         "portrait_enhanced", "portrait_reset", "portrait_shuffle", "portrait_latest",
         "portrait_cycle_version"],
        ["", "portrait_clip_seconds_down", "", "portrait_clip_seconds_up",
         "", "portrait_speed_down", "", "portrait_speed_up"]], (
        "the session draws the HUD on the Funestra, so this app publishes the model for it, and "
        "not the mode pair, which is the session's own to add")


def _band_button(slideshow, name: str):
    model = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))
    return next(button for row in model.rows for button in row
                if button.command == f"portrait_{name}")


def test_the_ten_second_steps_and_skip_ahead_follow_what_the_funestra_says_is_on_screen(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.mp4",
                                                duration_ms=30_000, has_funscript=True)
    slideshow.transport.set_has_osr2(True)
    assert [_band_button(slideshow, name).dim
            for name in ("nudge_prev", "nudge_next", "funscript_jump")] == [False, False, False]

    _says(slideshow, video="one.png", image=True)
    slideshow.tick()

    assert [_band_button(slideshow, name).dim
            for name in ("nudge_prev", "nudge_next", "funscript_jump")] == [True, True, True]
    assert _band_button(slideshow, "funscript_jump").tooltip.endswith(
        "(this slide has no funscript)")


def test_skip_ahead_is_faded_until_the_session_says_this_funestra_has_the_osr2(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.mp4",
                                                duration_ms=30_000, has_funscript=True)
    assert _band_button(slideshow, "funscript_jump").dim

    slideshow.transport.set_has_osr2(True)

    assert not _band_button(slideshow, "funscript_jump").dim


def test_the_ten_second_steps_and_the_skips_reach_the_funestra_as_its_own_verbs(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.mp4")

    for action in ("nudge_prev", "nudge_next", "funscript_jump", "next_funscripted"):
        assert answer(slideshow, action), action

    assert _sent(slideshow) == ["SEEK_BACK", "SEEK_FWD", "JUMP_TO_FUNSCRIPT", "NEXT_FUNSCRIPTED"]


def test_reset_is_faded_while_the_slideshow_is_at_its_defaults(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    assert _band_button(slideshow, "reset").dim

    slideshow.set_locked(True)

    assert not _band_button(slideshow, "reset").dim


def test_reset_is_offered_under_original_only_and_turns_it_off(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhanced_ids={"id-2"}))
    slideshow.show_originals_only()

    assert not _band_button(slideshow, "reset").dim
    assert answer(slideshow, "reset")

    assert (slideshow.hud_originals_mode, slideshow.pass_size()) == (False, 3)


def test_reset_is_offered_while_the_funestra_plays_off_the_normal_speed(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.mp4")
    assert _band_button(slideshow, "reset").dim

    _says(slideshow, video="one.mp4", speed=1.5)
    slideshow.tick()

    assert not _band_button(slideshow, "reset").dim


@pytest.mark.parametrize("actions", [
    pytest.param(SlideshowActions(), id="standalone"),
    pytest.param(SlideshowActions(reset=lambda slideshow: None), id="in a session"),
])
def test_a_reset_puts_the_funestras_speed_back_to_normal(qtbot, tmp_path, actions):
    slideshow = _slideshow(qtbot, tmp_path, actions=actions)
    _says(slideshow, video="one.mp4", speed=1.5)
    slideshow.tick()
    _sent(slideshow)

    assert answer(slideshow, "reset")

    assert set_speed(NORMAL_RATE) in _sent(slideshow)


def test_a_slideshow_opening_on_a_sessions_funestra_has_its_whole_hud_out_before_its_list(
        qtbot, tmp_path, monkeypatch):
    out_when_the_list_went: list = []
    hand_the_list_over = FunestraChannel.write_playlist

    def write_playlist(channel, items):
        out_when_the_list_went.append(
            parse_hud(channel.hud_file.read_text(encoding="utf-8"))
            if channel.hud_file.exists() else None)
        hand_the_list_over(channel, items)

    monkeypatch.setattr(FunestraChannel, "write_playlist", write_playlist)

    _slideshow(qtbot, tmp_path, versions=_VERSIONS,
               actions=SlideshowActions(queue_now=lambda: ([_inflight("j1")], 0)))

    hud = out_when_the_list_went[0]
    in_stages = (
        "the session draws whatever HUD is out when its Funestra takes the list, so a HUD that "
        "came after the list, or filled in after it, was a Satellite switching to Origenerator "
        "mode in stages")
    assert hud is not None, in_stages
    assert f"{OPEN}|j1" in [button.command for _rect, button in hud.foot.targets], in_stages
    assert not next(button for row in hud.rows for button in row
                    if button.command == "portrait_cycle_version").dim


class _Core:
    def __init__(self, *, minimized: bool) -> None:
        self._minimized = minimized

    def isVisible(self) -> bool:
        return True

    def isMinimized(self) -> bool:
        return self._minimized


def _published_foot(slideshow):
    return parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8")).foot


def _published_with_core(qtbot, tmp_path, *, minimized: bool):
    tmp_path.mkdir(exist_ok=True)
    core = _Core(minimized=minimized)
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(core_window=lambda: core))
    slideshow.shown.set_queue([_inflight("j1")], 0)
    return _published_foot(slideshow)


def _pressed_on(foot) -> list[str]:
    return [button.command for _rect, button in foot.targets]


def test_a_slideshow_on_a_sessions_funestra_hangs_the_job_queue_while_core_is_hidden(
        qtbot, tmp_path):
    foot = _published_with_core(qtbot, tmp_path, minimized=True)

    assert Path(foot.file).exists()
    assert f"{OPEN}|j1" in _pressed_on(foot)


def test_a_slideshow_on_a_sessions_funestra_keeps_the_job_queues_room_empty_while_core_shows(
        qtbot, tmp_path):
    shown = _published_with_core(qtbot, tmp_path / "hidden", minimized=True)
    blank = _published_with_core(qtbot, tmp_path / "shown", minimized=False)

    assert _pressed_on(blank) == []
    assert (blank.width, blank.height) == (shown.width, shown.height)


def test_a_double_click_on_the_map_gives_that_item_the_lock_buttons_whole_lock(qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    _sent(slideshow)

    slideshow.show_item("three.png", lock=True)
    sent = _sent(slideshow)
    _says(slideshow, video="three.png", locked=True)
    slideshow.tick()

    assert sent == ["PLAY_FILE three.png", "LOCK_ON"]
    assert asked == _the_whole_lock_on("id-3")


def test_a_double_click_on_the_map_moves_a_lock_held_on_another_item_onto_that_one(
        qtbot, tmp_path):
    asked = []
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))
    slideshow.slideshow_toggle_lock()
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()
    _sent(slideshow)

    slideshow.show_item("three.png", lock=True)
    sent = _sent(slideshow)
    _says(slideshow, video="three.png", locked=True)
    slideshow.tick()

    assert sent == ["LOCK_OFF", "PLAY_FILE three.png", "LOCK_ON"]
    assert asked == _the_whole_lock_on("id-1") + _the_whole_lock_on("id-3")


def test_a_slide_shown_locked_plays_and_locks_and_neither_stars_nor_enhances(qtbot, tmp_path):
    favorited, asked = [], []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(
        favorite=favorited.append, enhance=lambda prompt_id: asked.append(prompt_id) or True))
    _sent(slideshow)

    slideshow.show_locked("three.png")

    assert _sent(slideshow) == ["PLAY_FILE three.png", "LOCK_ON"]
    assert (favorited, asked) == ([], [])


def test_a_new_pace_reaches_the_funestra(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.step_dwell(1)

    assert _sent(slideshow) == [f"SET_PACE {DEFAULT_S + 1}"], (
        "the pace is the Funestra's to keep: it holds an image that long and then ends the file, "
        "which is how a slide moves on at all")


def test_a_new_pace_is_the_clip_seconds_the_satellites_hud_shows_at_once(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    slideshow.step_dwell(2)

    published = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))
    row = next(row for row in published.rows
               if any(button.command == "portrait_clip_seconds_up" for button in row))
    assert f"{DEFAULT_S + 2}s" in [button.icon for button in row]


def test_a_slideshow_that_is_over_gives_the_side_back(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    slideshow.close()

    assert slideshow.is_showing() is False
    assert slideshow.channel.hud_file.read_text(encoding="utf-8") == ""


def test_a_slideshow_that_is_over_takes_its_hud_down_though_the_funestra_is_reading_it(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    with _held_open_for(slideshow.channel.hud_file, 0.1):
        slideshow.close()

    assert slideshow.channel.hud_file.read_text(encoding="utf-8") == ""


def test_a_slideshow_on_the_funestras_hands_its_slide_over_as_it_closes(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    handed = []
    slideshow.open_requested.connect(handed.append)
    on_screen = slideshow.state().current

    slideshow.close()

    assert slideshow.is_showing() is False
    assert handed == [on_screen]


def test_a_new_set_lands_the_funestra_on_its_slide_over_another_item_of_it(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.play(Playing(_ITEMS, start=2, shuffle=in_order))

    assert _sent(slideshow) == ["SET_PACE 4", "PLAY_FILE three.png", "RELOAD_PLAYLIST"]


def test_a_new_set_does_not_reload_a_funestra_already_on_its_slide(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="three.png")

    slideshow.play(Playing(_ITEMS, start=2, shuffle=in_order))

    assert _sent(slideshow) == ["SET_PACE 4", "RELOAD_PLAYLIST"]


def test_the_slideshow_names_the_generation_it_is_locked_on(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
    assert slideshow.locked_on is None

    slideshow.set_locked(True)

    assert slideshow.locked_on == "id-2"


def test_a_new_set_lets_go_of_the_lock_the_last_one_had(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.set_locked(True)
    _sent(slideshow)

    slideshow.play(Playing(_ITEMS, start=1, shuffle=in_order))

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
    slideshow = _slideshow(qtbot, tmp_path, actions=_recording_the_lock_into(asked))

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-2", locked=True))
    _says(slideshow, video="two.png", locked=True)
    slideshow.tick()

    assert asked == []


_ONE_LISTED_AT_ITS_NEWEST = {"one.png": [("one.png", "image", "Enhancement 1/1"),
                                          ("one_original.png", "image", "Original")]}


def test_a_slideshow_picked_back_up_on_another_version_plays_that_version_locked(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
    slideshow.set_versions(_ONE_LISTED_AT_ITS_NEWEST)

    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-1",
                                    locked=True, version_index=1))

    sent = _sent(slideshow)
    assert ("NEXT_VERSION one.png|one_original.png" in sent, _locks(sent)[-1]) == (True, "LOCK_ON")
    _says(slideshow, video="one.png", showing="one_original.png")
    slideshow.tick()
    assert slideshow.state().version_index == 1


def test_the_funestra_reaching_the_slide_a_slideshow_resumed_on_keeps_its_version(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
    slideshow.set_versions(_ONE_LISTED_AT_ITS_NEWEST)
    slideshow.resume(SlideshowState(order=("id-1", "id-2", "id-3"), current="id-1", version_index=1))

    _says(slideshow, video="one.png", showing="one_original.png")
    slideshow.tick()

    assert slideshow.state().version_index == 1


def test_a_slideshow_on_a_funestra_hands_it_the_filters_it_takes_up(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhanced_ids={"id-2", "id-3"}))

    slideshow.take_up(SlideshowFilters(enhanced=True))

    assert slideshow.hud_enhanced_mode
    assert [str(item.path) for item in read_playlist(slideshow.channel.playlist)] == [
        "two.png", "three.png"]


def test_original_only_plays_what_is_not_enhanced(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhanced_ids={"id-2", "id-3"}))

    assert slideshow.show_originals_only() is True

    assert slideshow.hud_originals_mode
    assert [str(item.path) for item in read_playlist(slideshow.channel.playlist)] == ["one.png"]


def test_original_only_turns_enhanced_only_off(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhanced_ids={"id-2", "id-3"}))
    slideshow.set_enhanced_mode(True)

    slideshow.show_originals_only()

    assert (slideshow.hud_enhanced_mode, slideshow.hud_originals_mode) == (False, True)


def test_enhanced_and_original_lifts_either_and_leaves_f_mode_and_the_action_filter(
        qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of),
                           hud=HudFacts(favorite_ids={"id-1", "id-2", "id-3"},
                                        enhanced_ids={"id-3"}))
    slideshow.set_favorites_filter(True)
    slideshow.action_presses.filter("alpha")
    for narrow in (slideshow.show_originals_only, lambda: slideshow.set_enhanced_mode(True)):
        assert narrow() is True

        assert slideshow.show_enhanced_and_original() is True

        assert (slideshow.hud_enhanced_mode, slideshow.hud_originals_mode) == (False, False)
        assert (slideshow.hud_favorites_filter, slideshow.hud_action_filter) == (True, "alpha")


def test_the_enhanced_button_pressed_under_original_only_turns_enhanced_only_on(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhanced_ids={"id-2", "id-3"}))
    slideshow.show_originals_only()

    assert answer(slideshow, "enhanced")

    assert (slideshow.hud_enhanced_mode, slideshow.hud_originals_mode) == (True, False)
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

    assert _sent(slideshow)[:3] == [f"SET_PACE {slideshow.dwell_s}", "LOCK_OFF", "PLAY_FILE three.png"]
    assert slideshow.hud_prompt_id == "id-3"


def test_a_file_about_to_be_deleted_is_let_go_of(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.release_media(["one.png"])

    assert _sent(slideshow) == ["NEXT"]


def test_a_file_let_go_is_not_taken_for_one_that_would_not_open(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, items=_ITEMS[:1])
    _says(slideshow, video="one.png")
    slideshow.tick()
    _sent(slideshow)
    slideshow.release_media(["one.png"])
    let_go = _sent(slideshow)

    _says(slideshow, video="one.png", idle=True)
    slideshow.tick()

    assert (let_go, _sent(slideshow)) == (["LET_GO"], []), (
        "nothing is up because the file was let go, not because it would not open, so the "
        "slideshow does not step past it")


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


def test_a_reorder_keeping_the_slide_leaves_the_funestra_on_the_image_it_has(qtbot, tmp_path):
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


_VERSIONS = {"one.png": [("one.png", "image", "Enhancement 1/1"),
                         ("one_base.png", "image", "Original")]}
_FAMILY = "one.png|one_base.png"
_TWO_ENHANCEMENTS = {"one.png": [("one.png", "image", "Enhancement 2/2"),
                                 ("one_1.png", "image", "Enhancement 1/2"),
                                 ("one_base.png", "image", "Original")]}


class TestVersions:
    def test_a_step_holds_the_funestra_and_hands_it_the_versions_to_step_through(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_VERSIONS)

        slideshow.slideshow_step_version(1)

        assert _sent(slideshow) == ["SET_PACE 0", f"NEXT_VERSION {_FAMILY}"]

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
    def test_leaving_the_versions_forgets_them_and_hands_the_funestra_its_pace_before_the_next(
            self, qtbot, tmp_path, move, verb):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_VERSIONS)
        slideshow.slideshow_step_version(1)
        _sent(slideshow)

        move(slideshow)

        sent = _sent(slideshow)
        assert sent.index("FORGET_VERSIONS") < sent.index(f"SET_PACE {slideshow.dwell_s}") < sent.index(verb)

    def test_a_version_landing_while_they_are_compared_holds_the_funestra_on_the_new_one(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_VERSIONS)
        slideshow.slideshow_step_version(1)
        _sent(slideshow)

        slideshow.note_enhanced("id-1", "one_better.png")
        slideshow.add_versions({"one_better.png": [
            ("one_better.png", "image", "Enhancement 2/2"),
            ("one.png", "image", "Enhancement 1/2"),
            ("one_base.png", "image", "Original")]})
        _says(slideshow, video="one_better.png")
        slideshow.tick()

        assert f"SET_PACE {slideshow.dwell_s}" not in _sent(slideshow)
        assert _hud(slideshow).item_note == "Enhancement 2/2"

    def test_an_enhancement_about_to_be_deleted_hands_the_funestra_the_next_one_down(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_TWO_ENHANCEMENTS)
        _sent(slideshow)

        slideshow.release_media(["one.png"], the_item_stays=True)

        assert _sent(slideshow) == ["NEXT_VERSION one.png|one_1.png"]

    def test_an_item_left_with_fewer_enhancements_plays_on_at_its_newest_with_only_those(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_TWO_ENHANCEMENTS)

        slideshow.note_versions_deleted("id-1", "one_1.png", versions={"one_1.png": [
            ("one_1.png", "image", "Enhancement 1/1"), ("one_base.png", "image", "Original")]})
        _sent(slideshow)
        slideshow.slideshow_step_version(1)

        played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
        assert played[0] == "one_1.png"
        assert "one.png" not in played
        assert _sent(slideshow)[-1] == "NEXT_VERSION one_1.png|one_base.png"

    def test_a_videos_other_version_is_handed_over_with_its_own_script(
            self, qtbot, tmp_path, monkeypatch):
        scripts = _scripted(monkeypatch, tmp_path, "clip.mp4")
        slideshow = _slideshow(qtbot, tmp_path, items=[("clip_evolved.mp4", "video", "id-1")])
        _says(slideshow, video="clip_evolved.mp4")
        slideshow.tick()
        _sent(slideshow)
        slideshow.set_versions({"clip_evolved.mp4": [("clip_evolved.mp4", "video", "Evolved"),
                                                   ("clip.mp4", "video", "Original")]})

        slideshow.slideshow_step_version(1)

        assert _sent(slideshow)[-1] == f"NEXT_VERSION clip_evolved.mp4|clip.mp4\t{scripts['clip.mp4']}"

    def test_stepping_on_and_back_hands_the_funestra_the_same_versions_each_way(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_VERSIONS)

        slideshow.slideshow_step_version(1)
        _sent(slideshow)
        slideshow.slideshow_step_version(-1)

        assert _sent(slideshow) == [f"PREV_VERSION {_FAMILY}"]

    def test_the_sessions_shift_left_counts_the_enhancements_down_and_shift_right_up(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions({"one.png": [("one.png", "image", "Enhancement 2/2"),
                                            ("one_1.png", "image", "Enhancement 1/2"),
                                            ("one_0.png", "image", "Original")]})

        stepped = []
        for press in ("cycle_version_back", "cycle_version_back",
                      "cycle_version", "cycle_version"):
            answer(slideshow, press)
            stepped += [line.partition(" ")[0] for line in _sent(slideshow)
                        if line.partition(" ")[0] in ("NEXT_VERSION", "PREV_VERSION")]

        assert stepped == ["NEXT_VERSION", "NEXT_VERSION", "PREV_VERSION", "PREV_VERSION"]

    def test_the_version_on_screen_is_read_off_what_the_funestra_says_it_shows(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions(_VERSIONS)
        slideshow.slideshow_step_version(1)

        _says(slideshow, video="one.png", showing="one_base.png")
        slideshow.tick()

        assert _hud(slideshow).item_note == "Original"
        assert slideshow.state().version_index == 1

    def test_an_item_filed_once_is_left_alone_rather_than_stepping_the_set(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="two.png")
        slideshow.set_versions(_VERSIONS)

        slideshow.slideshow_step_version(1)

        assert _sent(slideshow) == []

    def test_the_band_lights_its_versions_button_only_where_there_are_some(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        assert slideshow.has_other_versions is False

        slideshow.set_versions(_VERSIONS)

        assert slideshow.has_other_versions is True

    def test_moving_to_another_item_forgets_the_versions_and_starts_that_ones_from_the_top(
            self, qtbot, tmp_path):
        slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
        slideshow.set_versions({**_VERSIONS,
                                "two.png": [("two.png", "image", "Enhancement 1/1"),
                                            ("two_base.png", "image", "Original")]})
        slideshow.slideshow_step_version(1)
        _sent(slideshow)

        _says(slideshow, video="two.png")
        slideshow.tick()
        moved = _sent(slideshow)
        slideshow.slideshow_step_version(1)

        assert "FORGET_VERSIONS" in moved
        assert _sent(slideshow) == ["SET_PACE 0", "NEXT_VERSION two.png|two_base.png"]


def _around(prompt_id):
    if prompt_id != "id-1":
        return NavMapNeighbors()
    other_action = Slide("one-x.png", "image", "id-1x")
    return NavMapNeighbors(seeds=(Slide("one-b.png", "image", "id-1b"),),
                        column=(NavMapRow(other_action, "dawn"),), label="fox",
                        group=(other_action,))


def test_the_hud_maps_the_item_on_screen_against_the_library(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))

    model = parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))

    assert ([cell.path for cell in model.seeds],
            [(cell.path, cell.label) for cell in model.actions]) == (
        ["one-b.png"], [("one-x.png", "dawn")]), (
        "the HUD hands the Funestra the item's other seeds for its row and its other actions for "
        "its column, as a Fun Time satellite maps a video, so the two maps read alike")
    assert (model.current_action, model.seed_count, model.action_count) == ("fox", 2, 2)


def test_a_loop_hands_the_funestra_the_row_to_play_and_its_ending_hands_back_the_set(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around), say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop("seed")

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "one-b.png"]
    assert "RELOAD_PLAYLIST" in _sent(slideshow)
    assert said == ["Looping seeds: 2"]
    assert parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8")).active_loop == "seed"

    slideshow.slideshow_loop_cycle()
    slideshow.slideshow_loop_cycle()

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


def test_a_cull_that_leaves_one_image_in_the_row_locks_it(qtbot, tmp_path):
    asked, starred, opened = [], [], []
    slideshow = _slideshow(qtbot, tmp_path,
                           actions=SlideshowActions(neighbors=_around, delete=lambda prompt_id: None,
                                                    favorite=starred.append, lock=opened.append,
                                                    enhance=lambda prompt_id: asked.append(prompt_id) or True))
    slideshow.slideshow_loop("seed")
    _sent(slideshow)

    slideshow.slideshow_cull()
    sent = _sent(slideshow)
    _says(slideshow, video="one-b.png", locked=True)
    slideshow.tick()

    assert "LOCK_ON" in sent, (
        "a row worn down to one image is that image over and over, which is the lock, so the "
        "cull that wore it down ends the loop and locks what is left, as a Satellite's does")
    assert (slideshow.locked, slideshow.hud_map().loop) == (True, "")
    assert (asked, starred, opened) == ([], [], [])


def test_the_cull_that_ends_a_loop_of_one_hands_the_funestra_its_list_once(
        qtbot, tmp_path, monkeypatch):
    slideshow = _slideshow(qtbot, tmp_path,
                           actions=SlideshowActions(neighbors=_around, delete=lambda prompt_id: None))
    slideshow.slideshow_loop("seed")
    written = _lists_handed_to_a_funestra(monkeypatch)

    slideshow.slideshow_cull()

    assert len(written) == 1, (
        "ending the loop deals the pass again, and that pass change has already handed the "
        "Funestra the set")


def test_a_reset_that_drops_a_switch_hands_the_funestra_its_list_once(
        qtbot, tmp_path, monkeypatch):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-1", "id-2"}))
    slideshow.set_favorites_filter(True)
    written = _lists_handed_to_a_funestra(monkeypatch)

    slideshow.reset_in_place()

    assert len(written) == 1, (
        "dropping a switch deals the pass again, and that pass change has already handed the "
        "Funestra the fresh pass")


def test_a_forward_step_in_a_row_down_to_one_image_hands_the_set_back(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    slideshow.slideshow_loop("seed")
    slideshow.slideshow_cull()
    _sent(slideshow)

    slideshow.slideshow_step(1)

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one-b.png", "two.png", "three.png"]
    assert _sent(slideshow)[-1] == "NEXT"
    assert slideshow.hud_map().loop == ""


def test_a_map_cell_the_set_never_held_is_played_by_the_one_verb_that_splices(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    _sent(slideshow)

    slideshow.show_item("one-x.png")

    assert _sent(slideshow) == ["PLAY_FILE one-x.png"]
    assert slideshow.hud_prompt_id == "id-1x"


def test_a_jump_out_of_a_loop_hands_the_funestra_its_list_before_the_jump(
        qtbot, tmp_path, monkeypatch):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around))
    slideshow.slideshow_loop("seed")
    _sent(slideshow)
    play_already_sent = []
    write = FunestraChannel.write_playlist

    def noting_what_was_sent(channel, items):
        command = channel.command_file
        play_already_sent.append(command.exists() and "PLAY_FILE" in command.read_text())
        return write(channel, items)

    monkeypatch.setattr(FunestraChannel, "write_playlist", noting_what_was_sent)

    slideshow.show_item("one-x.png")

    plays = [verb for verb in _sent(slideshow) if verb.startswith("PLAY_FILE")]
    assert (play_already_sent, plays) == ([False], ["PLAY_FILE one-x.png"]), (
        "a jump off the loop deals the pass again, which hands the Funestra the list, and only "
        "then may the one PLAY_FILE land in it")


_WATCHED_MOST = {"one.png": 1.0, "two.png": 1.0, "three.png": 1e12}


def _weighing_what_he_watches() -> SlideshowActions:
    return SlideshowActions(weight_of=lambda path: _WATCHED_MOST[str(path)])


def _handed_to_the_funestra(slideshow) -> list[str]:
    return [str(item.path) for item in read_playlist(slideshow.channel.playlist)]


def test_a_shuffled_slideshow_deals_what_he_watches_most_first_and_still_plays_everything(
        qtbot, tmp_path):
    slideshow = FunestraSlideshow(Playing(_ITEMS, actions=_weighing_what_he_watches()),
                                  _seat(tmp_path), _NO_HOSTING)
    stop_the_poll_to_tick_by_hand(slideshow)

    played = _handed_to_the_funestra(slideshow)

    assert played[0] == "three.png"
    assert sorted(played) == ["one.png", "three.png", "two.png"]


def test_a_slideshow_of_the_latest_plays_in_order_whatever_he_watches_most(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=_weighing_what_he_watches())

    assert _handed_to_the_funestra(slideshow) == ["one.png", "two.png", "three.png"]


def _plays(slideshow) -> list[str]:
    return [verb for verb in _sent(slideshow) if verb.startswith("PLAY_FILE")]


_NAMED_FOR = {"id-1": "Source image, alpha", "id-2": "beta", "id-3": "alpha"}


def _actions_of(prompt_ids):
    return {prompt_id: _NAMED_FOR.get(prompt_id, "") for prompt_id in prompt_ids}


def test_a_rows_button_narrows_the_slideshow_to_that_action_and_hands_the_funestra_what_is_left(
        qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of), say=_into(said))
    _sent(slideshow)

    slideshow.action_presses.filter("alpha")

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "three.png"]
    assert _plays(slideshow) == []
    assert said == ["Filter: 'alpha' (2)"]


def test_filter_said_of_its_side_narrows_to_what_the_item_on_screen_is_named_for(
        qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of), say=_into(said))

    slideshow.action_presses.filter_to_the_one_on_screen()

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert (played, said) == (["one.png"], ["Filter: 'source image, alpha' (1)"])


def test_filter_said_over_an_item_named_for_no_action_says_so(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))

    slideshow.action_presses.filter_to_the_one_on_screen()

    assert said == ["No action for this one"]


def _a_slideshow_whose_actions_can_be_struck(qtbot, tmp_path, said: list) -> FunestraSlideshow:
    named = {"id-1": "alpha"}
    return _slideshow(qtbot, tmp_path, say=_into(said), actions=SlideshowActions(
        actions_of=lambda prompt_ids: {prompt_id: named.get(prompt_id, "")
                                       for prompt_id in prompt_ids},
        strike_action=lambda slide: named.pop(slide.prompt_id, "")))


def test_wrong_action_sends_the_slide_on_screen_back_and_says_so(qtbot, tmp_path):
    said = []
    slideshow = _a_slideshow_whose_actions_can_be_struck(qtbot, tmp_path, said)
    slideshow.action_presses.filter_to_the_one_on_screen()

    assert answer(slideshow, "wrong_action")
    slideshow.action_presses.filter_to_the_one_on_screen()

    assert said == ["Filter: 'alpha' (1)", "Sent back to the action setter tool", "No action for this one"]


def test_a_row_naming_two_actions_is_posted_with_its_spaces_as_underscores(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of), say=_into(said))

    slideshow.action_presses.filter("source_image,_alpha")

    assert said == ["Filter: 'source image, alpha' (1)"]
    assert parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8")).filter_query == (
        "source image, alpha")


def test_a_configuration_rows_button_plays_it_and_loops_its_seeds(qtbot, tmp_path):
    said = []
    a_configuration = Slide("one-x.png", "image", "id-1x")
    around = lambda pid: NavMapNeighbors(  # noqa: E731
        column=(NavMapRow(a_configuration, "E629425B", configuration=True),)
        if pid == "id-1" else (),
        seeds=(Slide("one-y.png", "image", "id-1y"),) if pid == "id-1x" else ())
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=around, actions_of=_actions_of),
                           say=_into(said))
    _sent(slideshow)

    slideshow.action_presses.filter("e629425b")

    assert slideshow.hud_prompt_id == "id-1x"
    assert slideshow.hud_action_filter == ""
    assert said == ["Looping seeds: 2"]


def test_a_filter_past_the_item_on_screen_sends_the_funestra_to_what_is_left(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of))
    _sent(slideshow)

    slideshow.action_presses.filter("beta")

    assert _plays(slideshow) == ["PLAY_FILE two.png"]


def test_an_action_nothing_here_shows_says_so_and_moves_nothing(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of), say=_into(said))
    _sent(slideshow)

    slideshow.action_presses.filter("gamma")

    assert (_sent(slideshow), said) == ([], ["Filter: no matches for 'gamma'"])


def test_no_filter_lifts_the_action_filter_and_leaves_f_mode_on(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of),
                           hud=HudFacts(favorite_ids={"id-1", "id-2"}), say=_into(said))
    slideshow.set_favorites_filter(True)
    slideshow.action_presses.filter("beta")
    said.clear()

    assert answer(slideshow, "no_filter")

    assert (slideshow.hud_favorites_filter, slideshow.hud_action_filter) == (True, "")
    assert (slideshow.pass_size(), said) == (2, ["Filter: cleared (2)"])


def test_no_filter_lifts_the_action_filter_and_leaves_the_enhanced_filter_on(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of),
                           hud=HudFacts(enhanced_ids={"id-2", "id-3"}))
    slideshow.set_enhanced_mode(True)
    slideshow.action_presses.filter("beta")

    assert answer(slideshow, "no_filter")

    assert (slideshow.hud_enhanced_mode, slideshow.hud_action_filter) == (True, "")
    assert slideshow.pass_size() == 2


def test_no_filter_with_no_action_filter_on_changes_nothing(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(actions_of=_actions_of),
                           hud=HudFacts(favorite_ids={"id-1", "id-2"}))
    slideshow.set_favorites_filter(True)
    _sent(slideshow)

    assert answer(slideshow, "no_filter")

    assert (slideshow.hud_favorites_filter, slideshow.hud_action_filter) == (True, "")
    assert (slideshow.pass_size(), _sent(slideshow)) == (2, [])


def test_the_pass_is_as_long_as_what_the_funestra_was_handed(qtbot, tmp_path):
    assert _slideshow(qtbot, tmp_path).pass_size() == 3


def test_ending_a_loop_says_so_and_ending_none_says_nothing(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around), say=_into(said))
    slideshow.slideshow_loop("seed")

    slideshow.slideshow_loop("")
    slideshow.slideshow_loop("")

    assert said == ["Looping seeds: 2", "Loop off"]


def test_a_loop_button_for_a_row_of_one_image_locks_it_instead(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop("seed")

    assert (_sent(slideshow), said) == (["LOCK_ON"], ["Locked"]), (
        "a row holding only the image on screen cannot be looped and the press still means this "
        "one, so it locks the image rather than refusing, the way a Satellite's loop button "
        "locks a video whose group holds only it")
    assert slideshow.locked is True


def test_a_loop_asked_of_a_row_of_one_drops_the_loop_that_was_running(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_row_only))
    slideshow.slideshow_loop("seed")

    slideshow.slideshow_loop("action")

    assert (slideshow.locked, slideshow.hud_map().loop) == (True, ""), (
        "a lock is not a loop, so the loop that was running is dropped")


def test_the_loop_keys_first_press_locks_the_item_on_screen(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around), say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_loop_cycle()

    assert [verb for verb in _sent(slideshow) if verb.startswith("LOCK")] == ["LOCK_ON"]
    assert (slideshow.locked, slideshow.hud_map().loop, said) == (True, "", ["Locked"])


def test_the_loop_keys_off_stop_lets_go_of_a_lock_taken_inside_the_loop(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(neighbors=_around), say=_into(said))
    slideshow.slideshow_loop("action")
    slideshow.slideshow_toggle_lock()
    _sent(slideshow)
    said.clear()

    slideshow.slideshow_loop_cycle()

    assert "LOCK_OFF" in _sent(slideshow)
    assert (slideshow.locked, slideshow.hud_map().loop, said) == (False, "", ["Loop off"])


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


def test_a_switch_to_an_item_plays_it_and_says_switched(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.switch_to("three.png")

    assert (_sent(slideshow), said) == (["PLAY_FILE three.png"], ["Switched"])


def test_a_switch_to_an_item_the_slideshow_does_not_hold_says_nothing(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.switch_to("nowhere.png")

    assert (_sent(slideshow), said) == ([], [])


def test_cycle_seed_plays_the_next_seed_and_says_so(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said),
                           actions=SlideshowActions(neighbors=_around))
    _sent(slideshow)

    slideshow.slideshow_cycle("seed")

    assert (_sent(slideshow), said) == (["PLAY_FILE one-b.png"], ["Next seed"])


def test_cycle_action_plays_the_next_action_and_names_it(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said), actions=SlideshowActions(
        neighbors=_around, actions_of=lambda asked: dict.fromkeys(asked, "dawn")))
    _sent(slideshow)

    slideshow.slideshow_cycle("action")

    assert (_sent(slideshow), said) == (["PLAY_FILE one-x.png"], ["Action: dawn"])


def test_cycle_action_onto_an_item_with_no_action_says_nothing(qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said),
                           actions=SlideshowActions(neighbors=_around))
    _sent(slideshow)

    slideshow.slideshow_cycle("action")

    assert (_sent(slideshow), said) == (["PLAY_FILE one-x.png"], [])


@pytest.mark.parametrize(("axis", "said_then"), [("seed", "No other seeds"),
                                                 ("action", "No other actions")])
def test_a_cycle_with_nothing_else_on_its_row_says_so_and_stays(qtbot, tmp_path, axis, said_then):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=_into(said))
    _sent(slideshow)

    slideshow.slideshow_cycle(axis)

    assert (_sent(slideshow), said) == ([], [said_then])


def test_trash_over_a_favorite_takes_its_star_and_moves_on(qtbot, tmp_path):
    unfavorited, deleted = [], []
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(favorite_ids={"id-1"}),
                           actions=SlideshowActions(unfavorite=unfavorited.append, delete=deleted.append))
    _sent(slideshow)

    slideshow.slideshow_cull()

    assert (unfavorited, deleted) == (["id-1"], [])
    assert _sent(slideshow) == ["NEXT"]
    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "two.png", "three.png"]


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


def _hud(slideshow: FunestraSlideshow):
    return parse_hud(slideshow.channel.hud_file.read_text(encoding="utf-8"))


def test_the_hud_names_the_version_of_the_item_on_screen(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.set_versions(_VERSIONS)

    assert _hud(slideshow).item_note == "Enhancement 1/1"


def test_the_hud_says_whether_a_better_version_is_being_made_or_waiting(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.note_enhancing({"id-1": "queued"})
    assert _hud(slideshow).item_note == "Enhancement queued"
    slideshow.note_enhancing({"id-1": "running"})
    assert _hud(slideshow).item_note == "Enhancing…"


def test_a_lock_that_asks_for_a_better_version_says_so_on_the_hud(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, actions=SlideshowActions(enhance=lambda pid: True))

    slideshow.slideshow_toggle_lock()
    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert _hud(slideshow).item_note == "Enhancement queued"


def test_a_better_version_that_landed_leaves_nothing_in_flight_on_the_hud(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_enhancing({"id-1": "running"})

    slideshow.note_enhanced("id-1", "one_enhanced.png")

    assert _hud(slideshow).item_note == ""


def test_an_item_evolver_upscaled_plays_next_as_its_upscale(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    slideshow.note_added(Slide("three_topaz.mp4", "video", "id-3"))

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played == ["one.png", "three_topaz.mp4", "two.png"]


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


def _being_enhanced_on_screen(qtbot, tmp_path) -> FunestraSlideshow:
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhancing={"id-1": "running"}))
    _says(slideshow, video="one.png")
    slideshow.tick()
    return slideshow


def test_an_item_being_enhanced_is_held_for_half_the_pace_on_the_funestra(qtbot, tmp_path):
    slideshow = _being_enhanced_on_screen(qtbot, tmp_path)

    assert "HOLD_PICTURE 2" in _sent(slideshow)


def test_a_locked_item_being_enhanced_holds_for_the_whole_pace(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, hud=HudFacts(enhancing={"id-1": "running"}),
                           locked=True)

    _says(slideshow, video="one.png", locked=True)
    slideshow.tick()

    assert [verb for verb in _sent(slideshow) if verb.startswith("HOLD_PICTURE")] == [], (
        "the half hold has the Funestra move on early from an item being made, and a locked "
        "item is one it must not move on from")


def test_an_item_being_made_makes_its_move_at_the_ordinary_pace(qtbot, tmp_path):
    slideshow = _being_enhanced_on_screen(qtbot, tmp_path)

    assert [verb for verb in _sent(slideshow) if verb.startswith("SET_PACE")] == ["SET_PACE 4"]


def test_an_item_nothing_is_being_made_of_holds_for_the_whole_pace(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    _says(slideshow, video="two.png")
    slideshow.tick()

    assert not any(verb.startswith("HOLD_PICTURE") for verb in _sent(slideshow))


def test_a_request_spoken_over_an_image_keeps_it_on_the_funestra_still_moving(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.pause_for_request(True)
    while_said = _sent(slideshow)
    slideshow.pause_for_request(False)

    assert (while_said, _sent(slideshow), slideshow.locked) == (["LOCK_ON"], ["LOCK_OFF"], False)


def test_a_slideshow_closed_while_a_request_holds_its_slide_lets_the_funestra_go(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.pause_for_request(True)
    _sent(slideshow)

    slideshow.close()

    assert _sent(slideshow) == ["LOCK_OFF"], (
        "the Funestra keeps playing this list until the session hands it its own, which is what "
        "leaving Origenerator mode does")


def test_a_slideshow_closed_while_its_versions_are_compared_sets_the_funestra_going_again(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.set_versions(_VERSIONS)
    slideshow.slideshow_step_version(1)
    _sent(slideshow)

    slideshow.close()

    assert _sent(slideshow) == [f"SET_PACE {slideshow.dwell_s}"]


def test_a_slideshow_closed_on_a_slide_it_locked_leaves_the_funestra_locked(qtbot, tmp_path):
    slideshow = _slideshow_locked_on(qtbot, tmp_path, "one.png")

    slideshow.close()

    assert _sent(slideshow) == []


def test_a_slide_a_request_is_spoken_over_stays_held_through_a_new_list(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.pause_for_request(True)
    _sent(slideshow)

    slideshow.note_added(Slide("four.png", "image", "id-4"))

    assert "LOCK_OFF" not in _sent(slideshow)


def _following_a_run(qtbot, tmp_path) -> FunestraSlideshow:
    slideshow = _slideshow(qtbot, tmp_path)
    slideshow.note_generating("id-run", FRAME)
    slideshow.follow_what_is_being_made()
    _says(slideshow, video=str(read_playlist(slideshow.channel.playlist)[0].path))
    slideshow.tick()
    return slideshow


def _slideshow_following_a_run(qtbot, tmp_path) -> FunestraSlideshow:
    slideshow = _following_a_run(qtbot, tmp_path)
    _sent(slideshow)
    return slideshow


def test_a_run_the_slideshow_follows_is_held_on_the_funestra_while_it_is_made_still_moving(
        qtbot, tmp_path):
    slideshow = _following_a_run(qtbot, tmp_path)

    sent = _sent(slideshow)

    assert (_locks(sent)[-1], set(_paces(sent))) == ("LOCK_ON", {f"SET_PACE {slideshow.dwell_s}"})


def _paces(sent: list[str]) -> list[str]:
    return [verb for verb in sent if verb.startswith("SET_PACE")]


def _locks(sent: list[str]) -> list[str]:
    return [verb for verb in sent if verb.startswith("LOCK_")]


def test_a_run_the_slideshow_follows_that_stops_leaves_it_paging_at_its_pace(qtbot, tmp_path):
    slideshow = _slideshow_following_a_run(qtbot, tmp_path)

    slideshow.note_in_flight(set())

    assert _locks(_sent(slideshow)) == ["LOCK_OFF"]


def test_a_run_the_slideshow_follows_lets_go_once_the_funestra_is_stepped_off_it(
        qtbot, tmp_path):
    slideshow = _slideshow_following_a_run(qtbot, tmp_path)

    slideshow.slideshow_step(1)
    _says(slideshow, video="one.png")
    slideshow.tick()

    assert _locks(_sent(slideshow)) == ["LOCK_OFF"]


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


def test_an_image_enhanced_during_the_slideshow_steps_its_versions_on_the_funestra(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.note_enhanced("id-1", "one_enhanced.png")
    _says(slideshow, video="one_enhanced.png")
    slideshow.tick()
    _sent(slideshow)

    slideshow.add_versions({"one_enhanced.png": [("one_enhanced.png", "image", "Enhancement 1/1"),
                                               ("one.png", "image", "Original")]})
    slideshow.slideshow_step_version(1)

    assert _sent(slideshow) == ["SET_PACE 0", "NEXT_VERSION one_enhanced.png|one.png"]


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

    slideshow.note_added(Slide("run.png", "image", "id-run"))

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


def test_an_image_being_enhanced_on_the_funestra_shows_the_enhancement_coming_in(
        qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")

    slideshow.note_enhancing({"id-1": "running"}, {"id-1": FRAME})

    assert _frame_shown(_sent(slideshow)) == FRAME


def test_a_better_version_landing_on_the_funestras_image_goes_up_on_its_move(qtbot,
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

    slideshow.note_added(Slide("run.png", "image", "id-run"))

    played = [str(item.path) for item in read_playlist(slideshow.channel.playlist)]
    assert played[:2] == ["two.png", "run.png"]


def _row_only(prompt_id):
    return (NavMapNeighbors(seeds=(Slide("one-b.png", "image", "id-1b"),), label="fox")
            if prompt_id == "id-1" else NavMapNeighbors())


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


def test_an_image_goes_to_the_funestra_with_the_places_its_fixes_found(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)

    slideshow.set_versions(_PLACED)

    handed = {str(item.path): item.points_of_interest
              for item in read_playlist(slideshow.channel.playlist)}
    assert handed == {"one.png": FACE, "two.png": (), "three.png": ()}


def test_a_slideshow_opened_with_its_versions_hands_the_funestra_its_list_once(
        qtbot, tmp_path, monkeypatch):
    written = _lists_handed_to_a_funestra(monkeypatch)

    slideshow = _slideshow(qtbot, tmp_path, versions=_PLACED)

    handed = {str(item.path): item.points_of_interest
              for item in read_playlist(slideshow.channel.playlist)}
    assert (written, handed) == ([3], {"one.png": FACE, "two.png": (), "three.png": ()})


def test_versions_that_bring_no_places_leave_the_pass_where_it_was(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    _sent(slideshow)

    slideshow.set_versions(_VERSIONS)

    assert "RELOAD_PLAYLIST" not in _sent(slideshow)


def test_an_older_version_stepped_to_goes_with_its_own_places(qtbot, tmp_path):
    slideshow = _slideshow_with_the_funestra_on(qtbot, tmp_path, video="one.png")
    slideshow.set_versions({"one.png": [("one.png", "image", "Enhance 2", FACE),
                                      ("one-v1.png", "image", "Enhance 1", ((0.0, 0.0, 0.5, 0.5),))]})
    _sent(slideshow)

    slideshow.slideshow_step_version(1)

    assert _sent(slideshow) == [
        "SET_PACE 0", "NEXT_VERSION one.png		0.4,0.1,0.6,0.3|one-v1.png		0,0,0.5,0.5"]


def _ready_opening(items, *, scripts=None, lead=0, lead_neighbors=None) -> RegionOpening:
    return RegionOpening(rows=[], items=items, versions={}, enhanced_ids=set(),
                         scripts=scripts or {}, lead=lead, lead_neighbors=lead_neighbors)


def test_a_ready_opening_hands_over_its_scripts_without_looking_on_disk(
        qtbot, tmp_path, monkeypatch):
    items = [("clip.mp4", "video", "id-1"), ("other.mp4", "video", "id-2")]
    script = tmp_path / "clip.funscript"

    def looked(*_args, **_kwargs):
        raise AssertionError("looked on disk on the press")

    monkeypatch.setattr(slideshow_pass, "funscript_of", looked)

    slideshow = FunestraSlideshow(
        Playing(items, opening=_ready_opening(items, scripts={"clip.mp4": script, "other.mp4": None})),
        _seat(tmp_path))
    stop_the_poll_to_tick_by_hand(slideshow)

    assert {item.path.name: item.funscript for item in read_playlist(slideshow.channel.playlist)} == {
        "clip.mp4": script, "other.mp4": None}


def test_after_opening_a_slideshow_looks_on_disk_for_a_script_again(
        qtbot, tmp_path, monkeypatch):
    items = [("clip.mp4", "video", "id-1")]
    slideshow = FunestraSlideshow(
        Playing(items, opening=_ready_opening(items, scripts={"clip.mp4": None})),
        _seat(tmp_path))
    stop_the_poll_to_tick_by_hand(slideshow)
    scripts = _scripted(monkeypatch, tmp_path, "clip.mp4")

    qtbot.waitUntil(lambda: not slideshow._scripts_on_opening)
    slideshow.play(Playing(items))

    assert read_playlist(slideshow.channel.playlist)[0].funscript == scripts["clip.mp4"]


def test_a_ready_opening_leads_with_the_slide_whose_map_it_already_has(qtbot, tmp_path):
    items = [("one.png", "image", "id-1"), ("two.png", "image", "id-2")]
    neighbors = NavMapNeighbors()

    def walked(_prompt_id):
        raise AssertionError("walked the library for the first slide's map")

    slideshow = FunestraSlideshow(
        Playing(items, actions=SlideshowActions(neighbors=walked),
                opening=_ready_opening(items, lead=1, lead_neighbors=neighbors)),
        _seat(tmp_path))
    stop_the_poll_to_tick_by_hand(slideshow)

    assert read_playlist(slideshow.channel.playlist)[0].path.name == "two.png"


def test_on_a_sessions_funestra_a_request_and_what_is_being_dictated_are_said_in_the_gallerys_caption(
        qtbot, tmp_path):
    said = []
    slideshow = _slideshow(qtbot, tmp_path, say=lambda text, mark: said.append(text))

    slideshow.shown.request_line("a request")
    slideshow.shown.dictating("some words")
    slideshow.shown.dictating("")
    slideshow.shown.room_paused(True)

    assert said == ["a request", "some words"]


def test_a_press_on_the_job_queue_on_a_sessions_funestra_reaches_its_foot(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path)
    pressed = []
    slideshow.shown._press_the_foot = lambda verb, payload: pressed.append((verb, payload))

    slideshow.shown.press_the_queue("a press", "1|2")

    assert pressed == [("a press", "1|2")]


def test_a_slideshow_culled_empty_is_over(qtbot, tmp_path):
    slideshow = _slideshow(qtbot, tmp_path, items=[("one.png", "image", "id-1")])

    slideshow.slideshow_cull()

    assert slideshow.is_showing() is False


_TWO_GROUPS = [("fox.png", "image", "id-fox"), ("fox-runs.mp4", "video", "id-runs"),
               ("hare.png", "image", "id-hare"), ("hare-runs.mp4", "video", "id-hare-runs")]
_BY_ANIMAL = {"id-fox": "fox", "id-runs": "fox", "id-hare": "hare", "id-hare-runs": "hare"}
_ID_OF = {path: prompt_id for path, _kind, prompt_id in _TWO_GROUPS}


def _shuffled_by_animal(qtbot, tmp_path, *, shuffle=None) -> FunestraSlideshow:
    slideshow = FunestraSlideshow(
        Playing(_TWO_GROUPS, shuffle=shuffle,
                actions=SlideshowActions(group_of=lambda slide, _seed: _BY_ANIMAL[slide.prompt_id])),
        _seat(tmp_path), _NO_HOSTING)
    stop_the_poll_to_tick_by_hand(slideshow)
    return slideshow


def _on_the_last_slide(slideshow) -> list[str]:
    last = _handed_to_the_funestra(slideshow)[-1]
    _says(slideshow, video=last)
    slideshow.tick()
    return _handed_to_the_funestra(slideshow)


def test_a_shuffled_slideshow_on_its_last_slide_hands_the_funestra_its_next_pass_to_follow(
        qtbot, tmp_path):
    slideshow = _shuffled_by_animal(qtbot, tmp_path)
    handed = set()
    for _ in range(30):
        last = _handed_to_the_funestra(slideshow)[-1]
        following = _on_the_last_slide(slideshow)
        assert following[0] == last
        assert sorted(_BY_ANIMAL[_ID_OF[video]] for video in following[1:]) in (
            ["fox", "hare"], ["fox"], ["hare"])
        handed |= set(following)

    assert len(handed) == 4


def test_a_slideshow_of_the_latest_on_its_last_slide_hands_the_funestra_nothing_new(
        qtbot, tmp_path):
    slideshow = _shuffled_by_animal(qtbot, tmp_path, shuffle=in_order)
    before = _handed_to_the_funestra(slideshow)
    _sent(slideshow)

    assert _on_the_last_slide(slideshow) == before
    assert "RELOAD_PLAYLIST" not in _sent(slideshow)
