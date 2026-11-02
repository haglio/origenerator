"""The Trash — deleted generations held until you say otherwise.

Deleting a generation moves its files into the trash and drops its row (see
:class:`~origenerator.gallery_edits.GalleryEdits`), which the session's undo
stack can reverse. That hold does not end on its own at all -- not at the next
launch, not ever -- because the delete also records the row it dropped and the
batch its files went into. The gallery's Trash
collection lists those records, puts one back, or ends one for good — and ending one
by hand is the only thing that ends one. A launch clears the batch folders no record
names (:func:`reclaim_orphans`) and takes every file but the thumbnail from an item
that has waited a day (:func:`empty_what_has_waited_a_day`), and restoring such an
item runs a job that makes it again.

A record is the whole story of one delete — ``{"prompt_id", "row", "batch",
"deleted_at"}``, as :meth:`origenerator.db.Database.list_trashed` returns it —
so nothing about a deleted item has to be reconstructed from the disk. This
module is pure data over the database and the trash, with no Qt dependency, so
what the collection shows can be unit-tested directly.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from origenerator.branch_session import is_branch_session
from origenerator.config import COMFYUI_FOLDERS
from origenerator.file_refs import frame_name
from origenerator.gallery.output import (
    is_in_progress,
    parse_file_list,
    resolve_preview,
    with_files_renamed,
)
from origenerator.gallery.signatures import parse_params
from origenerator.gallery.tree import settings_folder_key
from origenerator.generation_state import GenerationStatus
from origenerator.one_look import is_file
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import leave_out_for_good
from origenerator.regeneration import why_it_cannot_be_made_again
from origenerator.thumbnail import generate_thumbnail
from origenerator.trash import Trash, TrashedBatch
from origenerator.workflows import workflow_named

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400
_WHAT_A_RUN_MADE = ("status", "output_files", "original_files", "enhance_history",
                    "thumbnail_path", "duration_seconds", "completed_at", "workflow_json",
                    "provenance")


def _now() -> datetime:
    """Now in the frame sqlite stamps a trashed item in: UTC, without a timezone."""
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

    Read as "how long ago did I trash this", which is why it rounds down: an item
    deleted an hour ago has been there no days rather than a whole one. A record
    whose stamp won't parse simply reads as freshly deleted.
    """
    when = _deleted_at(record)
    if when is None:
        return 0
    elapsed = ((now or _now()) - when).total_seconds()
    return max(0, int(elapsed // _SECONDS_PER_DAY))


def trash_items(records, now: datetime | None = None) -> list[dict]:
    """The trashed items as gallery rows the Trash collection can draw, newest first.

    Each is the row exactly as it was deleted — so its media type, its star and
    its caption read the way they did in the gallery — with its files re-pointed
    at where they actually sit now, inside the trash, and ``days_in_trash`` for
    how long it has been there.

    Re-pointing the *output* files, not only the thumbnail, is what makes a
    deleted item as watchable as any other. A Trash row is fed to the same preview,
    slideshow and fullscreen machinery every live row goes through, and all of
    that resolves files through
    :func:`~origenerator.gallery.output.output_file_path` — which follows the
    re-pointed path. Left alone, those rows resolve to the folder the files were
    taken out of, so the collection could offer a stored thumbnail and nothing else:
    no video to play, nothing to open full size.
    """
    now = now or _now()
    return [_trash_item(record, now) for record in records
            if not (record.get("batch") or {}).get("regenerating_as")]


def _trash_item(record: dict, now: datetime) -> dict:
    row = dict(record.get("row") or {})
    row["prompt_id"] = record["prompt_id"]
    thumbnail = row.get("thumbnail_path")
    if thumbnail:
        row["thumbnail_path"] = _trashed_path(record, thumbnail)
    row["output_files"] = _trashed_output_files(record, row)
    row["deleted_at"] = record.get("deleted_at")
    row["days_in_trash"] = days_held(record, now)
    row["emptied"] = is_emptied(record)
    return row


def _trashed_output_files(record: dict, row: dict) -> str:
    """``row``'s output files with each one's current location stamped on it.

    The recorded ``filename``/``subfolder`` stay as they were — they say what the
    generation produced and where it lived, which is what the Generate pane shows —
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
    held = TrashedBatch.from_record(record.get("batch") or {}).holding(Path(original))
    return str(held) if held is not None else original


def restore(db, record: dict) -> str:
    """Put one trashed item back: its files return to the paths they were taken
    from, or beside them under a new number where that name is taken, and its
    row rejoins the gallery naming them. Returns the restored prompt_id, so a
    caller can navigate to what it brought back."""
    renamed = TrashedBatch.from_record(record.get("batch") or {}).restore()
    db.restore_generation(with_files_renamed(record["row"], renamed))
    db.forget_trashed(record["prompt_id"])
    return record["prompt_id"]


def purge(db, record: dict) -> None:
    """End one trashed item now: its files are removed and the Trash forgets it.

    Irreversible, and there is nothing left to undo it with — the row went when
    the item was deleted, and this takes the only copies of its files.
    """
    TrashedBatch.from_record(record.get("batch") or {}).purge()
    db.forget_trashed(record["prompt_id"])
    leave_out_for_good(db, record["row"])


def is_emptied(record: dict) -> bool:
    return bool((record.get("batch") or {}).get("emptied"))


def empty_what_has_waited_a_day(db, places: OutputPlaces, now: datetime | None = None) -> int:
    now = now or _now()
    emptied = 0
    still_needed = _start_images_in_the_library(db)
    for record in db.list_trashed():
        moves = (record.get("batch") or {}).get("moves")
        if (is_emptied(record) or days_held(record, now) < 1 or not moves
                or any(frame_name(original) in still_needed for original, _held in moves)):
            continue
        try:
            _empty(db, record, places, now)
            emptied += 1
        except OSError as e:
            logger.warning("Could not empty %s in the Trash: %s", record["prompt_id"], e)
    return emptied


def _start_images_in_the_library(db) -> set[str]:
    names = set()
    for row in db.list_generations():
        workflow = workflow_named(row.get("workflow_name"))
        params = parse_params(row.get("params_json"))
        for key in [key for key, _label in workflow.input_params] if workflow else ["input_image"]:
            names.add(frame_name(params.get(key)))
    return names - {""}


def _empty(db, record: dict, places: OutputPlaces, now: datetime) -> None:
    batch = TrashedBatch.from_record(record["batch"])
    item = _trash_item(record, now)
    row = record["row"]
    kept = item.get("thumbnail_path")
    if not (kept and is_file(kept)):
        kept = _thumbnail_made_from(item, batch, places)
        row = {**row, "thumbnail_path": kept}
    batch.empty(keeping=Path(kept) if kept else None)
    db.record_trashed(record["prompt_id"], row, {**record["batch"], "emptied": True},
                       deleted_at=record["deleted_at"])


def _thumbnail_made_from(item: dict, batch: TrashedBatch, places: OutputPlaces) -> str | None:
    shown = resolve_preview(item, places)
    if shown is None:
        return None
    source, rendered_as = shown
    return str(generate_thumbnail(source, rendered_as, batch.subdir, name="thumbnail"))


def start_regenerating(db, record: dict, job_prompt_id: str) -> None:
    db.record_trashed(record["prompt_id"], record["row"],
                       {**record["batch"], "regenerating_as": job_prompt_id},
                       deleted_at=record["deleted_at"])


def settle_regenerations(db) -> int:
    settled = 0
    for record in db.list_trashed():
        job_prompt_id = (record.get("batch") or {}).get("regenerating_as")
        if job_prompt_id is None:
            continue
        job_row = db.get_generation(job_prompt_id)
        if job_row is not None and is_in_progress(job_row):
            continue
        settled += 1
        if job_row is not None and job_row.get("status") == GenerationStatus.COMPLETED:
            _bring_back_with_the_files_of(db, record, job_row)
        else:
            _back_in_the_trash(db, record, job_row)
    return settled


def _bring_back_with_the_files_of(db, record: dict, job_row: dict) -> None:
    db.delete_generation(job_row["prompt_id"])
    db.restore_generation({**record["row"], **{column: job_row.get(column)
                                               for column in _WHAT_A_RUN_MADE}})
    TrashedBatch.from_record(record["batch"]).purge()
    db.forget_trashed(record["prompt_id"])


def _back_in_the_trash(db, record: dict, job_row: dict | None) -> None:
    if job_row is not None:
        db.delete_generation(job_row["prompt_id"])
    batch = {key: value for key, value in record["batch"].items() if key != "regenerating_as"}
    db.record_trashed(record["prompt_id"], record["row"], batch, deleted_at=record["deleted_at"])


def why_it_cannot_be_restored(item: dict) -> str | None:
    return why_it_cannot_be_made_again(item, COMFYUI_FOLDERS) if item.get("emptied") else None


def restore_action_on(menu, label: str, items: list[dict]):
    action = menu.addAction(label)
    reasons = [why_it_cannot_be_restored(item) for item in items]
    if items and all(reasons):
        menu.setToolTipsVisible(True)
        action.setEnabled(False)
        action.setToolTip(reasons[0])
    return action


def restore_from_trash(db, jobs, prompt_ids, restore_with_files, image_index: dict) -> str | None:
    records = [db.get_trashed(prompt_id) for prompt_id in prompt_ids]
    emptied = [record for record in records if record is not None and is_emptied(record)]
    leaving_as_jobs = {record["prompt_id"] for record in emptied}
    restored = restore_with_files([pid for pid in prompt_ids if pid not in leaving_as_jobs])
    return _regenerate(db, jobs, emptied, image_index) or restored


def _regenerate(db, jobs, records: list[dict], image_index: dict) -> str | None:
    landing = None
    for record in records:
        row = record["row"]
        if why_it_cannot_be_made_again(row, COMFYUI_FOLDERS) is not None:
            continue
        job_prompt_id = jobs.regenerate(settings_folder_key(row, image_index), row)
        if job_prompt_id is not None:
            start_regenerating(db, record, job_prompt_id)
            landing = job_prompt_id
    return landing


def tend_the_trash(db, places: OutputPlaces, *, environ=os.environ) -> int:
    reclaimed = reclaim_orphans(db, Trash(places.trash))
    if reclaimed:
        logger.info("Trash: reclaimed %d unreachable batch folder(s)", reclaimed)
    settle_regenerations(db)
    return 0 if is_branch_session(environ) else empty_what_has_waited_a_day(db, places)


def reclaim_orphans(db, trash) -> int:
    """Clear the trash folders nothing can reach, and say how many went.

    It never takes anything the Trash is holding: every held record's batch folder
    is named as one to spare, so what is removed is only what no record points at
    — a rejected experiment's batch that fell off the undo stack, a batch from
    before the Trash existed, or a folder left by a crash between the move and the
    record.
    """
    return trash.purge_orphans([
        (record.get("batch") or {}).get("subdir") for record in db.list_trashed()
    ])
