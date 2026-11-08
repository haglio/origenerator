from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app_support import origenerator_handoff as handoff
from app_support.file_channel import read_key_values
from funestra.file_channel import append_command
from funestra.playlist import write_playlist
from shared_ui.orientation import orientation_of_size as shape_of_size

from origenerator.media import MediaType
from origenerator.osr2_controls_commands import spelled_filter, spelled_for
from origenerator.slideshow import Slide
from origenerator.slideshow_buttons import (
    HUD_FACTS,
    PRESSES,
    PRESSES_ABOUT_A_FILE,
    PRESSES_ON_THE_QUEUE,
)
from origenerator.workflows.detail_parts import published_fix_phrases

logger = logging.getLogger(__name__)

MODULE = "origenerator"

MODE_FLAG = "--fun-time"

RECT_FIELDS = ("x", "y", "width", "height")
MAIN_RECT_PREFIX = ""
REGION_RECT_PREFIXES = {shape: f"{shape}-" for shape in ("portrait", "landscape")}

SESSION_FILES = ("command-file", "paused-file", "status-file", "dashboard-cmd-file")

SHAPES = ("portrait", "landscape")
FUNESTRA_FILES = ("playlist", "cmd-file", "status-file", "hud-file")

HEADSET_FILES = ("frames-file", "input-file")

HEADSET_PRESS = "press"
HEADSET_RELEASE = "release"
HEADSET_DRAG = "drag"
HEADSET_HOVER = "hover"
HEADSET_SCROLL = "scroll"
HEADSET_RIGHT_CLICK = "rightclick"
HEADSET_WORDS = (HEADSET_PRESS, HEADSET_RELEASE, HEADSET_DRAG, HEADSET_HOVER,
                 HEADSET_SCROLL, HEADSET_RIGHT_CLICK)

CLOSE_SLIDESHOWS = "CLOSE_SLIDESHOWS"
FILTER_ENHANCED = "FILTER_ENHANCED"
RELEASE = "RELEASE"
HAND_OVER = "HAND_OVER"
TAKE_BACK = "TAKE_BACK"
SESSION_VERBS = (CLOSE_SLIDESHOWS, FILTER_ENHANCED, RELEASE, TAKE_BACK)
OPEN_SLIDESHOW = "open_slideshow"
CLOSE_SLIDESHOW = "close_slideshow"
SIDE_VERBS = (OPEN_SLIDESHOW, CLOSE_SLIDESHOW)
GO_TO = "GO_TO"
TRASH_FILE = "TRASH_FILE"
SAY = "say"
SAID_AT = " @"
REQUEST_OPEN = "request_open"
REQUEST_CLOSED = "request_closed"
LOCK_HELD = "lock_held"

TASKBAR_IDENTITY_FLAG = "--taskbar-identity"

CHECK_LAUNCH_FLAG = "--check-launch"

SPOKEN_PHRASES_MODULE = "origenerator.voice.hosted"

WINDOW_TITLE = "Origenerator"

CONTRACT_FILE = "origenerator_contract.json"

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _rect_flags(prefix: str) -> tuple[str, ...]:
    return tuple(f"--{prefix}{field}" for field in RECT_FIELDS)


def required_flags() -> tuple[str, ...]:
    return (
        MODE_FLAG,
        *_rect_flags(MAIN_RECT_PREFIX),
        TASKBAR_IDENTITY_FLAG,
        *(f"--{name}" for name in SESSION_FILES),
    )


def region_flags(shape: str) -> tuple[str, ...]:
    return _rect_flags(REGION_RECT_PREFIXES[shape])


def funestra_flags(shape: str) -> tuple[str, ...]:
    return tuple(f"--{shape}-{name}" for name in FUNESTRA_FILES)


def headset_flags() -> tuple[str, ...]:
    return tuple(f"--{name}" for name in HEADSET_FILES)


