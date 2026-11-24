from __future__ import annotations

import ctypes
import sys

from app_support.threading_utils import wait_until

from origenerator.unseen_desktop import start_unseen

_WRITE_THE_DESKTOP_IT_RUNS_ON = """
import ctypes, sys
from ctypes import wintypes
user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
user32.GetThreadDesktop.restype = wintypes.HANDLE
user32.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
name = ctypes.create_unicode_buffer(256)
user32.GetUserObjectInformationW(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()), 2, name,
                                 ctypes.sizeof(name), None)
with open(sys.argv[1] + ".writing", "w", encoding="utf-8") as written:
    written.write(name.value)
import os
os.replace(sys.argv[1] + ".writing", sys.argv[1])
if len(sys.argv) > 2:
    import time
    while True:
        time.sleep(1)
"""


def _started(tmp_path, *more):
    told = tmp_path / "desktop.txt"
    started = start_unseen([sys._base_executable, "-c", _WRITE_THE_DESKTOP_IT_RUNS_ON,
                            str(told), *more])
    wait_until(told.exists)
    return started, told.read_text(encoding="utf-8")


def test_a_program_started_unseen_runs_on_a_desktop_that_is_not_the_one_on_screen(tmp_path):
    started, desktop = _started(tmp_path)

    wait_until(lambda: not started.is_running())
    started.end()
    assert desktop.startswith("Origenerator")


def test_ending_a_program_started_unseen_stops_it(tmp_path):
    started, _desktop = _started(tmp_path, "stay")
    assert started.is_running()

    started.end()

    wait_until(lambda: not _is_alive(started.pid))


def _is_alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    still = kernel32.WaitForSingleObject(handle, 0) != 0
    kernel32.CloseHandle(handle)
    return still
