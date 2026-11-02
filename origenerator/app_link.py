from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import msvcrt
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app_support.loading_screen import TAKING_OVER_WITHIN_S
from app_support.win32 import mutex_name, try_acquire_mutex

from origenerator.single_instance import let_go_of

SCHEME = "origenerator"
_GO_TO = "go-to"
_GENERATION = "generation"

_AN_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

CARRIED_IN = "ORIGENERATOR_GO_TO"

HANDLER = Path("tools") / "open_from_toast.py"

LIVE_LAUNCHER = "launch_origenerator.vbs"

CHECKOUT = Path(__file__).resolve().parents[1]

_PIPE = r"\\.\pipe"
_BUSY_PATIENCE_S = 2.0
_NO_SUCH_PIPE = 2

_STARTING = "Global\\Origenerator.starting-for-a-click"
_LOOK_EVERY_S = 0.1


def link_to(generation: str) -> str:
    return f"{SCHEME}:{_GO_TO}?{_GENERATION}={generation}"


def generation_in(link: str) -> str | None:
    parts = urlsplit(link)
    if parts.scheme != SCHEME or parts.path != _GO_TO:
        return None
    asked = parse_qs(parts.query).get(_GENERATION, [])
    return a_generation(asked[0]) if len(asked) == 1 else None


def a_generation(asked: str) -> str | None:
    return asked if _AN_ID.fullmatch(asked or "") else None


def made_for_a_click() -> bool:
    return CARRIED_IN in os.environ


def channel_for(checkout: Path) -> str:
    home = os.path.normcase(os.path.abspath(checkout))
    return f"Origenerator-{hashlib.sha1(home.encode('utf-16-le')).hexdigest()[:12]}"


def windowless_interpreter() -> Path:
    """Windows gives a console interpreter run with no console of its own a console window over whatever the user was doing."""
    silent = Path(sys.executable).with_name("pythonw.exe")
    return silent if silent.exists() else Path(sys.executable)


def handler_command(*, checkout: Path, interpreter: Path) -> str:
    return f'"{interpreter}" "{checkout / HANDLER}" "{LIVE_LAUNCHER}" "%1"'


def follow(argv, *, checkout: Path = CHECKOUT) -> int:
    try:
        launcher, link = argv
    except ValueError:
        return 2
    generation = generation_in(link)
    if generation is None:
        return 2
    channel = channel_for(checkout)
    if hand_over(generation, channel=channel):
        _note(checkout, f"handed {generation} to the running app")
        return 0
    starting = try_acquire_mutex(mutex_name(_STARTING, channel))
    if starting is None:
        _note(checkout, f"left {generation} to the copy another click is starting")
        return 0
    try:
        _note(checkout, f"starting the app on {generation}")
        start_the_app(checkout, launcher, generation)
        wait_until_it_listens(channel)
    finally:
        let_go_of(starting)
    return 0


def wait_until_it_listens(channel: str) -> None:
    giving_up_at = time.monotonic() + TAKING_OVER_WITHIN_S
    while not listening(channel) and time.monotonic() < giving_up_at:
        time.sleep(_LOOK_EVERY_S)


def hand_over(generation: str, *, channel: str) -> bool:
    giving_up_at = time.monotonic() + _BUSY_PATIENCE_S
    while True:
        try:
            pipe = os.open(rf"{_PIPE}\{channel}", os.O_WRONLY | os.O_BINARY)
        except FileNotFoundError:
            return False
        except OSError:
            if time.monotonic() >= giving_up_at:
                return True
            time.sleep(0.05)
            continue
        try:
            let_it_take_the_foreground(pipe)
            os.write(pipe, generation.encode("ascii") + b"\n")
        finally:
            os.close(pipe)
        return True


def listening(channel: str) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitNamedPipeW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD]
    if kernel32.WaitNamedPipeW(rf"{_PIPE}\{channel}", 1):
        return True
    return ctypes.get_last_error() != _NO_SUCH_PIPE


def let_it_take_the_foreground(pipe: int) -> None:
    """Windows lets only the process it started for a click come to the foreground."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GetNamedPipeServerProcessId.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.ULONG)]
    listener = ctypes.wintypes.ULONG()
    if kernel32.GetNamedPipeServerProcessId(msvcrt.get_osfhandle(pipe),
                                            ctypes.byref(listener)):
        ctypes.windll.user32.AllowSetForegroundWindow(listener)  # type: ignore[attr-defined]


def start_the_app(checkout: Path, launcher: str, generation: str) -> None:
    system = os.environ.get("SYSTEMROOT", r"C:\Windows")
    subprocess.Popen(
        [str(Path(system) / "System32" / "wscript.exe"), str(checkout / launcher)],
        env={**os.environ, CARRIED_IN: generation},
        cwd=str(checkout),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _note(checkout: Path, what: str) -> None:
    try:
        log = checkout / "state" / "origenerator_launcher.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as writing:
            stamped = time.strftime("%Y-%m-%d %H:%M:%S")
            writing.write(f"===== {stamped} toast: {what}\n")
    except OSError:
        pass