def command_lines() -> tuple[str, ...]:
    return (
        *SESSION_VERBS,
        f"{HAND_OVER}|{{frames}}|{{input}}",
        f"{GO_TO}|{{file}}",
        f"{SAY.upper()}:{{words}}",
        f"{TRASH_FILE}|{{file}}",
        *(line for shape in SHAPES for line in _lines_said_to(shape)),
    )


def _lines_said_to(shape: str) -> tuple[str, ...]:
    return (
        *(spelled_for(shape, verb) for verb in SIDE_VERBS),
        *(spelled_for(shape, press) for press in PRESSES),
        *(f"{spelled_for(shape, press)}|{{file}}" for press in PRESSES_ABOUT_A_FILE),
        *(f"{spelled_for(shape, press)}|{where}" for press, where in PRESSES_ON_THE_QUEUE.items()),
        *(f"{spelled_for(shape, fact)}|{payload}"
          for fact, payload in HUD_FACTS.items()),
        spelled_filter(shape, "{row}"),
        f"{spelled_for(shape, SAY)}:{{words}}",
    )


_CARRIED = re.compile(r"(\{\w+\})")
_MAYBE_SAID_AT = rf"(?:{re.escape(SAID_AT)}[0-9]+(?:\.[0-9]+)?)?"


def command_patterns() -> tuple[str, ...]:
    return tuple("(?i)" + "".join(".+" if _CARRIED.fullmatch(piece) else re.escape(piece)
                                  for piece in _CARRIED.split(line))
                 + ("" if "|" in line else _MAYBE_SAID_AT)
                 for line in command_lines())


def declaration() -> dict:
    return {
        "module": MODULE,
        "window_title": WINDOW_TITLE,
        "check_launch_flag": CHECK_LAUNCH_FLAG,
        "spoken_phrases_module": SPOKEN_PHRASES_MODULE,
        "required_flags": list(required_flags()),
        "region_flags": {shape: list(region_flags(shape)) for shape in SHAPES},
        "player_flags": {shape: list(funestra_flags(shape)) for shape in SHAPES},
        "headset_flags": list(headset_flags()),
        "headset_words": list(HEADSET_WORDS),
        "command_case_blind": True,
        "command_lines": list(command_lines()),
        "command_patterns": list(command_patterns()),
        "said_at_suffix": f"{SAID_AT}{{said_at_epoch_seconds}}",
        "request_lines": [spelled_for(shape, line) for shape in SHAPES
                          for line in (REQUEST_OPEN, REQUEST_CLOSED)],
        "lock_lines": [f"{spelled_for(shape, LOCK_HELD)}|{{file}}" for shape in SHAPES],
        "fix_phrases": list(published_fix_phrases()),
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8", newline="\n")
    return path


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class FunestraChannel:
    playlist: Path
    command_file: Path
    status_file: Path
    hud_file: Path

    def write_playlist(self, items) -> None:
        write_playlist(self.playlist, items)

    def send(self, verb: str) -> bool:
        return append_command(self.command_file, verb)

    def status(self) -> dict[str, str]:
        try:
            return read_key_values(self.status_file)
        except OSError:
            return {}


@dataclass(frozen=True)
class FunTimeSession:
    main_rect: Rect
    portrait_rect: Rect
    landscape_rect: Rect
    command_file: Path | None
    paused_file: Path | None
    status_file: Path | None
    dashboard_cmd_file: Path | None
    portrait_funestra: FunestraChannel | None = None
    landscape_funestra: FunestraChannel | None = None
    frames_file: Path | None = None
    input_file: Path | None = None
    taskbar_identity: str | None = None

    @property
    def in_a_headset(self) -> bool:
        return self.frames_file is not None and self.input_file is not None

    def region_rect(self, shape: str) -> Rect:
        return self.portrait_rect if shape == "portrait" else self.landscape_rect

    def funestra(self, shape: str) -> FunestraChannel | None:
        return self.portrait_funestra if shape == "portrait" else self.landscape_funestra


@dataclass(frozen=True)
class AppArgs:
    fun_time: FunTimeSession | None
    check_launch: bool = False


def _add_rect_arguments(parser: argparse.ArgumentParser, prefix: str) -> None:
    for field in RECT_FIELDS:
        parser.add_argument(f"--{prefix}{field}", type=int, default=0)


def _rect(args: argparse.Namespace, prefix: str) -> Rect:
    held = prefix.replace("-", "_")
    return Rect(*(getattr(args, f"{held}{field}") for field in RECT_FIELDS))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=MODULE)
    parser.add_argument(MODE_FLAG, action="store_true")
    _add_rect_arguments(parser, MAIN_RECT_PREFIX)
    for prefix in REGION_RECT_PREFIXES.values():
        _add_rect_arguments(parser, prefix)
    for name in (*SESSION_FILES, *HEADSET_FILES):
        parser.add_argument(f"--{name}", type=Path, default=None)
    for shape in SHAPES:
        for name in FUNESTRA_FILES:
            parser.add_argument(f"--{shape}-{name}", type=Path, default=None)
    parser.add_argument(TASKBAR_IDENTITY_FLAG, default=None)
    parser.add_argument(CHECK_LAUNCH_FLAG, action="store_true")
    return parser


