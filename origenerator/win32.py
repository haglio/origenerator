"""Win32 helpers for Origenerator taskbar identity and shortcut AUMID stamping.

Clicking a pinned taskbar shortcut only activates the running window if the
shortcut's ``System.AppUserModel.ID`` property matches the AppUserModelID the
process sets for itself. ``WScript.Shell`` (how the launcher .lnk was created)
cannot write that property, so Windows treats the launched window as a separate
app and pops a second taskbar button. ``stamp_pinned_shortcuts`` writes the
property onto the pinned shortcut via COM so the two collapse into one button.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import uuid
from pathlib import Path

_shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
_ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
# HWND/HANDLE argtypes declared so ctypes passes them as 64-bit pointers rather
# than truncating to c_int -- the same rule fun_time/win32.py follows.
_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.c_bool
_kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

APP_USER_MODEL_ID = "FunTime.Origenerator"


def set_app_user_model_id(app_id: str) -> None:
    """Set the AppUserModelID for the current process.

    Must be called before any windows are created so the taskbar groups
    the process's windows under the correct pinned shortcut / icon.
    """
    hr = _shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    if hr < 0:
        raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: HRESULT 0x{hr:08x}")


# --- COM helpers for shortcut AUMID stamping ---

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_ALL = 0x17


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _make_guid(s: str) -> GUID:
    u = uuid.UUID(s)
    return GUID(u.time_low, u.time_mid, u.time_hi_version,
                (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


PKEY_AppUserModel_ID = PROPERTYKEY(
    _make_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5
)

VT_LPWSTR = 31


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", ctypes.wintypes.LPWSTR),
        ("_pad", ctypes.c_void_p),
    ]


CLSID_ShellLink = _make_guid("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = _make_guid("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = _make_guid("0000010B-0000-0000-C000-000000000046")
IID_IPropertyStore = _make_guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")

STGM_READWRITE = 0x00000002
_VTBL_QI = 0
_VTBL_RELEASE = 2
_VTBL_IPF_LOAD = 5
_VTBL_IPF_SAVE = 6
_VTBL_IPS_SET_VALUE = 6
_VTBL_IPS_COMMIT = 7


def _vtbl_call(obj_addr: int, index: int, restype: type, *argtypes: type):
    vtbl = ctypes.c_void_p.from_address(obj_addr).value
    func_ptr = ctypes.c_void_p.from_address(
        vtbl + index * ctypes.sizeof(ctypes.c_void_p)
    ).value
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(func_ptr)


def _release(obj_addr: int) -> None:
    _vtbl_call(obj_addr, _VTBL_RELEASE, ctypes.c_ulong)(obj_addr)


def _query_interface(obj_addr: int, iid: GUID) -> int:
    out = ctypes.c_void_p()
    hr = _vtbl_call(obj_addr, _VTBL_QI, ctypes.HRESULT,
                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
        obj_addr, ctypes.byref(iid), ctypes.byref(out))
    if hr < 0:
        raise OSError(f"QueryInterface failed: HRESULT 0x{hr:08x}")
    return out.value


def set_shortcut_app_user_model_id(lnk_path: str, app_id: str) -> None:
    """Set the AppUserModelID property on a .lnk shortcut file."""
    _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        _set_lnk_aumid(lnk_path, app_id)
    finally:
        _ole32.CoUninitialize()


def _set_lnk_aumid(lnk_path: str, app_id: str) -> None:
    shell_link = ctypes.c_void_p()
    hr = _ole32.CoCreateInstance(
        ctypes.byref(CLSID_ShellLink), None, CLSCTX_ALL,
        ctypes.byref(IID_IShellLinkW), ctypes.byref(shell_link),
    )
    if hr < 0:
        raise OSError(f"CoCreateInstance(ShellLink) failed: HRESULT 0x{hr:08x}")
    try:
        persist_file = _query_interface(shell_link.value, IID_IPersistFile)
        try:
            hr = _vtbl_call(persist_file, _VTBL_IPF_LOAD,
                            ctypes.HRESULT, ctypes.wintypes.LPCWSTR, ctypes.c_ulong)(
                persist_file, lnk_path, STGM_READWRITE)
            if hr < 0:
                raise OSError(f"IPersistFile::Load failed: HRESULT 0x{hr:08x}")

            prop_store = _query_interface(shell_link.value, IID_IPropertyStore)
            try:
                pv = PROPVARIANT()
                pv.vt = VT_LPWSTR
                pv.pwszVal = app_id

                hr = _vtbl_call(prop_store, _VTBL_IPS_SET_VALUE,
                                ctypes.HRESULT,
                                ctypes.POINTER(PROPERTYKEY),
                                ctypes.POINTER(PROPVARIANT))(
                    prop_store,
                    ctypes.byref(PKEY_AppUserModel_ID),
                    ctypes.byref(pv))
                if hr < 0:
                    raise OSError(f"IPropertyStore::SetValue failed: HRESULT 0x{hr:08x}")

                hr = _vtbl_call(prop_store, _VTBL_IPS_COMMIT, ctypes.HRESULT)(prop_store)
                if hr < 0:
                    raise OSError(f"IPropertyStore::Commit failed: HRESULT 0x{hr:08x}")
            finally:
                _release(prop_store)

            hr = _vtbl_call(persist_file, _VTBL_IPF_SAVE,
                            ctypes.HRESULT, ctypes.wintypes.LPCWSTR, ctypes.wintypes.BOOL)(
                persist_file, lnk_path, True)
            if hr < 0:
                raise OSError(f"IPersistFile::Save failed: HRESULT 0x{hr:08x}")
        finally:
            _release(persist_file)
    finally:
        _release(shell_link.value)


def stamp_pinned_shortcuts(app_id: str, *, include: str) -> None:
    """Stamp pinned taskbar shortcuts whose name contains *include* with *app_id*.

    Searches the user's taskbar pin directory for ``*.lnk`` files whose stem
    (lowered) contains *include* and writes *app_id* as their AppUserModelID.
    Failures are logged, never fatal — a missing pin dir or an unstampable
    shortcut must not stop the app from launching.
    """
    _log = logging.getLogger(__name__)
    appdata = os.environ.get("APPDATA", "")
    pin_dir = Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"
    if not pin_dir.is_dir():
        return
    for lnk in pin_dir.glob("*.lnk"):
        if include not in lnk.stem.lower():
            continue
        try:
            set_shortcut_app_user_model_id(str(lnk), app_id)
            _log.info("Stamped AppUserModelID on %s", lnk)
        except OSError as exc:
            _log.warning("Could not stamp AppUserModelID on %s: %s", lnk, exc)


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

    A handle outlives the window it named — closing the window leaves the number
    behind — so anything that must reach *that* window and no other asks first.
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
    # SWP_NOZORDER | SWP_NOACTIVATE: banding and focus belong to whoever asked
    # for them, and a move must not quietly take either.
    return bool(_user32.SetWindowPos(ctypes.c_void_p(hwnd), None,
                                     int(x), int(y), int(width), int(height),
                                     0x0004 | 0x0010))


def force_foreground_window(hwnd: int) -> bool:
    """Take the foreground for *hwnd* from a process that does not hold it.

    Windows refuses ``SetForegroundWindow`` outright unless the calling process
    owns the foreground window or received the last input event, and by the time
    a launch has finished its boot work the user has clicked into something else,
    so Origenerator is neither. The refusal is silent — it flashes the taskbar
    button and leaves the window sitting behind whatever they moved on to, which
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
