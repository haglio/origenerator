"""The contract for running inside a Fun Time session's satellite half.

Launched with ``--fun-time``, Origenerator stops being a free-floating desktop
app and becomes one of the session's managed windows: the main window occupies
the rect Fun Time names (the Random Favs Browser's), each show goes to the
portrait or landscape side by its subject's orientation, and everything OSR2 is
left to Fun Time's main player.  Fun Time drives the shows through a command
file and reads back which sides are occupied through a status file — the same
file-channel idioms its own satellite players speak
(``player_core.file_channel``).

What a side IS depends on what the session hands over.  A session that names
each player's own channel (:class:`PlayerChannel`) is handing this app its
players: a show is then a playlist written for one, a few verbs, and the panel
this app publishes for it.  One that names none is an older session, whose
shows open a window of this app's over each region instead.

This module is the pure half: the argv contract, the session dataclass, and the
orientation policy that picks a region.  The Qt half — placing windows, polling
the channels — lives in :mod:`origenerator.gui.fun_time_bridge`.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from origenerator.media import MediaType
from origenerator.slideshow import Slide
from origenerator.win32 import process_creation_time

logger = logging.getLogger(__name__)

# --- the declared launch contract ------------------------------------------
#
# Everything a host must know to start this app inside a session and then find
# the windows it opens.  Declared once here, published as CONTRACT_FILE at the
# checkout root for a host that cannot import this package, and used below to
# BUILD the parser -- so the flags a host writes, the flags this app reads and
# the document a host checks itself against are all one thing.  They were three
# hand-kept copies with nothing comparing them, which is how a flag renamed on
# one side could become a window that never appeared on the other (audit
# cross/boundaries/cross/017).

#: The module a host runs.
MODULE = "origenerator"

#: Present iff this app is being hosted.
MODE_FLAG = "--fun-time"

#: The main window's rect -- the Random Favs Browser's, which it covers -- and
#: the two satellite regions a show of this app's opens over when the session
#: hands no player for that side.
RECT_FIELDS = ("x", "y", "width", "height")
MAIN_RECT_PREFIX = ""
REGION_RECT_PREFIXES = {side: f"{side}-" for side in ("portrait", "landscape")}

#: The session's own channel to this app: how it drives it and reads it back.
SESSION_FILES = ("command-file", "paused-file", "status-file", "dashboard-cmd-file")

#: The two satellite players a session hands over, and the four files each
#: player contract trades through (see :class:`PlayerChannel`).  All four of a
#: side or none of it: a session that names none for a side still wants a
#: window of this app's over that region instead.
SIDES = ("portrait", "landscape")
PLAYER_FILES = ("playlist", "cmd-file", "status-file", "hud-file")

#: Whose taskbar button this window joins.
TASKBAR_IDENTITY_FLAG = "--taskbar-identity"

#: Boot and exit without opening anything -- how a host's suite proves the real
#: launch works (see :func:`build_parser`).
CHECK_LAUNCH_FLAG = "--check-launch"

#: The caption the main window wears, which a host resolves it by (together
#: with the pid).  The splash deliberately wears another ("Origenerator
#: Loading"), so a caption match cannot reach it.
WINDOW_TITLE = "Origenerator"

# The captions a host resolves the shows by (with the process pid), the way it
# resolves its own satellites by "Portrait AI Player"/"Landscape AI Player".
# Per REGION, not per view class: whatever view occupies a region carries that
# region's caption.
PORTRAIT_SHOW_TITLE = "Origenerator Portrait"
LANDSCAPE_SHOW_TITLE = "Origenerator Landscape"
SHOW_TITLES = {"portrait": PORTRAIT_SHOW_TITLE, "landscape": LANDSCAPE_SHOW_TITLE}

#: Beside the launcher at the checkout root, which is the path a host is
#: already told.  Running this module rewrites it.
CONTRACT_FILE = "origenerator_contract.json"

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _rect_flags(prefix: str) -> tuple[str, ...]:
    return tuple(f"--{prefix}{field}" for field in RECT_FIELDS)


def required_flags() -> tuple[str, ...]:
    """The flags every hosted launch carries, in the order a host writes them.

    Required in the strict sense: :func:`parse_app_args` refuses a hosted
    launch missing one.  argparse already refuses a flag this app does not
    know, so a rename on the host's side fails at its launch with a message --
    and this is the other half of the same drift, a host that stopped SENDING
    one, which used to fall through to a default of nothing at all.
    """
    return (
        MODE_FLAG,
        *_rect_flags(MAIN_RECT_PREFIX),
        TASKBAR_IDENTITY_FLAG,
        *(f"--{name}" for name in SESSION_FILES),
    )


def region_flags(side: str) -> tuple[str, ...]:
    """One region's rect, for the show this app opens over it itself.

    Not required: a host that names a player for the side opens no window of
    ours there at all, so the rect it would take is beside the point.
    """
    return _rect_flags(REGION_RECT_PREFIXES[side])


def player_flags(side: str) -> tuple[str, ...]:
    """One side's player channel: all four of them, or none of them."""
    return tuple(f"--{side}-{name}" for name in PLAYER_FILES)


