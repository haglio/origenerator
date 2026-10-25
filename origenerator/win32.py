"""Win32 helpers for Origenerator's taskbar identity and its window on screen.

Clicking a pinned taskbar shortcut only activates the running window if the
shortcut's ``System.AppUserModel.ID`` matches the AppUserModelID the process
claims for itself, ``APP_USER_MODEL_ID`` below; ``app.py`` claims it and stamps
the pin through ``app_support.win32``.  The rest is the window itself: whether it
is still there, where it goes, and taking the foreground for it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
# HWND/HANDLE argtypes declared so ctypes passes them as 64-bit pointers rather
# than truncating to c_int -- the same rule fun_time/win32.py follows.
_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.c_bool
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010

# What this app calls itself to Windows. It is not decoration: the taskbar
# groups by it, and it is the name Windows prints over a notification this app
# raises, so it is this app's name and no one else's. It read
# "FunTime.Origenerator" until the notifications made that visible.
APP_USER_MODEL_ID = "Origenerator"


def _write_string_values(key_path: str, values: dict[str, str]) -> None:
    """Put *values* under *key_path* in HKEY_CURRENT_USER, making the key if new."""
    import winreg  # noqa: PLC0415 (raises off Windows)

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register_notification_identity(app_id: str, *, name: str, icon: Path,
                                   write=_write_string_values) -> None:
    """Say what Windows calls this app over a notification, and what mark
    it draws.

    It takes both from whatever is registered under the AppUserModelID the
    process claims; with nothing registered it prints the id itself beside a
    generic glyph, which is how this app's first notification came out headed
    "FunTime.Origenerator". Written on every launch rather than once, so a mark
    that has moved or been deleted comes back, and never fatal.
    """
    try:
        write(rf"Software\Classes\AppUserModelId\{app_id}",
              {"DisplayName": name, "IconUri": str(icon)})
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not register the notification identity: %s", exc)


def register_link_handler(scheme: str, *, name: str, command: str,
                          write=_write_string_values) -> None:
    """Say what Windows runs to follow a link of this app's.

    A notification carries a link rather than a way back to the process that
    raised it, because it outlives that process (:mod:`origenerator.app_link` is
    what Windows runs and why). Written on every launch, and never fatal.
    """
    try:
        write(rf"Software\Classes\{scheme}", {"": f"URL:{name}", "URL Protocol": ""})
        write(rf"Software\Classes\{scheme}\shell\open\command", {"": command})
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not register the link handler: %s", exc)


# argtypes matter on 64-bit: without them ctypes marshals an HWND as a 32-bit
# c_int and truncates the handle.
_user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
_user32.IsWindow.restype = ctypes.wintypes.BOOL


def window_exists(hwnd: int) -> bool:
    """Whether *hwnd* still names a live window.

    A handle outlives the window it named — closing the window does not retire
    the number — so anything that must reach *that* window and no other asks
    first.
    """
    return bool(hwnd) and bool(_user32.IsWindow(hwnd))


def place_window_in_device_pixels(hwnd: int, x: int, y: int,
                                  width: int, height: int) -> bool:
    """Put *hwnd* on exactly this DEVICE rect, whatever Qt is scaled to.

    Qt's own ``setGeometry`` cannot do this in a scaled process on a multi-
    monitor desktop, and the failure is not a rounding error.  With
    ``QT_SCALE_FACTOR`` below 1 the screens' logical rects OVERLAP -- measured
    here, the primary reports logical (0, 0, 3982, 2240) while the second
    monitor's logical origin is 2560, inside it -- and Qt maps a logical point
    through whichever screen's rect contains it.  So a logical x of 3982 was
    read against the second screen and landed 914px too far right, and a logical
    x of 2560 was read against the PRIMARY and landed 914px too far left.  There
    is no logical x that satisfies both readings; the coordinate is genuinely
    ambiguous, so the whole space is the wrong place to say this in.

    Win32 has no such ambiguity: ``SetWindowPos`` is device pixels on the
    virtual desktop, which is the space Fun Time measured these rects in and
    the space it places its own windows in.  So the rects it hands over are
    used verbatim, and nothing is converted at all.

    Call it AFTER the window is shown -- an unrealized window has no handle to
    place, and Qt re-applies its own geometry when it creates one.
    """
    if not window_exists(hwnd):
        return False
    if _user32.IsIconic(hwnd):
        return _place_where_it_comes_back(hwnd, x, y, width, height)
    # Banding and focus belong to whoever asked for them, and a move must not
    # quietly take either.
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
    """Off the monitors, still drawn: DWM composites a cloaked window, so one
    handed to a room in the headset still has a frame to publish."""
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
