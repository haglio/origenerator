"""The recovery bin — deleted generations held long enough to change your mind.

Deleting a generation moves its files into the trash and drops its row (see
:class:`~origenerator.gallery_actions.GalleryActions`), which the session's undo
stack can reverse. That hold used to end at the next launch, when the whole trash
was cleared; here it lasts :data:`RETENTION_DAYS`, because the delete also
records the row it dropped and the batch its files went into. The gallery's Trash
shelf lists those records, puts one back, or ends one early, and :func:`sweep`
clears whatever has outlived the window at the next launch.

A record is the whole story of one delete — ``{"prompt_id", "row", "batch",
"deleted_at"}``, as :meth:`origenerator.db.Database.list_deletions` returns it —
so nothing about a deleted item has to be reconstructed from the disk. This
module is pure data over the database and the trash, with no Qt dependency, so
the retention arithmetic can be unit-tested directly.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from origenerator.trash import TrashedBatch

RETENTION_DAYS = 60
_SECONDS_PER_DAY = 86400


def _now() -> datetime:
    """Now in the frame sqlite stamps a deletion in: UTC, without a timezone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _deleted_at(record: dict) -> datetime | None:
    """When ``record``'s delete happened, or ``None`` if its stamp won't parse."""
    stamp = (record.get("deleted_at") or "").strip()
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def days_left(record: dict, now: datetime | None = None,
              retention_days: int = RETENTION_DAYS) -> int:
    """Whole days ``record`` has before the sweep takes it, rounded up.

    Rounded up so an item with hours to go still reads as having a day rather
    than as already gone. A record whose stamp won't parse is reported as newly
    deleted, which means it never ages out: the failure of a clock must not be
    what destroys files, and a record stuck in the bin is at least visible and
    removable by hand.
    """
    when = _deleted_at(record)
    if when is None:
        return retention_days
    remaining = (when + timedelta(days=retention_days)) - (now or _now())
    return max(0, math.ceil(remaining.total_seconds() / _SECONDS_PER_DAY))


def is_expired(record: dict, now: datetime | None = None,
               retention_days: int = RETENTION_DAYS) -> bool:
    """True once ``record`` has outlived its window and is due to be purged."""
    return days_left(record, now, retention_days) <= 0


def bin_items(records, now: datetime | None = None,
              retention_days: int = RETENTION_DAYS) -> list[dict]:
    """The held deletions as gallery rows the Trash shelf can draw, newest first.

    Each is the row exactly as it was deleted — so its media type, its star and
    its caption read the way they did in the gallery — with two additions: the
    thumbnail is re-pointed at where that file actually sits now, inside the
    trash, and ``days_left`` says how long the item has before it is taken.
    """
    now = now or _now()
    return [_bin_item(record, now, retention_days) for record in records]


def _bin_item(record: dict, now: datetime, retention_days: int) -> dict:
    row = dict(record.get("row") or {})
    row["prompt_id"] = record["prompt_id"]
    thumbnail = row.get("thumbnail_path")
    if thumbnail:
        row["thumbnail_path"] = _trashed_path(record, thumbnail)
    row["deleted_at"] = record.get("deleted_at")
    row["days_left"] = days_left(record, now, retention_days)
    return row


def _trashed_path(record: dict, original: str) -> str:
    """Where ``original`` sits now that it has been trashed — or the path itself,
    unchanged, when the delete moved nothing (a branch session takes no files)."""
    for moved_from, moved_to in (record.get("batch") or {}).get("moves") or []:
        if Path(moved_from) == Path(original):
            return moved_to
    return original


def restore(db, record: dict) -> str:
    """Put one held deletion back: its files return to the paths they were taken
    from and its row rejoins the gallery verbatim. Returns the restored
    prompt_id, so a caller can navigate to what it brought back."""
    TrashedBatch.from_record(record.get("batch") or {}).restore()
    db.restore_generation(record["row"])
    db.forget_deletion(record["prompt_id"])
    return record["prompt_id"]


def purge(db, record: dict) -> None:
    """End one held deletion now: its files are removed and the bin forgets it.

    Irreversible, and there is nothing left to undo it with — the row went when
    the item was deleted, and this takes the only copies of its files.
    """
    TrashedBatch.from_record(record.get("batch") or {}).purge()
    db.forget_deletion(record["prompt_id"])


def sweep(db, trash, *, now: datetime | None = None,
          retention_days: int = RETENTION_DAYS) -> int:
    """Clear what the bin no longer holds, and say how many deletions went.

    Two jobs, both belonging to launch. Every record past its window is purged,
    files and all — this is the "60 days, then it's really gone" half of the
    promise. Then the batch folders of the records that *survived* are handed to
    the trash, which deletes every folder none of them names: what a launch used
    to clear wholesale, now narrowed to only what nothing can reach.
    """
    now = now or _now()
    records = db.list_deletions()
    expired = [record for record in records if is_expired(record, now, retention_days)]
    for record in expired:
        purge(db, record)
    doomed = {record["prompt_id"] for record in expired}
    trash.purge_orphans([
        (record.get("batch") or {}).get("subdir")
        for record in records if record["prompt_id"] not in doomed
    ])
    return len(expired)
