"""The Fun Time mode contract: the flags Fun Time launches this app with."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from origenerator.fun_time_mode import (
    Rect,
    a_session_holds_the_device,
    parse_app_args,
    region_for_items,
    region_for_size,
    take_the_takeover,
)
from origenerator.slideshow import Slide
from origenerator.win32 import this_process_creation_time
from tests.hosted_launch import hosted_launch


def _png(path: Path, width: int, height: int) -> Path:
    Image.new("RGB", (width, height)).save(path)
    return path


def test_plain_launch_has_no_fun_time_session():
    args = parse_app_args([])
    assert args.fun_time is None
    assert args.taskbar_identity is None


def test_fun_time_launch_carries_rects_channels_and_identity():
    args = parse_app_args([
        "--fun-time",
        "--x", "10", "--y", "206", "--width", "840", "--height", "1200",
        "--portrait-x", "2560", "--portrait-y", "0",
        "--portrait-width", "1440", "--portrait-height", "1870",
        "--landscape-x", "853", "--landscape-y", "0",
        "--landscape-width", "1707", "--landscape-height", "1400",
        "--command-file", "st/origenerator_cmd.txt",
        "--paused-file", "st/origenerator_paused.txt",
        "--status-file", "st/origenerator_status.txt",
        "--dashboard-cmd-file", "st/dashboard_cmd.txt",
        "--taskbar-identity", "FunTime.App",
    ])
    session = args.fun_time
    assert session.main_rect == Rect(10, 206, 840, 1200)
    assert session.portrait_rect == Rect(2560, 0, 1440, 1870)
    assert session.landscape_rect == Rect(853, 0, 1707, 1400)
    assert session.region_rect("portrait") == session.portrait_rect
    assert session.region_rect("landscape") == session.landscape_rect
    assert session.command_file == Path("st/origenerator_cmd.txt")
    assert session.paused_file == Path("st/origenerator_paused.txt")
    assert session.status_file == Path("st/origenerator_status.txt")
    assert session.dashboard_cmd_file == Path("st/dashboard_cmd.txt")
    assert args.taskbar_identity == "FunTime.App"


def test_a_session_hands_over_each_players_own_channel():
    """Inside a session the players are what shows the slides, so the launch
    names each one's channel: the list it plays, the verbs it answers, the
    status it publishes, and the panel this app publishes for it."""
    args = parse_app_args(hosted_launch(players=True, **{
        "--portrait-playlist": "st/portrait.tsv",
        "--portrait-cmd-file": "st/portrait_cmd.txt",
        "--portrait-status-file": "st/portrait_status.txt",
        "--portrait-hud-file": "st/origenerator_portrait_hud.json",
        "--landscape-playlist": "st/landscape.tsv",
    }))
    portrait = args.fun_time.player("portrait")

    assert portrait.playlist == Path("st/portrait.tsv")
    assert portrait.command_file == Path("st/portrait_cmd.txt")
    assert portrait.status_file == Path("st/portrait_status.txt")
    assert portrait.hud_file == Path("st/origenerator_portrait_hud.json")
    assert args.fun_time.player("landscape").playlist == Path("st/landscape.tsv")


def test_a_session_in_a_headset_names_where_to_hand_its_window_over():
    """A room in the headset has no monitor to put this window on, so the
    session asks for its picture instead: the file to write it into, and the
    file its pointer's presses come back through."""
    args = parse_app_args(hosted_launch(headset=True, **{
        "--frames-file": "st/origenerator_frame.bin",
        "--input-file": "st/origenerator_input.txt",
    }))
    session = args.fun_time

    assert session.frames_file == Path("st/origenerator_frame.bin")
    assert session.input_file == Path("st/origenerator_input.txt")
    assert session.in_a_headset is True


def test_a_session_on_the_monitors_asks_for_no_picture():
    """The window itself is what it shows there, so nothing is handed over and
    this app must not spend a frame drawing one."""
    args = parse_app_args(hosted_launch())

    assert args.fun_time.frames_file is None
    assert args.fun_time.in_a_headset is False


def test_a_session_that_names_no_player_hands_over_none():
    """A session too old to name them is one whose shows still open windows of
    their own, so the answer has to be "there is no player here" rather than a
    channel of empty paths."""
    args = parse_app_args(hosted_launch())

    assert args.fun_time.player("portrait") is None
    assert args.fun_time.player("landscape") is None
_SESSION_ARGS = ["--fun-time", "--x", "0", "--y", "206", "--width", "853",
                 "--height", "1234", "--command-file", "st/origenerator_cmd.txt"]


def _takeover(state_dir: Path, *, pid: int, args=_SESSION_ARGS) -> Path:
    path = state_dir / "fun_time_takeover.json"
    path.write_text(json.dumps({"pid": pid, "args": args}), encoding="utf-8")
    return path


