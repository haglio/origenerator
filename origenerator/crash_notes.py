from __future__ import annotations

from datetime import UTC, datetime

_crash_log: list = []


def write_notes_to(crash_log) -> None:
    _crash_log[:] = [crash_log]


def note(said: str) -> None:
    if not _crash_log:
        return
    now = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    try:
        _crash_log[0].write(f"=== {now} {said} ===\n")
        _crash_log[0].flush()
    except (OSError, ValueError):
        pass
