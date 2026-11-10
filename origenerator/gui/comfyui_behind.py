from __future__ import annotations

from collections.abc import Callable

from origenerator.boot_passes import MAINTENANCE, Library, asking_comfyui, run_maintenance
from origenerator.gui import job_queue
from origenerator.gui.off_thread import run_off_thread

DID_NOT_COME_UP = ("ComfyUI did not come up behind the window; the runs in flight at launch "
                   "are left for the next launch to reconnect")


def bring_comfyui_up_behind_the_window(library: Library, logger, *, owner,
                                       then: Callable[[], None]) -> None:
    def came_up(up) -> None:
        if not up:
            logger.warning(DID_NOT_COME_UP)
            return
        run_maintenance(library, asking_comfyui(MAINTENANCE), logger.info, logger)
        then()

    bring_up = job_queue.BRING_UP_COMFYUI
    if bring_up is None:
        came_up(False)
        return
    run_off_thread(bring_up, came_up, owner=owner, waits_long=True)