def test_a_takeover_for_this_process_is_the_session_it_names(tmp_path):
    takeover = _takeover(tmp_path, pid=4321)

    session = take_the_takeover(tmp_path, pid=4321)

    assert session.main_rect == Rect(0, 206, 853, 1234)
    assert session.command_file == Path("st/origenerator_cmd.txt")
    assert not takeover.exists()


def test_a_takeover_meant_for_another_process_is_spent_unanswered(tmp_path):
    takeover = _takeover(tmp_path, pid=4321)

    assert take_the_takeover(tmp_path, pid=1234) is None
    assert not takeover.exists()


@pytest.mark.parametrize("written", [
    "not json",
    "[4321]",
    '{"pid": 4321}',
    '{"pid": 4321, "args": ["--fun-time", "--a-flag-from-a-newer-session"]}',
    '{"pid": 4321, "args": ["--x", "5"]}',
])
def test_a_takeover_that_does_not_read_as_a_session_is_spent_unanswered(tmp_path, written):
    takeover = tmp_path / "fun_time_takeover.json"
    takeover.write_text(written, encoding="utf-8")

    assert take_the_takeover(tmp_path, pid=4321) is None
    assert not takeover.exists()


def test_region_for_size_splits_on_aspect():
    assert region_for_size(1920, 1080) == "landscape"
    assert region_for_size(720, 1280) == "portrait"
    # A square subject goes to the landscape region, the roomier of the two.
    assert region_for_size(512, 512) == "landscape"


def test_region_for_items_takes_the_majority_orientation(tmp_path):
    tall = _png(tmp_path / "tall.png", 100, 200)
    wide = _png(tmp_path / "wide.png", 200, 100)
    items = [
        (str(tall), "image", "a", str(tall)),
        (str(tall), "image", "b", str(tall)),
        (str(wide), "image", "c", str(wide)),
    ]
    assert region_for_items(items) == "portrait"


def test_region_for_items_routes_a_running_shows_own_slides(tmp_path):
    # A show already playing asks again when its region has to be re-decided,
    # and what it holds are slides rather than the tuples the browser built.
    tall = _png(tmp_path / "tall.png", 100, 200)
    assert region_for_items([Slide(str(tall), "image", "a", str(tall))]) == "portrait"


def test_region_for_items_measures_the_still_when_the_media_is_a_video(tmp_path):
    still = _png(tmp_path / "still.png", 90, 160)
    items = [(str(tmp_path / "clip.mp4"), "video", "a", str(still))]
    assert region_for_items(items) == "portrait"


def test_region_for_items_defaults_to_landscape_when_nothing_measures(tmp_path):
    assert region_for_items([]) == "landscape"
    assert region_for_items([(str(tmp_path / "gone.mp4"), "video", "a", None)]) == "landscape"


def _mp4(path: Path, width: int, height: int) -> Path:
    import cv2  # noqa: PLC0415 (heavy; only this helper writes a real mp4)
    import numpy  # noqa: PLC0415

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5,
                             (width, height))
    for _ in range(3):
        writer.write(numpy.zeros((height, width, 3), dtype=numpy.uint8))
    writer.release()
    return path


def test_videos_without_stills_are_probed_rather_than_defaulted(tmp_path):
    # A folder of videos whose rows carry no thumbnails measured as nothing at
    # all, and "nothing" fell to landscape — which is how a portrait slideshow
    # once landed on the landscape region.  With no stills to vote, the first
    # video's own frame answers.
    clip = _mp4(tmp_path / "tall.mp4", 64, 128)
    items = [(str(clip), "video", "a", None), (str(clip), "video", "b", None)]
    assert region_for_items(items) == "portrait"


def test_the_probe_only_runs_when_nothing_else_measured(tmp_path):
    # A measurable still decides without paying for a decode.
    wide_still = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide_still)
    items = [
        (str(tmp_path / "gone.mp4"), "video", "a", str(wide_still)),
        (str(tmp_path / "also-gone.mp4"), "video", "b", None),
    ]
    assert region_for_items(items) == "landscape"


def test_a_live_sessions_claim_on_the_device_is_read_off_its_process(tmp_path):
    assert not a_session_holds_the_device(tmp_path)

    claim = tmp_path / "fun_time_session.txt"
    claim.write_text(f"{os.getpid()} {this_process_creation_time()}", encoding="utf-8")
    assert a_session_holds_the_device(tmp_path)

    claim.write_text(f"{os.getpid()} {this_process_creation_time() - 1}", encoding="utf-8")
    assert not a_session_holds_the_device(tmp_path)

    claim.write_text("not a claim", encoding="utf-8")
    assert not a_session_holds_the_device(tmp_path)
