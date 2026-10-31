"""The graphics card handed from ComfyUI to the local model: the two do not fit on
it together, and a model squeezed beside ComfyUI's crawls or dies mid-answer. The
model takes the one claim on the card the trainers take (tools.card_claim), so a
training and the model never take the card together either."""
from __future__ import annotations

import logging
import os
import subprocess
import time

from tools import card_claim

logger = logging.getLogger(__name__)

CARD_MIB_NEEDED = 9000  # 6.6 GB of weights, 1.3 GB for a 40,960-token window, room (2026-10-28)
_POLL_S = 2.0
_ROOM_WAIT_S = 30.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NVIDIA_SMI = ("nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits")


def card_memory_mib() -> tuple[int, int] | None:
    try:
        done = subprocess.run([*NVIDIA_SMI], capture_output=True, text=True, timeout=20,
                              creationflags=_NO_WINDOW)
        free, total = done.stdout.strip().splitlines()[0].split(",")
        return int(free), int(total)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _comfyui_busy(comfyui) -> bool | None:
    try:
        return len(comfyui.fetch_queue()) > 0
    except Exception as e:  # noqa: BLE001 -- not running, or not answering: nothing holds the card
        logger.info("ComfyUI could not be asked what it is making: %s", e)
        return None


def wait_for_the_card(comfyui, holder: str, *, needed_mib: int = CARD_MIB_NEEDED,
                      deadline_s: float = 600.0, memory=None, clock=time.monotonic,
                      sleep=time.sleep, claim_path=None) -> bool:
    memory = memory or card_memory_mib
    pid = os.getpid()
    deadline = clock() + deadline_s
    while True:
        busy = _comfyui_busy(comfyui)
        if (not busy and not card_claim.held_by_another(pid, claim_path)
                and card_claim.take(holder, pid, claim_path)):
            break
        if clock() >= deadline:
            logger.info("The card was still ComfyUI's or another program's after %.0f s; the "
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


def let_go_of_the_card(claim_path=None) -> None:
    card_claim.release(os.getpid(), claim_path)
