"""Is the GPU already working for someone else?

The experiment runner yields to *any* GPU load it didn't create — Evolver's
ambient upscaler, a game, a manual ComfyUI run — by asking ``nvidia-smi`` for
the current compute utilization before each launch. Deliberately app-agnostic:
no cross-app protocol, just "is the card busy right now". A machine without
``nvidia-smi`` (or a probe that fails) reads as idle, so experiments still run
there rather than being silently disabled forever.
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

# Compute utilization at or above this counts as "someone is using the GPU".
DEFAULT_BUSY_THRESHOLD = 25

_QUERY = ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"]
# Windows flashes a console window for every console-tool subprocess unless
# CREATE_NO_WINDOW is passed (the startup ffprobe storm, once).
_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def gpu_busy(threshold_percent: int = DEFAULT_BUSY_THRESHOLD) -> bool:
    """True when any GPU's compute utilization is at or above the threshold.

    False whenever the answer can't be read (no nvidia-smi, a timeout, garbled
    output) — an unprobeable GPU must not stall experiments forever.
    """
    try:
        result = subprocess.run(
            _QUERY, capture_output=True, text=True, timeout=4,
            creationflags=_CREATIONFLAGS,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("GPU probe unavailable (%s); treating the GPU as idle", e)
        return False
    if result.returncode != 0:
        return False
    utilizations = []
    for line in result.stdout.splitlines():
        try:
            utilizations.append(int(line.strip()))
        except ValueError:
            continue
    return bool(utilizations) and max(utilizations) >= threshold_percent
