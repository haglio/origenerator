"""The one claim on the graphics card every LoRA trainer on this computer takes
before it uses the card: a file naming who holds it, read by both trainer
programs and by his hand scripts beside them, stale once its holder has died."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path

CLAIM = Path.home() / ".haglio" / "graphics_card_claim.json"
_STILL_ACTIVE = 259
_QUERY_LIMITED_INFORMATION = 0x1000


def alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == _STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def _read(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        read = json.loads(text)
    except ValueError:
        return {}
    return read if isinstance(read, dict) else {}


def take(holder: str, pid: int, path: Path | None = None) -> bool:
    path = path or CLAIM
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            opened = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = _read(path)
            if existing is None:
                continue
            if existing.get("pid") == pid:
                return True
            if alive(existing.get("pid")):
                return False
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(opened, "w", encoding="utf-8") as claim:
            json.dump({"holder": holder, "pid": pid, "since": time.time()}, claim)
        return True


def held_by_another(pid: int, path: Path | None = None) -> bool:
    existing = _read(path or CLAIM)
    return existing is not None and existing.get("pid") != pid and alive(existing.get("pid"))


def release(pid: int, path: Path | None = None) -> None:
    path = path or CLAIM
    existing = _read(path)
    if existing is not None and existing.get("pid") == pid:
        path.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    verb, *words = argv
    if verb == "take":
        holder, pid, *path = words
        return 0 if take(holder, int(pid), *map(Path, path)) else 1
    pid, *path = words
    if verb == "held-by-another":
        return 0 if held_by_another(int(pid), *map(Path, path)) else 1
    release(int(pid), *map(Path, path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
