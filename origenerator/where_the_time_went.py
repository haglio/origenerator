from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import NamedTuple

PACKAGE_DIR = str(Path(__file__).resolve().parent)
LOOK_EVERY_S = 0.1
MOST_NAMED = 25

def functions_stood_in(frame: FrameType | None, under: str = PACKAGE_DIR) -> list[str]:
    stood_in: list[str] = []
    while frame is not None:
        code = frame.f_code
        if code.co_filename.startswith(under):
            function = f"{Path(code.co_filename).stem}.{code.co_name}"
            if function not in stood_in:
                stood_in.append(function)
        frame = frame.f_back
    return stood_in


def said_in_one_line(looks: int, stood_in: Counter, most: int = MOST_NAMED) -> str:
    most_often_first = sorted(stood_in.items(), key=lambda found: -found[1])
    named = ", ".join(f"{function} {count}" for function, count in most_often_first[:most])
    return f"{looks} looks at the thread, and how many found it inside each function: {named}"


class LooksAtAThread:
    def __init__(self, thread_id: int, *,
                 frames: Callable[[], dict[int, FrameType]] = sys._current_frames,
                 every_s: float = LOOK_EVERY_S) -> None:
        self._thread_id = thread_id
        self._frames = frames
        self._every_s = every_s
        self._stood_in: Counter = Counter()
        self._looks = 0
        self._done = threading.Event()
        self._looking = threading.Thread(target=self._keep_looking, daemon=True,
                                         name="where-the-time-went")

    def __enter__(self) -> LooksAtAThread:
        self._looking.start()
        return self

    def __exit__(self, *_raised) -> None:
        self._done.set()
        self._looking.join()

    def look(self) -> None:
        self._stood_in.update(functions_stood_in(self._frames().get(self._thread_id)))
        self._looks += 1

    def said_in_one_line(self, most: int = MOST_NAMED) -> str:
        return said_in_one_line(self._looks, self._stood_in, most)

    def _keep_looking(self) -> None:
        while not self._done.wait(self._every_s):
            self.look()


class Seconds(NamedTuple):
    wall: float
    this_program: float
    computer_busy: float
    computer_all: float


_FILETIME_TICKS_A_SECOND = 10_000_000


def _seconds_of(filetime: ctypes.c_uint64) -> float:
    return filetime.value / _FILETIME_TICKS_A_SECOND


def read_seconds() -> Seconds:
    idle, kernel_with_idle_in_it, user = ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64()
    ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel_with_idle_in_it), ctypes.byref(user))
    computer_all = _seconds_of(kernel_with_idle_in_it) + _seconds_of(user)
    return Seconds(wall=time.perf_counter(), this_program=time.process_time(),
                   computer_busy=computer_all - _seconds_of(idle), computer_all=computer_all)


def spent_between(before: Seconds, after: Seconds) -> str:
    computer_all = after.computer_all - before.computer_all
    busy = (after.computer_busy - before.computer_busy) / computer_all if computer_all else 0.0
    return (f"{after.wall - before.wall:.1f} s passed, this program had a processor for "
            f"{after.this_program - before.this_program:.1f} s of them, "
            f"and the computer's processors were {busy:.0%} busy")
