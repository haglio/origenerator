from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_LINE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\] Prompt executed in ([\d.]+) seconds"
)

# ComfyUI writes a "Prompt executed" line moments after the file lands, stamped in local time
# with no zone, and names no file in it.
MATCH_TOLERANCE_SECONDS = 120.0


def parse_log_durations(text: str) -> list[tuple[float, float]]:
    entries = []
    for stamp, duration in _LINE.findall(text):
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f").astimezone()
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
