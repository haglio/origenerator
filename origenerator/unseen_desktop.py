from __future__ import annotations

import ctypes
import subprocess
import uuid
from collections.abc import Sequence
from ctypes import wintypes

from app_support.win32 import a_job_ending_with_this_process

_NO_WINDOW = 0x08000000
_SUSPENDED = 0x4
_EVERY_RIGHT = 0x10000000
_STILL_RUNNING = 259


class _StartupInfo(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    )


class _ProcessInformation(ctypes.Structure):
    _fields_ = (("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD))


def _windows():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID)
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = (wintypes.HANDLE,)
    kernel32.CreateProcessW.argtypes = (
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL,
        wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInformation))
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return user32, kernel32


class StartedUnseen:
    def __init__(self, user32, kernel32, desktop, started: _ProcessInformation):
        self._user32, self._kernel32, self._desktop, self._started = user32, kernel32, desktop, started
        self.pid = started.dwProcessId
        self._everything_it_starts = a_job_ending_with_this_process(started.hProcess)
        kernel32.ResumeThread(started.hThread)

    def is_running(self) -> bool:
        code = wintypes.DWORD()
        self._kernel32.GetExitCodeProcess(self._started.hProcess, ctypes.byref(code))
        return code.value == _STILL_RUNNING

    def end(self) -> None:
        if self._desktop is None:
            return
        with self._everything_it_starts as job:
            job.end_all()
        self._kernel32.CloseHandle(self._started.hThread)
        self._kernel32.CloseHandle(self._started.hProcess)
        self._user32.CloseDesktop(self._desktop)
        self._desktop = None


def start_unseen(command: Sequence[str]) -> StartedUnseen:
    user32, kernel32 = _windows()
    name = "Origenerator" + uuid.uuid4().hex
    desktop = user32.CreateDesktopW(name, None, None, 0, _EVERY_RIGHT, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    startup = _StartupInfo(cb=ctypes.sizeof(_StartupInfo), lpDesktop=name)
    started = _ProcessInformation()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
    if not kernel32.CreateProcessW(None, line, None, None, False, _NO_WINDOW | _SUSPENDED, None, None,
                                   ctypes.byref(startup), ctypes.byref(started)):
        refused = ctypes.WinError(ctypes.get_last_error())
        user32.CloseDesktop(desktop)
        raise refused
    return StartedUnseen(user32, kernel32, desktop, started)