def region_for_size(width: int, height: int) -> str:
    return shape_of_size(width, height)


def _measured_size(slide: Slide) -> tuple[int, int] | None:
    from PIL import Image  # noqa: PLC0415 (this module is read before the splash)

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
    import cv2  # noqa: PLC0415 (this module is read before the splash)

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
    slides = [Slide.of(item) for item in items]
    shapes = [region_for_size(*size) for size in map(_measured_size, slides)
              if size is not None]
    if not shapes:
        probed = _probed_video_size(slides)
        shapes = [region_for_size(*probed)] if probed is not None else []
    shape = majority_shape(shapes)
    logger.info(
        "Slideshow routed to %s (portrait=%d landscape=%d of %d items)",
        shape, shapes.count("portrait"), shapes.count("landscape"), len(slides),
    )
    return shape


def majority_shape(shapes) -> str:
    votes = Counter(shapes)
    return "portrait" if votes["portrait"] > votes["landscape"] else "landscape"


def _funestra(args: argparse.Namespace, shape: str) -> FunestraChannel | None:
    files = [getattr(args, flag.removeprefix("--").replace("-", "_"))
             for flag in funestra_flags(shape)]
    return FunestraChannel(*files) if all(files) else None


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
        portrait_funestra=_funestra(args, "portrait"),
        landscape_funestra=_funestra(args, "landscape"),
        frames_file=args.frames_file,
        input_file=args.input_file,
        taskbar_identity=args.taskbar_identity,
    )


def _missing_required(argv: list[str]) -> list[str]:
    written = {word.split("=", 1)[0] for word in argv}
    return [flag for flag in required_flags() if flag not in written]


def parse_app_args(argv: list[str]) -> AppArgs:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.fun_time and (missing := _missing_required(argv)):
        parser.error(f"{MODE_FLAG} without {', '.join(missing)}; the launch "
                     f"contract is {CONTRACT_FILE}")
    return AppArgs(fun_time=_session_of(args), check_launch=args.check_launch)


def _stayed_standalone(why: str) -> None:
    logger.warning("A Fun Time session's takeover was not taken: %s. This window "
                   "stays standalone, so that session has no Origenerator.", why)


def take_the_takeover(state_dir: Path, *, pid: int) -> FunTimeSession | None:
    try:
        asked = handoff.take_the_takeover(state_dir)
        if asked is None:
            return None
        args, unknown = build_parser().parse_known_args(asked.args)
    except (OSError, ValueError, TypeError) as not_one:
        _stayed_standalone(f"it did not read as a session ({not_one!r})")
        return None
    if asked.pid != pid:
        _stayed_standalone(f"it asked for another window, pid {asked.pid}")
        return None
    if unknown:
        _stayed_standalone(f"it named {unknown}, a flag this app does not know")
        return None
    session = _session_of(args)
    if session is None:
        _stayed_standalone("it named no session at all")
    return session


if __name__ == "__main__":
    print(publish())
