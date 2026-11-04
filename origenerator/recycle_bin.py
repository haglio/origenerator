from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

_DELETE = 3
ALLOW_UNDO = 0x0040
_NO_CONFIRMATION = 0x0010
_SILENT = 0x0004
_ASK_BEFORE_DELETING_FOR_GOOD = 0x4000


class _ShellFileOperation(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR)]


def _windows_shell(to_delete: str, flags: int, *, shell_call=None) -> int:
    operation = _ShellFileOperation(wFunc=_DELETE, pFrom=to_delete, fFlags=flags)
    call = shell_call or ctypes.windll.shell32.SHFileOperationW
    refused = call(ctypes.byref(operation))
    return refused or int(bool(operation.fAnyOperationsAborted))


def send_to_recycle_bin(path: Path, *, shell=_windows_shell) -> None:
    refused = shell(f"{path}\0\0", ALLOW_UNDO | _NO_CONFIRMATION | _SILENT
                    | _ASK_BEFORE_DELETING_FOR_GOOD)
    if refused:
        raise OSError(f"Windows would not move {path} to the Recycle Bin (code {refused}).")
