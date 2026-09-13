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
_kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

# What this app calls itself to Windows. It is not decoration: the taskbar
# groups by it, and it is the name Windows prints over a notification this app
# raises, so it is this app's name and no one else's. It read
# "FunTime.Origenerator" until the notifications made that visible.
APP_USER_MODEL_ID = "Origenerator"


def _write_string_values(key_path: str, values: dict[str, str]) -> None:
    """Put *values* under *key_path* in HKEY_CURRENT_USER, making the key if new."""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register_notification_identity(app_id: str, *, name: str, icon: Path,
                                   write=_write_string_values) -> None:
    """Say what Windows calls this app over a notification, and what mark it draws.

    It takes both from whatever is registered under the AppUserModelID the
    process claims. With nothing registered it prints the id itself and falls
    back to a generic glyph — which is how this app's first notification came
    out headed "FunTime.Origenerator" beside an (i). Every app on a desktop
    whose notifications read properly carries these two values, and Windows
    writes them itself for a tray app that claims no id of its own.

    Written on every launch rather than once, so a mark that has moved or been
    deleted comes back. Failures are logged and never fatal: a notification
    with the wrong heading beats a launch that stopped over one.
    """
    try:
        write(rf"Software\Classes\AppUserModelId\{app_id}",
              {"DisplayName": name, "IconUri": str(icon)})
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not register the notification identity: %s", exc)


# --- Taking the foreground for the window this process just opened ---

# argtypes matter on 64-bit: without them ctypes marshals an HWND as a 32-bit
# c_int and truncates the handle. AttachThreadInput takes thread ids rather than
# handles, so its two DWORDs are the whole signature, and the process-id
# out-param of GetWindowThreadProcessId must be a real pointer.
_user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
_user32.IsWindow.restype = ctypes.wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
_user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
_user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
_user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]
_user32.BringWindowToTop.restype = ctypes.wintypes.BOOL
_user32.AttachThreadInput.argtypes = [
    ctypes.wintypes.DWORD,  # idAttach
    ctypes.wintypes.DWORD,  # idAttachTo
    ctypes.wintypes.BOOL,   # fAttach
]
_user32.AttachThreadInput.restype = ctypes.wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [
    ctypes.wintypes.HWND,                   # hWnd
    ctypes.POINTER(ctypes.wintypes.DWORD),  # lpdwProcessId (out)
]
_user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
_kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD


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
    # Banding and focus belong to whoever asked for them, and a move must not
    # quietly take either.
    return bool(_user32.SetWindowPos(ctypes.c_void_p(hwnd), None,
                                     int(x), int(y), int(width), int(height),
                                     _SWP_NOZORDER | _SWP_NOACTIVATE))


def raise_window_without_activating(hwnd: int) -> bool:
    if not window_exists(hwnd):
        return False
    return bool(_user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
                                     _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE))


def force_foreground_window(hwnd: int) -> bool:
    """Take the foreground for *hwnd* from a process that does not hold it.

    Windows refuses ``SetForegroundWindow`` outright unless the calling process
    owns the foreground window or received the last input event, and by the time
    a launch has finished its boot work the user has clicked into something else,
    so Origenerator is neither. The refusal is silent — it flashes the taskbar
    button and leaves the window sitting under whatever they moved on to, which
    is the bug this exists for. Attaching this thread's input queue to the
    foreground window's thread makes the two one queue, and a thread sharing the
    foreground thread's queue is one of the cases the rule accepts, so the call
    goes through.

    Returns whether the window really ended up in the foreground. A False is
    worth logging but not worth acting on: with no foreground window at all
    (an offscreen/headless desktop) there is nothing to be in front of, so this
    reads False there while the activation itself still lands.
    """
    if not window_exists(hwnd):
        return False
    foreground = _user32.GetForegroundWindow()
    this_thread = _kernel32.GetCurrentThreadId()
    other_thread = _user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = bool(
        other_thread
        and other_thread != this_thread
        and _user32.AttachThreadInput(other_thread, this_thread, True)
    )
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(other_thread, this_thread, False)
    return int(_user32.GetForegroundWindow() or 0) == hwnd
