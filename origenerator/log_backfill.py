"""Recover generation times for past runs from ComfyUI's console logs.

ComfyUI logs a ``Prompt executed in X.XX seconds`` line (with a wall-clock
timestamp) after every prompt, but never names the output file, so a log line
can only be tied back to a generation by *when* it happened: the line is
written the instant the output file lands. This module parses those lines and
matches each one to the imported row whose file mtime sits closest in time.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_LINE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\] Prompt executed in ([\d.]+) seconds"
)

# How far a log line's timestamp may sit from a file's mtime and still be taken
# as the same generation. The line is written moments after the file lands, so
# a small window is plenty while keeping distinct runs from cross-matching.
MATCH_TOLERANCE_SECONDS = 120.0


def parse_log_durations(text: str) -> list[tuple[float, float]]:
    """Extract ``(epoch_seconds, duration_seconds)`` for each executed prompt.

    The log timestamp is naive local time (as ComfyUI writes it); converting it
    through ``datetime.timestamp()`` yields an absolute epoch comparable to a
    file's mtime.
    """
    entries = []
    for stamp, duration in _LINE.findall(text):
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f")
        entries.append((when.timestamp(), float(duration)))
    return entries


def _completed_epoch(completed_at: str | None) -> float | None:
    if not completed_at:
        return None
    try:
        return datetime.fromisoformat(completed_at).timestamp()
    except ValueError:
        return None


def backfill_durations_from_logs(db, log_paths) -> int:
    """Fill in ``duration_seconds`` for completed rows that lack one.

    Each candidate row is paired with the closest-in-time log line within
    ``MATCH_TOLERANCE_SECONDS``; matching is greedy nearest-first and
    one-to-one, so no line is reused and the best fits win. Returns the number
    of rows updated.
    """
    entries = []
    for path in log_paths:
        try:
            entries.extend(parse_log_durations(
                Path(path).read_text(encoding="utf-8", errors="replace")))
        except OSError as e:
            logger.warning("Could not read ComfyUI log %s: %s", path, e)
    if not entries:
        return 0

    candidates = []
    for row in db.completed_without_duration():
        row_epoch = _completed_epoch(row.get("completed_at"))
        if row_epoch is None:
            continue
        for index, (entry_epoch, duration) in enumerate(entries):
            delta = abs(entry_epoch - row_epoch)
            if delta <= MATCH_TOLERANCE_SECONDS:
                candidates.append((delta, row["prompt_id"], index, duration))

    candidates.sort(key=lambda c: c[0])
    used_rows: set[str] = set()
    used_entries: set[int] = set()
    matched = 0
    for _delta, prompt_id, index, duration in candidates:
        if prompt_id in used_rows or index in used_entries:
            continue
        db.update_generation(prompt_id, duration_seconds=duration)
        used_rows.add(prompt_id)
        used_entries.add(index)
        matched += 1
    return matched
