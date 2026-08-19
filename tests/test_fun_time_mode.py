"""The Fun Time mode contract: the flags Fun Time launches this app with."""

from pathlib import Path

from PIL import Image

from origenerator.fun_time_mode import (
    Rect,
    parse_app_args,
    region_for_items,
    region_for_size,
)


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
        "--portrait_x", "2560", "--portrait_y", "0",
        "--portrait_width", "1440", "--portrait_height", "1870",
        "--landscape_x", "853", "--landscape_y", "0",
        "--landscape_width", "1707", "--landscape_height", "1400",
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


def test_region_for_items_measures_the_still_when_the_media_is_a_video(tmp_path):
    still = _png(tmp_path / "still.png", 90, 160)
    items = [(str(tmp_path / "clip.mp4"), "video", "a", str(still))]
    assert region_for_items(items) == "portrait"


def test_region_for_items_defaults_to_landscape_when_nothing_measures(tmp_path):
    assert region_for_items([]) == "landscape"
    assert region_for_items([(str(tmp_path / "gone.mp4"), "video", "a", None)]) == "landscape"


def _mp4(path: Path, width: int, height: int) -> Path:
    import cv2
    import numpy

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
