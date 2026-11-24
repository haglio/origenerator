from __future__ import annotations

import ctypes
import faulthandler
import logging
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NamedTuple

from PySide6.QtCore import QObject, QTimer

from origenerator.where_the_time_went import LooksAtAThread

logger = logging.getLogger(__name__)

STALLED_AFTER_S = 10.0
CLOSED_WITHIN_S = 10.0
HANDED_OVER_WITHIN_S = 30.0
BEAT_MS = 1000
LATE_AFTER_S = 0.1
ASKED_AGAIN_AFTER_S = 0.05
STALL_LINES_A_MINUTE = 4
FUNCTIONS_NAMED_IN_A_STALL = 12
A_MINUTE_S = 60.0


class Timing(NamedTuple):
    stalled_after_s: float = STALLED_AFTER_S
    closed_within_s: float = CLOSED_WITHIN_S
    handed_over_within_s: float = HANDED_OVER_WITHIN_S
    beat_ms: int = BEAT_MS


USUAL_TIMING = Timing()


class FreezeWatch(QObject):
    def __init__(self, crash_log, *, timing: Timing = USUAL_TIMING, clock=time.monotonic,
                 arm=faulthandler.dump_traceback_later, stalls: StallRecord | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._crash_log = crash_log
        self._stalled_after_s = timing.stalled_after_s
        self._closed_within_s = timing.closed_within_s
        self._handed_over_within_s = timing.handed_over_within_s
        self._clock = clock
        self._arm = arm
        self._stalls = stalls
        self._last_beat = clock()
        self._beats = QTimer(self)
        self._beats.timeout.connect(self.beat)
        self._beats.start(timing.beat_ms)
        self._rearm()

    def beat(self) -> None:
        now = self._clock()
        stalled_for = now - self._last_beat
        self._last_beat = now
        if stalled_for >= self._stalled_after_s:
            self._say_the_window_answers_again(stalled_for)
        self._rearm()

    def end_the_process_if_the_close_sticks(self) -> None:
        self._end_the_process_unless_done(f"closing at {_now()}; if still closing",
                                          within_s=self._closed_within_s)

    def end_the_process_if_the_hand_over_sticks(self) -> None:
        self._end_the_process_unless_done(f"handing ComfyUI its work at {_now()}; if still at it",
                                          within_s=self._handed_over_within_s)

    def _end_the_process_unless_done(self, said: str, *, within_s: float) -> None:
        self._beats.stop()
        if self._stalls is not None:
            self._stalls.stop()
        self._crash_log.write(f"=== {said} {within_s:.0f} s later, the stacks follow "
                              f"and the process is ended ===\n")
        self._crash_log.flush()
        self._arm(within_s, repeat=False, file=self._crash_log, exit=True)

    def _rearm(self) -> None:
        self._arm(self._stalled_after_s, repeat=False, file=self._crash_log, exit=False)

    def _say_the_window_answers_again(self, stalled_for: float) -> None:
        logger.warning("The window stopped answering for %.0f s; every thread's stack "
                       "from %.0f s in is in origenerator_crash.log",
                       stalled_for, self._stalled_after_s)
        self._crash_log.write(f"=== answering again after {stalled_for:.0f} s, "
                              f"at {_now()} ===\n")
        self._crash_log.flush()


_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_USER32.CreateWindowExW.restype = wintypes.HWND
_USER32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
    wintypes.HINSTANCE, wintypes.LPVOID)