def declaration() -> dict:
    """The published document, as a host reads it."""
    return {
        "module": MODULE,
        "window_title": WINDOW_TITLE,
        "show_titles": dict(SHOW_TITLES),
        "check_launch_flag": CHECK_LAUNCH_FLAG,
        "required_flags": list(required_flags()),
        "region_flags": {side: list(region_flags(side)) for side in SIDES},
        "player_flags": {side: list(player_flags(side)) for side in SIDES},
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    """Write the document out, in the shape the tracked copy holds."""
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class PlayerChannel:
    """One of the session's players, as the player contract reaches it.

    The four files a content source and a player trade through
    (``player_core.playlist`` / ``player_verbs`` / ``status`` /
    ``satellite_hud``): the list the player plays, the verbs it drains, the
    status it publishes back, and the panel this app publishes for the session
    to draw on it.
    """

    playlist: Path
    command_file: Path
    status_file: Path
    hud_file: Path


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
    # Each satellite player's own channel, where the session hands its players
    # over — ``None`` for a side it named none for, which is a session that
    # still wants a window of this app's over that region instead.
    portrait_player: PlayerChannel | None = None
    landscape_player: PlayerChannel | None = None

    def region_rect(self, side: str) -> Rect:
        return self.portrait_rect if side == "portrait" else self.landscape_rect

    def player(self, side: str) -> PlayerChannel | None:
        """The player holding *side*, or ``None`` where the session named none."""
        return self.portrait_player if side == "portrait" else self.landscape_player


@dataclass(frozen=True)
class AppArgs:
    fun_time: FunTimeSession | None
    taskbar_identity: str | None
    check_launch: bool = False


def _add_rect_arguments(parser: argparse.ArgumentParser, prefix: str) -> None:
    for field in RECT_FIELDS:
        parser.add_argument(f"--{prefix}{field}", type=int, default=0)


def _rect(args: argparse.Namespace, prefix: str) -> Rect:
    held = prefix.replace("-", "_")
    return Rect(*(getattr(args, f"{held}{field}") for field in RECT_FIELDS))


def build_parser() -> argparse.ArgumentParser:
    """The contract above, as the parser that reads it off a command line.

    Every flag comes from the declaration, so the document a host reads and the
    argv this app accepts cannot come to disagree.
    """
    parser = argparse.ArgumentParser(prog=MODULE)
    parser.add_argument(MODE_FLAG, action="store_true")
    _add_rect_arguments(parser, MAIN_RECT_PREFIX)
    for prefix in REGION_RECT_PREFIXES.values():
        _add_rect_arguments(parser, prefix)
    for name in SESSION_FILES:
        parser.add_argument(f"--{name}", type=Path, default=None)
    for side in SIDES:
        for name in PLAYER_FILES:
            parser.add_argument(f"--{side}-{name}", type=Path, default=None)
    parser.add_argument(TASKBAR_IDENTITY_FLAG, default=None)
    # Boot far enough to prove this launch works, then exit 0 without opening
    # anything.  A hosting session's integration suite runs the REAL launch
    # command it would use in production through this, which is how a break
    # that kills the process before it can log — an import that cannot resolve
    # under the launch interpreter, a bad argv contract — is caught by a test
    # instead of by a session coming up with a window missing.  It stops short
    # of the database, ComfyUI and any window, so a run costs the machine
    # nothing and contends with no live app.
    parser.add_argument(CHECK_LAUNCH_FLAG, action="store_true")
    return parser


def region_for_size(width: int, height: int) -> str:
    """Which satellite region a subject of this shape belongs in.

    A square subject goes to the landscape region — the roomier of the two.
    """
    return "portrait" if height > width else "landscape"


def _measured_size(slide: Slide) -> tuple[int, int] | None:
    """(width, height) of *slide*, or ``None`` when nothing about it measures.

    The stored thumbnail is preferred — bounded to 256px but aspect-preserving,
    so it answers orientation without opening the full-size file.  An image
    with no thumbnail is measured directly; a video without one is passed over
    rather than decoded, since a frame grab costs seconds on HEVC.
    """
    from PIL import Image  # deferred: this module is imported before the splash

    for candidate in (slide.still,
                      slide.path if slide.media_type == MediaType.IMAGE else None):
        if not candidate:
            continue
        try:
            with Image.open(candidate) as opened:
                return opened.size
        except OSError:
            continue
    return None


def _probed_video_size(slides: list[Slide]) -> tuple[int, int] | None:
    """(width, height) of the first openable video's frame, or ``None``.

    The backstop for a set whose stills all failed to measure: one decode of
    one frame, paid only on that path — a folder of thumbnail-less videos
    otherwise measured as nothing at all, and "nothing" fell to landscape,
    which is how a portrait slideshow once landed on the landscape region.
    """
    import cv2  # deferred: this module is imported before the splash

    for slide in slides:
        if slide.media_type != MediaType.VIDEO:
            continue
        capture = cv2.VideoCapture(str(slide.path))
        try:
            got_frame, frame = capture.read()
        finally:
            capture.release()
        if got_frame and frame is not None:
            height, width = frame.shape[:2]
            return width, height
    return None


def region_for_items(items) -> str:
    """The region a set of slides plays in, however the caller assembled them.

    Majority orientation over what measures — stills first, one decoded video
    frame as the backstop when no still answered.  A tie, or a set in which
    nothing measures at all, goes to landscape, the roomier region.
    """
    slides = [Slide.of(item) for item in items]
    votes = {"portrait": 0, "landscape": 0}
    for slide in slides:
        size = _measured_size(slide)
        if size is not None:
            votes[region_for_size(*size)] += 1
    if not votes["portrait"] and not votes["landscape"]:
        probed = _probed_video_size(slides)
        if probed is not None:
            votes[region_for_size(*probed)] += 1
    side = "portrait" if votes["portrait"] > votes["landscape"] else "landscape"
    logger.info(
        "Show routed to %s (portrait=%d landscape=%d of %d items)",
        side, votes["portrait"], votes["landscape"], len(slides),
    )
    return side


def _player(args: argparse.Namespace, side: str) -> PlayerChannel | None:
    """*side*'s player channel, or ``None`` where the session named no player.

    All four files or none: half a channel is a player this app could write a
    list for and never hear back from, which is worse than the window it would
    otherwise open.
    """
    files = [getattr(args, flag.removeprefix("--").replace("-", "_"))
             for flag in player_flags(side)]
    return PlayerChannel(*files) if all(files) else None


def _session_of(args: argparse.Namespace) -> FunTimeSession | None:
    if not args.fun_time:
        return None
    return FunTimeSession(
        main_rect=_rect(args, MAIN_RECT_PREFIX),
        portrait_rect=_rect(args, REGION_RECT_PREFIXES["portrait"]),
        landscape_rect=_rect(args, REGION_RECT_PREFIXES["landscape"]),
        command_file=args.command_file,
        paused_file=args.paused_file,
        status_file=args.status_file,
        dashboard_cmd_file=args.dashboard_cmd_file,
        portrait_player=_player(args, "portrait"),
        landscape_player=_player(args, "landscape"),
    )


def _missing_required(argv: list[str]) -> list[str]:
    """Which of :func:`required_flags` a hosted *argv* does not carry."""
    written = {word.split("=", 1)[0] for word in argv}
    return [flag for flag in required_flags() if flag not in written]


def parse_app_args(argv: list[str]) -> AppArgs:
    """The launch contract, parsed.  ``argv`` excludes the program name.

    A hosted launch short of a required flag is refused rather than started:
    see :func:`required_flags` for why silence was the worse answer.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.fun_time and (missing := _missing_required(argv)):
        parser.error(f"{MODE_FLAG} without {', '.join(missing)}; the launch "
                     f"contract is {CONTRACT_FILE}")
    return AppArgs(fun_time=_session_of(args), taskbar_identity=args.taskbar_identity,
                   check_launch=args.check_launch)


OFFER_NAME = "fun_time_offer.txt"
TAKEOVER_NAME = "fun_time_takeover.json"
SESSION_NAME = "fun_time_session.txt"


def a_session_holds_the_device(state_dir: Path) -> bool:
    """Whether a live Fun Time session has claimed the OSR2.

    A session leaves its own pid and creation time here for as long as it runs,
    the way a standalone window leaves its own in the offer.  Read that way
    rather than as a heartbeat because a session that died without clearing it
    names a pid that is gone, so the claim expires with the session.

    The claim stands whether or not the session took this window over: a
    takeover can miss -- an app still booting when the room opened, an offer
    another instance overwrote -- and a window the session never reached must
    still keep off the one device it is driving.
    """
    try:
        pid, created_at = map(int, (state_dir / SESSION_NAME)
                              .read_text(encoding="utf-8").split())
    except (OSError, ValueError):
        return False
    return process_creation_time(pid) == created_at


def take_the_takeover(state_dir: Path, *, pid: int) -> FunTimeSession | None:
    takeover = state_dir / TAKEOVER_NAME
    try:
        asked = json.loads(takeover.read_text(encoding="utf-8"))
        if asked["pid"] != pid:
            return None
        args, unknown = build_parser().parse_known_args(asked["args"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    finally:
        takeover.unlink(missing_ok=True)
    return None if unknown else _session_of(args)


if __name__ == "__main__":
    print(publish())
