from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app_support.win32 import window_exists

_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
# Declared so ctypes passes HWND/HANDLE as 64-bit pointers rather than truncating them to c_int.
_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.c_bool
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010

# Windows groups the taskbar by it and prints it over this app's toasts.
APP_USER_MODEL_ID = "Origenerator"


def _write_string_values(key_path: str, values: dict[str, str]) -> None:
    import winreg  # noqa: PLC0415 (raises off Windows)

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register_toast_identity(app_id: str, *, name: str, icon: Path,
                                   write=_write_string_values) -> None:
    try:
        write(rf"Software\Classes\AppUserModelId\{app_id}",
              {"DisplayName": name, "IconUri": str(icon)})
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not register the toast identity: %s", exc)


def register_link_handler(scheme: str, *, name: str, command: str,
                          write=_write_string_values) -> None:
    try:
        write(rf"Software\Classes\{scheme}", {"": f"URL:{name}", "URL Protocol": ""})
        write(rf"Software\Classes\{scheme}\shell\open\command", {"": command})
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not register the link handler: %s", exc)


def place_window_in_device_pixels(hwnd: int, x: int, y: int,
                                  width: int, height: int) -> bool:
    # Not Qt's setGeometry: with QT_SCALE_FACTOR below 1 the screens' logical rects overlap, so a
    # logical x is read against the wrong screen. SetWindowPos takes device pixels, used verbatim.
    if not window_exists(hwnd):
        return False
    if _user32.IsIconic(hwnd):
        return _place_where_it_comes_back(hwnd, x, y, width, height)
    return bool(_user32.SetWindowPos(ctypes.c_void_p(hwnd), None,
                                     int(x), int(y), int(width), int(height),
                                     _SWP_NOZORDER | _SWP_NOACTIVATE))


class _WindowPlacement(ctypes.Structure):
    _fields_ = [("length", ctypes.wintypes.UINT), ("flags", ctypes.wintypes.UINT),
                ("showCmd", ctypes.wintypes.UINT), ("ptMinPosition", ctypes.wintypes.POINT),
                ("ptMaxPosition", ctypes.wintypes.POINT),
                ("rcNormalPosition", ctypes.wintypes.RECT)]


_user32.IsIconic.argtypes = [ctypes.wintypes.HWND]
_user32.IsIconic.restype = ctypes.wintypes.BOOL
for _placement_call in (_user32.GetWindowPlacement, _user32.SetWindowPlacement):
    _placement_call.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(_WindowPlacement)]
    _placement_call.restype = ctypes.wintypes.BOOL
_SW_SHOWMINNOACTIVE = 7
_WPF_RESTORETOMAXIMIZED = 0x0002


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.wintypes.DWORD), ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.wintypes.DWORD)]


_user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]
_user32.MonitorFromPoint.restype = ctypes.wintypes.HMONITOR
_user32.GetMonitorInfoW.argtypes = [ctypes.wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
_user32.GetMonitorInfoW.restype = ctypes.wintypes.BOOL
_MONITOR_DEFAULTTONEAREST = 2


def _work_area_inset(x: int, y: int) -> tuple[int, int]:
    info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
    monitor = _user32.MonitorFromPoint(ctypes.wintypes.POINT(int(x), int(y)),
                                       _MONITOR_DEFAULTTONEAREST)
    if not _user32.GetMonitorInfoW(monitor, ctypes.pointer(info)):
        return 0, 0
    return info.rcWork.left - info.rcMonitor.left, info.rcWork.top - info.rcMonitor.top


def _place_where_it_comes_back(hwnd: int, x: int, y: int, width: int, height: int) -> bool:
    found = _WindowPlacement(length=ctypes.sizeof(_WindowPlacement))
    if not _user32.GetWindowPlacement(hwnd, ctypes.pointer(found)):
        return False
    inset_x, inset_y = _work_area_inset(x, y)
    left, top = int(x) - inset_x, int(y) - inset_y
    placement = _WindowPlacement(
        length=found.length, flags=found.flags & ~_WPF_RESTORETOMAXIMIZED,
        showCmd=_SW_SHOWMINNOACTIVE, ptMinPosition=found.ptMinPosition,
        ptMaxPosition=found.ptMaxPosition,
        rcNormalPosition=ctypes.wintypes.RECT(left, top, left + int(width), top + int(height)))
    return bool(_user32.SetWindowPlacement(hwnd, ctypes.pointer(placement)))


_dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
_dwmapi.DwmSetWindowAttribute.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.DWORD, ctypes.c_void_p, ctypes.wintypes.DWORD,
]
_dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
_DWMWA_CLOAK = 13


def _cloak(hwnd: int, hidden: bool) -> None:
    flag = ctypes.wintypes.BOOL(hidden)
    _dwmapi.DwmSetWindowAttribute(hwnd, _DWMWA_CLOAK, ctypes.pointer(flag),
                                  ctypes.sizeof(flag))


def keep_out_of_sight(hwnd: int) -> None:
    # Windows' DWM still composites a cloaked window, so a frame can still be published.
    if window_exists(hwnd):
        _cloak(hwnd, True)


def bring_back_into_sight(hwnd: int) -> None:
    if window_exists(hwnd):
        _cloak(hwnd, False)


@contextmanager
def out_of_sight(hwnd: int) -> Iterator[None]:
    keep_out_of_sight(hwnd)
    try:
        yield
    finally:
        bring_back_into_sight(hwnd)


def raise_window_without_activating(hwnd: int) -> bool:
    if not window_exists(hwnd):
        return False
    return bool(_user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
                                     _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE))
