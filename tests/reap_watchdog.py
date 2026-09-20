"""When the per-test reap stops coming back, say which native code it sits in.

No debugger is installed here or on the runner, so a watchdog thread suspends
the main thread, reads its stack, and prints every return address that lands
inside a loaded module. It writes to a copy of stderr taken before pytest
redirects it, so the dump reaches the log from inside a test.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes

PATIENCE_S = float(os.environ.get("REAP_PATIENCE", "60"))
_SAVED_STDERR = os.dup(2)
_reap_started = [None]
_current = ["<none>"]
_armed = []

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p),
                                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                       ctypes.c_wchar_p, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenThread.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

PROCESS_ALL_ACCESS = 0x1F0FFF
THREAD_ALL_ACCESS = 0x1FFFFF
TH32CS_SNAPTHREAD = 0x4
CONTEXT_FULL = 0x100000 | 0x1 | 0x2 | 0x8


class M128A(ctypes.Structure):
    _fields_ = [("Low", ctypes.c_ulonglong), ("High", ctypes.c_longlong)]


class CONTEXT(ctypes.Structure):
    _pack_ = 16
    _fields_ = [("P1Home", ctypes.c_ulonglong), ("P2Home", ctypes.c_ulonglong),
                ("P3Home", ctypes.c_ulonglong), ("P4Home", ctypes.c_ulonglong),
                ("P5Home", ctypes.c_ulonglong), ("P6Home", ctypes.c_ulonglong),
                ("ContextFlags", wintypes.DWORD), ("MxCsr", wintypes.DWORD),
                ("SegCs", wintypes.WORD), ("SegDs", wintypes.WORD),
                ("SegEs", wintypes.WORD), ("SegFs", wintypes.WORD),
                ("SegGs", wintypes.WORD), ("SegSs", wintypes.WORD),
                ("EFlags", wintypes.DWORD),
                ("Dr0", ctypes.c_ulonglong), ("Dr1", ctypes.c_ulonglong),
                ("Dr2", ctypes.c_ulonglong), ("Dr3", ctypes.c_ulonglong),
                ("Dr6", ctypes.c_ulonglong), ("Dr7", ctypes.c_ulonglong),
                ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong),
                ("Rdx", ctypes.c_ulonglong), ("Rbx", ctypes.c_ulonglong),
                ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
                ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong),
                ("R8", ctypes.c_ulonglong), ("R9", ctypes.c_ulonglong),
                ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
                ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong),
                ("R14", ctypes.c_ulonglong), ("R15", ctypes.c_ulonglong),
                ("Rip", ctypes.c_ulonglong),
                ("FltSave", ctypes.c_byte * 512),
                ("VectorRegister", M128A * 26), ("VectorControl", ctypes.c_ulonglong),
                ("DebugControl", ctypes.c_ulonglong),
                ("LastBranchToRip", ctypes.c_ulonglong),
                ("LastBranchFromRip", ctypes.c_ulonglong),
                ("LastExceptionToRip", ctypes.c_ulonglong),
                ("LastExceptionFromRip", ctypes.c_ulonglong)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


class MODULEINFO(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", ctypes.c_void_p), ("SizeOfImage", wintypes.DWORD),
                ("EntryPoint", ctypes.c_void_p)]


def _loaded_modules(process):
    handles = (ctypes.c_void_p * 2048)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcessModules(process, handles, ctypes.sizeof(handles),
                                    ctypes.byref(needed)):
        return []
    found = []
    for handle in handles[:needed.value // ctypes.sizeof(ctypes.c_void_p)]:
        name = ctypes.create_unicode_buffer(512)
        psapi.GetModuleFileNameExW(process, ctypes.c_void_p(handle), name, 512)
        info = MODULEINFO()
        psapi.GetModuleInformation(process, ctypes.c_void_p(handle),
                                   ctypes.byref(info), ctypes.sizeof(info))
        base = info.lpBaseOfDll or 0
        found.append((base, base + info.SizeOfImage, name.value.rsplit("\\", 1)[-1]))
    return sorted(found)


def _named(loaded, address):
    for base, end, name in loaded:
        if base <= address < end:
            return f"{name}+0x{address - base:x}"
    return None


def _thread_ids():
    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    mine = os.getpid()
    found = []
    if k32.Thread32First(snapshot, ctypes.byref(entry)):
        while True:
            if entry.th32OwnerProcessID == mine:
                found.append(entry.th32ThreadID)
            if not k32.Thread32Next(snapshot, ctypes.byref(entry)):
                break
    k32.CloseHandle(snapshot)
    return found


def native_stacks(depth=60):
    process = k32.OpenProcess(PROCESS_ALL_ACCESS, False, os.getpid())
    loaded = _loaded_modules(process)
    mine = threading.get_native_id()
    said = []
    for tid in _thread_ids():
        if tid == mine:
            continue
        thread = k32.OpenThread(THREAD_ALL_ACCESS, False, tid)
        if not thread:
            continue
        k32.SuspendThread(thread)
        context = CONTEXT()
        context.ContextFlags = CONTEXT_FULL
        ok = k32.GetThreadContext(thread, ctypes.byref(context))
        frames, rip = [], 0
        if ok:
            rip = context.Rip
            buffer = (ctypes.c_ulonglong * 8192)()
            read = ctypes.c_size_t()
            k32.ReadProcessMemory(process, ctypes.c_void_p(context.Rsp), buffer,
                                  ctypes.sizeof(buffer), ctypes.byref(read))
            seen = set()
            for slot in buffer[:read.value // 8]:
                where = _named(loaded, slot)
                if where and where.split("+")[0] not in seen:
                    seen.add(where.split("+")[0])
                    frames.append(where)
                if len(frames) >= depth:
                    break
        k32.ResumeThread(thread)
        k32.CloseHandle(thread)
        said.append(f"--- thread {tid} rip={_named(loaded, rip) or hex(rip)}")
        said += [f"      {frame}" for frame in frames]
    k32.CloseHandle(process)
    return "\n".join(said)


def _shout(text):
    """Write past pytest's capture, the way pytest-timeout writes its dump."""
    capture = _armed[0] if _armed else None
    if capture is not None:
        capture.suspend_global_capture(in_=False)
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
        os.write(_SAVED_STDERR, text.encode("utf-8", "replace"))
    finally:
        if capture is not None:
            capture.resume_global_capture()


def _watch():
    told = False
    while True:
        time.sleep(5)
        started = _reap_started[0]
        if started is None:
            told = False
            continue
        if time.monotonic() - started > PATIENCE_S and not told:
            told = True
            _shout(f"\n=== the reap after {_current[0]} has run for "
                   f"{time.monotonic() - started:.0f}s ===\n")
            try:
                _shout(native_stacks() + "\n=== end of stacks ===\n")
            except Exception as failure:  # a probe may never cost the run
                _shout(f"native stacks unavailable: {failure!r}\n")


@contextmanager
def watching(nodeid="<none>"):
    """Mark a reap as under way, so the watchdog can tell a stuck one."""
    _current[0] = nodeid
    _reap_started[0] = time.monotonic()
    try:
        yield
    finally:
        _reap_started[0] = None


def arm(config):
    if _armed:
        return
    _armed.append(config.pluginmanager.getplugin("capturemanager"))
    threading.Thread(target=_watch, daemon=True).start()
    _shout(f"[watchdog] armed, patience {PATIENCE_S:.0f}s\n")
