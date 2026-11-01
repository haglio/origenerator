from __future__ import annotations

import logging
import os
import subprocess
import time

from origenerator import card_claim

logger = logging.getLogger(__name__)

GRAPHICS_CARD_MIB_NEEDED = 9000
_POLL_S = 2.0
_ROOM_WAIT_S = 30.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NVIDIA_SMI = ("nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits")


def graphics_card_memory_mib(*, run=None) -> tuple[int, int] | None:
    try:
        done = (run or subprocess.run)([*NVIDIA_SMI], capture_output=True, text=True, timeout=20,
                              creationflags=_NO_WINDOW, check=False)
        free, total = done.stdout.strip().splitlines()[0].split(",")
        return int(free), int(total)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _comfyui_busy(comfyui) -> bool | None:
    try:
        return len(comfyui.fetch_queue()) > 0
    except Exception as e:  # noqa: BLE001 -- not running, or not answering: nothing holds the graphics card
        logger.info("ComfyUI could not be asked what it is making: %s", e)
        return None


def wait_for_the_graphics_card(comfyui, holder: str, *, deadline_s: float = 600.0,
                               claim_path=None, **machine) -> bool:
    needed_mib = machine.get("needed_mib", GRAPHICS_CARD_MIB_NEEDED)
    memory = machine.get("memory", graphics_card_memory_mib)
    clock = machine.get("clock", time.monotonic)
    sleep = machine.get("sleep", time.sleep)
    pid = os.getpid()
    deadline = clock() + deadline_s
    while True:
        busy = _comfyui_busy(comfyui)
        if (not busy and not card_claim.held_by_another(pid, claim_path)
                and card_claim.take(holder, pid, claim_path)):
            break
        if clock() >= deadline:
            logger.info("The graphics card was still ComfyUI's or another program's after %.0f s; the "
                        "model is not loaded", deadline_s)
            return False
        sleep(_POLL_S)
    if busy is None:
        return True
    try:
        comfyui.free_memory()
    except Exception as e:  # noqa: BLE001 -- the model loads with whatever room there is
        logger.info("ComfyUI could not be asked to let go of its models: %s", e)
    room_by = clock() + _ROOM_WAIT_S
    while (reading := memory()) is not None and reading[0] < needed_mib and clock() < room_by:
        sleep(_POLL_S)
    return True


def let_go_of_the_graphics_card(claim_path=None) -> None:
    card_claim.release(os.getpid(), claim_path)
