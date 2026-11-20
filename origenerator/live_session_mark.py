from __future__ import annotations

import ctypes
import os

LIVE_SESSION = "Local\\Haglio.LiveSession"
_SYNCHRONIZE = 0x00100000


def is_live() -> bool:
    if os.name != "nt" or not hasattr(ctypes, "WinDLL"):
        return False
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenMutexW(_SYNCHRONIZE, False, LIVE_SESSION)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True
