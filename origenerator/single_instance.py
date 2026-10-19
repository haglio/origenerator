from __future__ import annotations

import ctypes
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from app_support.win32 import is_mutex_held, mutex_name, try_acquire_mutex

logger = logging.getLogger(__name__)

LOOK_EVERY_S = 0.1
GIVE_UP_AFTER_S = 60.0


class LibraryClaim:
    def __init__(self, handle: int, closing: str) -> None:
        self._handles = [handle]
        self._closing = closing

    def closes_with(self, app) -> None:
        app.aboutToQuit.connect(self._say_it_is_closing)

    def _say_it_is_closing(self) -> None:
        handle = try_acquire_mutex(self._closing)
        if handle is not None:
            self._handles.append(handle)
        logger.info("Closing: a launch now waits for this copy to let go of the library")

    def let_go(self) -> None:
        while self._handles:
            let_go_of(self._handles.pop(0))
        logger.info("Let go of the library")


def let_go_of(held: int) -> None:
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(held))


class Copies:
    def __init__(self, state_dir: Path) -> None:
        identity = os.path.normcase(os.path.realpath(state_dir))
        self._holding = mutex_name("Global\\Origenerator", identity)
        self._closing = mutex_name("Global\\Origenerator.closing", identity)

    def claim_the_library(self) -> LibraryClaim | None:
        handle = try_acquire_mutex(self._holding)
        return None if handle is None else LibraryClaim(handle, self._closing)

    def one_holds_the_library(self) -> bool:
        return is_mutex_held(self._holding)

    def one_is_closing(self) -> bool:
        return is_mutex_held(self._closing)

    def claim_the_library_once_the_closing_one_lets_go(
            self, *, sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic) -> LibraryClaim | None:
        give_up_at = clock() + GIVE_UP_AFTER_S
        while True:
            closing = self.one_is_closing()
            claim = self.claim_the_library()
            if claim is not None or not closing or clock() >= give_up_at:
                return claim
            sleep(LOOK_EVERY_S)


def say_another_copy_is_running() -> None:
    from PyQt6.QtWidgets import QMessageBox  # noqa: PLC0415

    QMessageBox.information(None, "Origenerator", "Another copy of Origenerator is already running.")
