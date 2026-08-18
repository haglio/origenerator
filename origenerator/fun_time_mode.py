"""The contract for running inside a Fun Time session's satellite half.

Launched with ``--fun-time``, Origenerator stops being a free-floating desktop
app and becomes one of the session's managed windows: the main window occupies
the rect Fun Time names (the Random Favs Browser's), the slideshows and
fullscreen views go to the portrait/landscape satellite regions by their
subject's orientation, and everything OSR2 is left to Fun Time's main player.
Fun Time drives the shows through a command file and reads back which regions
are occupied through a status file — the same file-channel idioms its own
satellite players speak (``player_core.file_channel``).

This module is the pure half: the argv contract, the session dataclass, and the
orientation policy that picks a region.  The Qt half — placing windows, polling
the channels — lives in :mod:`origenerator.gui.fun_time_bridge`.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# The window captions Fun Time resolves the shows by (with the process pid), the
# way it resolves its own satellites by "Portrait AI Player"/"Landscape AI
# Player".  Per REGION, not per view class: whatever view occupies a region
# carries that region's caption.
PORTRAIT_SHOW_TITLE = "Origenerator Portrait"
LANDSCAPE_SHOW_TITLE = "Origenerator Landscape"
SHOW_TITLES = {"portrait": PORTRAIT_SHOW_TITLE, "landscape": LANDSCAPE_SHOW_TITLE}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class FunTimeSession:
    """Everything ``--fun-time`` hands this app about the session hosting it."""

    main_rect: Rect
    portrait_rect: Rect
    landscape_rect: Rect
    command_file: Path | None
    paused_file: Path | None
    status_file: Path | None
    dashboard_cmd_file: Path | None

    def region_rect(self, side: str) -> Rect:
        return self.portrait_rect if side == "portrait" else self.landscape_rect


@dataclass(frozen=True)
class AppArgs:
    fun_time: FunTimeSession | None
    taskbar_identity: str | None


def _add_rect_arguments(parser: argparse.ArgumentParser, prefix: str) -> None:
    for field in ("x", "y", "width", "height"):
        parser.add_argument(f"--{prefix}{field}", type=int, default=0)


def _rect(args: argparse.Namespace, prefix: str) -> Rect:
    return Rect(*(getattr(args, f"{prefix}{field}") for field in ("x", "y", "width", "height")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="origenerator")
    parser.add_argument("--fun-time", action="store_true")
    _add_rect_arguments(parser, "")           # the main window's rect (the RFB's)
    _add_rect_arguments(parser, "portrait_")  # the portrait satellite region
    _add_rect_arguments(parser, "landscape_")  # the landscape satellite region
    for name in ("command-file", "paused-file", "status-file", "dashboard-cmd-file"):
        parser.add_argument(f"--{name}", type=Path, default=None)
    parser.add_argument("--taskbar-identity", default=None)
    return parser


def region_for_size(width: int, height: int) -> str:
    """Which satellite region a subject of this shape belongs in.

    A square subject goes to the landscape region — the roomier of the two.
    """
    return "portrait" if height > width else "landscape"


def _measured_size(item: tuple) -> tuple[int, int] | None:
    """(width, height) of *item*, or ``None`` when nothing about it measures.

    The stored thumbnail is preferred — bounded to 256px but aspect-preserving,
    so it answers orientation without opening the full-size file.  An image
    with no thumbnail is measured directly; a video without one is passed over
    rather than decoded, since a frame grab costs seconds on HEVC.
    """
    from PIL import Image  # deferred: this module is imported before the splash

    path, media_type = item[0], item[1]
    still = item[3] if len(item) > 3 else None
    for candidate in (still, path if media_type == "image" else None):
        if not candidate:
            continue
        try:
            with Image.open(candidate) as opened:
                return opened.size
        except OSError:
            continue
    return None


def _probed_video_size(items: list[tuple]) -> tuple[int, int] | None:
    """(width, height) of the first openable video's frame, or ``None``.

    The backstop for a set whose stills all failed to measure: one decode of
    one frame, paid only on that path — a folder of thumbnail-less videos
    otherwise measured as nothing at all, and "nothing" fell to landscape,
    which is how a portrait slideshow once landed on the landscape region.
    """
    import cv2  # deferred: this module is imported before the splash

    for item in items:
        if item[1] != "video":
            continue
        capture = cv2.VideoCapture(str(item[0]))
        try:
            got_frame, frame = capture.read()
        finally:
            capture.release()
        if got_frame and frame is not None:
            height, width = frame.shape[:2]
            return width, height
    return None


def region_for_items(items: list[tuple]) -> str:
    """The region a set of ``(path, media_type, prompt_id, still)`` items plays in.

    Majority orientation over what measures — stills first, one decoded video
    frame as the backstop when no still answered.  A tie, or a set in which
    nothing measures at all, goes to landscape, the roomier region.
    """
    votes = {"portrait": 0, "landscape": 0}
    for item in items:
        size = _measured_size(item)
        if size is not None:
            votes[region_for_size(*size)] += 1
    if not votes["portrait"] and not votes["landscape"]:
        probed = _probed_video_size(items)
        if probed is not None:
            votes[region_for_size(*probed)] += 1
    side = "portrait" if votes["portrait"] > votes["landscape"] else "landscape"
    logger.info(
        "Show routed to %s (portrait=%d landscape=%d of %d items)",
        side, votes["portrait"], votes["landscape"], len(items),
    )
    return side


def parse_app_args(argv: list[str]) -> AppArgs:
    """The launch contract, parsed.  ``argv`` excludes the program name."""
    args = build_parser().parse_args(argv)
    session = None
    if args.fun_time:
        session = FunTimeSession(
            main_rect=_rect(args, ""),
            portrait_rect=_rect(args, "portrait_"),
            landscape_rect=_rect(args, "landscape_"),
            command_file=args.command_file,
            paused_file=args.paused_file,
            status_file=args.status_file,
            dashboard_cmd_file=args.dashboard_cmd_file,
        )
    return AppArgs(fun_time=session, taskbar_identity=args.taskbar_identity)
