from __future__ import annotations

import threading
from collections.abc import Callable

from origenerator.boot_passes import (
    MAINTENANCE,
    Library,
    asking_comfyui,
    run_maintenance,
    without_comfyui,
)
from origenerator.gui import job_queue
from origenerator.gui.off_thread import run_off_thread

DID_NOT_COME_UP = ("ComfyUI did not come up behind the window; the runs in flight at launch "
                   "are left for the next launch to reconnect")


class WorkBehindTheWindow:
    def __init__(self) -> None:
        self._tidying: threading.Thread | None = None

    def tidy(self, work, done, *, owner) -> None:
        self._tidying = run_off_thread(work, done, owner=owner, waits_long=True)

    def wait_for_the_tidying(self) -> None:
        if self._tidying is not None:
            self._tidying.join()


def finish_core_behind_the_window(library: Library, logger, *, owner,
                                  tidied: Callable[[], None],
                                  then: Callable[[], None],
                                  behind: WorkBehindTheWindow | None = None) -> None:
    behind = behind or WorkBehindTheWindow()

    def came_up(up) -> None:
        if not up:
            logger.warning(DID_NOT_COME_UP)
            return
        run_maintenance(library, asking_comfyui(MAINTENANCE), logger.info, logger)
        then()

    def bring_comfyui_up() -> bool:
        bring_up = job_queue.BRING_UP_COMFYUI
        return bring_up is not None and bring_up()

    def the_library_is_tidy(_nothing) -> None:
        tidied()
        run_off_thread(bring_comfyui_up, came_up, owner=owner, waits_long=True)

    behind.tidy(
        lambda: run_maintenance(library, without_comfyui(MAINTENANCE), logger.info, logger),
        the_library_is_tidy, owner=owner)