_USER32.SendMessageTimeoutW.restype = ctypes.c_size_t
_USER32.SendMessageTimeoutW.argtypes = (
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT,
    wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
_ONLY_FOR_MESSAGES = wintypes.HWND(-3)
_NOTHING_TO_DO = 0
_WAIT_WHATEVER_THE_WINDOW_IS_DOING = 0
_ERROR_TIMEOUT = 1460


class AnsweringWindow:
    def __init__(self) -> None:
        self._hwnd = _USER32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0,
                                             _ONLY_FOR_MESSAGES, None, None, None)
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

    def answers_within(self, seconds: float) -> bool:
        answer = ctypes.c_size_t()
        if _USER32.SendMessageTimeoutW(self._hwnd, _NOTHING_TO_DO, 0, 0,
                                       _WAIT_WHATEVER_THE_WINDOW_IS_DOING,
                                       round(seconds * 1000), ctypes.byref(answer)):
            return True
        error = ctypes.get_last_error()
        if error != _ERROR_TIMEOUT:
            raise ctypes.WinError(error)
        return False


@dataclass
class _Stall:
    began: float
    began_on_the_wall: float
    looks: LooksAtAThread


@dataclass
class _Minute:
    began: float
    stalls: list[float] = field(default_factory=list)

    def sum_up(self, now: float) -> None:
        if self.stalls:
            logger.info("Window stalls over %.0f s: %d, %.2f s in all, worst %.2f s, "
                        "%d not written one by one", now - self.began, len(self.stalls),
                        sum(self.stalls), max(self.stalls),
                        max(0, len(self.stalls) - STALL_LINES_A_MINUTE))


class StallRecord:
    def __init__(self, window: AnsweringWindow, window_thread: int, *, clock=time.monotonic,
                 wall=time.time, frames=sys._current_frames, pause=None) -> None:
        self._window = window
        self._window_thread = window_thread
        self._clock = clock
        self._wall = wall
        self._frames = frames
        self._stopped = threading.Event()
        self._pause = pause or self._stopped.wait
        self._stall: _Stall | None = None
        self._minute = _Minute(began=clock())
        self._watching = threading.Thread(target=self._keep_watching, daemon=True,
                                          name="window-stall-watch")

    def start(self) -> None:
        self._watching.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._watching.is_alive():
            self._watching.join()

    def watching(self) -> bool:
        return self._watching.is_alive()

    def watch_once(self) -> None:
        asked_at, asked_on_the_wall = self._clock(), self._wall()
        if not self._window.answers_within(LATE_AFTER_S):
            if self._stall is None:
                self._stall = _Stall(asked_at, asked_on_the_wall,
                                     LooksAtAThread(self._window_thread, frames=self._frames))
            self._stall.looks.look()
            return
        now = self._clock()
        if self._stall is not None:
            self._note_the_stall(now - self._stall.began)
            self._stall = None
        if now - self._minute.began >= A_MINUTE_S:
            self._minute.sum_up(now)
            self._minute = _Minute(began=now)
        self._pause(ASKED_AGAIN_AFTER_S)

    def _keep_watching(self) -> None:
        try:
            while not self._stopped.is_set():
                self.watch_once()
        except OSError:
            logger.warning("Window stalls: the window it asks went away, so no more are written")

    def _note_the_stall(self, lasted: float) -> None:
        self._minute.stalls.append(lasted)
        if len(self._minute.stalls) > STALL_LINES_A_MINUTE:
            return
        began = datetime.fromtimestamp(self._stall.began_on_the_wall, UTC).astimezone()
        logger.info("Window stall: %.2f s without answering, from %s; %s", lasted,
                    began.strftime("%H:%M:%S.%f")[:-3],
                    self._stall.looks.said_in_one_line(most=FUNCTIONS_NAMED_IN_A_STALL))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def watch_the_window(app, crash_log, timing: Timing = USUAL_TIMING) -> FreezeWatch:
    stalls = StallRecord(AnsweringWindow(), threading.get_ident())
    watch = FreezeWatch(crash_log, timing=timing, stalls=stalls, parent=app)
    stalls.start()
    logger.info("Window stalls: each over %.1f s is written, %d a minute at most, and a minute "
                "that had one ends in a line summing them up", LATE_AFTER_S, STALL_LINES_A_MINUTE)
    app.lastWindowClosed.connect(watch.end_the_process_if_the_close_sticks)
    return watch
