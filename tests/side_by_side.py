from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

_THIS_PROCESS = wintypes.HANDLE(-1)


def run_behind_what_he_is_using() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetPriorityClass(_THIS_PROCESS, subprocess.BELOW_NORMAL_PRIORITY_CLASS)
