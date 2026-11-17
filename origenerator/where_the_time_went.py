from __future__ import annotations

import ctypes
import faulthandler
import re
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

PACKAGE_DIR = str(Path(__file__).resolve().parent)
LOOK_EVERY_S = 0.1
MOST_NAMED = 25

_A_FRAME = re.compile(r'^\s+File "(?P<file>.+)", line \d+ in (?P<function>.+)$')


def every_threads_stack() -> str:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as dumped:
        faulthandler.dump_traceback(dumped, all_threads=True)
        dumped.seek(0)
        return dumped.read()


def functions_stood_in(stacks: str, thread_id: int, under: str = PACKAGE_DIR) -> set[str]:
    its_header = f"0x{thread_id:08x}"
    stood_in = set()
    reading_it = False
    for line in stacks.splitlines():
        frame = _A_FRAME.match(line)
        if frame is None:
            reading_it = its_header in line
        elif reading_it and frame["file"].startswith(under):
            stood_in.add(f"{Path(frame['file']).stem}.{frame['function']}")
    return stood_in


def said_in_one_line(looks: int, stood_in: Counter, most: int = MOST_NAMED) -> str:
    most_often_first = sorted(stood_in.items(), key=lambda found: (-found[1], found[0]))
    named = ", ".join(f"{function} {count}" for function, count in most_often_first[:most])
    return f"{looks} looks at the thread, and how many found it inside each function: {named}"


class LooksAtAThread:
    def __init__(self, thread_id: int, *,
                 stacks: Callable[[], str] = every_threads_stack,
                 every_s: float = LOOK_EVERY_S) -> None:
        self._thread_id = thread_id
        self._stacks = stacks
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
        self._stood_in.update(functions_stood_in(self._stacks(), self._thread_id))
        self._looks += 1

    def said_in_one_line(self) -> str:
        return said_in_one_line(self._looks, self._stood_in)

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
