"""The recovery bin — deleted generations held until you say otherwise.

Deleting a generation moves its files into the trash and drops its row (see
:class:`~origenerator.gallery_actions.GalleryActions`), which the session's undo
stack can reverse. That hold used to end at the next launch, when the whole trash
was cleared; here it does not end on its own at all, because the delete also
records the row it dropped and the batch its files went into. The gallery's Trash
shelf lists those records, puts one back, or ends one for good — and ending one
by hand is the only thing that ends one. :func:`reclaim_orphans` is all that is
left for launch to do: clear the batch folders no record names, and leave
everything the bin holds exactly where it is.

A record is the whole story of one delete — ``{"prompt_id", "row", "batch",
"deleted_at"}``, as :meth:`origenerator.db.Database.list_deletions` returns it —
so nothing about a deleted item has to be reconstructed from the disk. This
module is pure data over the database and the trash, with no Qt dependency, so
what the shelf shows can be unit-tested directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from origenerator.gallery.output import parse_file_list
from origenerator.trash import TrashedBatch

_SECONDS_PER_DAY = 86400


def _now() -> datetime:
    """Now in the frame sqlite stamps a deletion in: UTC, without a timezone."""
    return datetime.now(UTC).replace(tzinfo=None)


def _deleted_at(record: dict) -> datetime | None:
    """When ``record``'s delete happened, or ``None`` if its stamp won't parse."""
    stamp = (record.get("deleted_at") or "").strip()
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def days_held(record: dict, now: datetime | None = None) -> int:
    """Whole days ``record`` has been sitting in the trash, rounded down.

    Read as "how long ago did I bin this", which is why it rounds down: an item
    deleted an hour ago has been there no days rather than a whole one. It is a
    fact about the item, not a countdown — nothing acts on it, and a record
    whose stamp won't parse simply reads as freshly deleted.
    """
    when = _deleted_at(record)
    if when is None:
        return 0
    elapsed = ((now or _now()) - when).total_seconds()
    return max(0, int(elapsed // _SECONDS_PER_DAY))


def bin_items(records, now: datetime | None = None) -> list[dict]:
    """The held deletions as gallery rows the Trash shelf can draw, newest first.

    Each is the row exactly as it was deleted — so its media type, its star and
    its caption read the way they did in the gallery — with its files re-pointed
    at where they actually sit now, inside the trash, and ``days_in_trash`` for
    how long it has been there.

    Re-pointing the *output* files, not only the thumbnail, is what makes a
    deleted item as watchable as any other. A bin row is fed to the same preview,
    slideshow and fullscreen machinery every live row goes through, and all of
    that resolves files through
    :func:`~origenerator.gallery.output.output_file_path` — which follows the
    re-pointed path. Left alone, those rows resolve to the folder the files were
    taken out of, so the shelf could offer a stored thumbnail and nothing else:
    no video to play, nothing to open full size.
    """
    now = now or _now()
    return [_bin_item(record, now) for record in records]


def _bin_item(record: dict, now: datetime) -> dict:
    row = dict(record.get("row") or {})
    row["prompt_id"] = record["prompt_id"]
    thumbnail = row.get("thumbnail_path")
    if thumbnail:
        row["thumbnail_path"] = _trashed_path(record, thumbnail)
    row["output_files"] = _trashed_output_files(record, row)
    row["deleted_at"] = record.get("deleted_at")
    row["days_in_trash"] = days_held(record, now)
    return row


def _trashed_output_files(record: dict, row: dict) -> str:
    """``row``'s output files with each one's current location stamped on it.

    The recorded ``filename``/``subfolder`` stay as they were — they say what the
    generation produced and where it lived, which is what the info pane shows —
    and a ``path`` alongside says where that file is right now. A file the batch
    never moved (a branch session's delete takes none) gets no ``path`` and is
    read from its own folder, as before.
    """
    moved = {Path(moved_from).name: moved_to
             for moved_from, moved_to in (record.get("batch") or {}).get("moves") or []}
    files = []
    for f in parse_file_list(row.get("output_files")):
        trashed = moved.get(f.get("filename") or "")
        files.append({**f, "path": trashed} if trashed else f)
    return json.dumps(files)


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


def reclaim_orphans(db, trash) -> int:
    """Clear the trash folders nothing can reach, and say how many went.

    Launch's one piece of housekeeping, and it never takes anything the bin is
    holding: every held record's batch folder is named as one to spare, so what
    is removed is only what no record points at — a rejected experiment's batch
    that fell off the undo stack, a batch from before the bin existed, or a
    folder left behind by a crash between the move and the record. Nothing here
    reads a clock. A held deletion stays until the user restores it or ends it
    from the Trash shelf, however long that takes.
    """
    return trash.purge_orphans([
        (record.get("batch") or {}).get("subdir") for record in db.list_deletions()
    ])
