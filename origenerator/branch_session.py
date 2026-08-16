"""Run a session out of a branch worktree, skipping what only the live app does.

``launch_preview_branch.vbs`` in a worktree runs that branch's code as its own
instance with its own ``state/`` — but a fresh state dir made every launch
re-scan ComfyUI's whole output history ("Scanning for new images…" for minutes,
looking crashed) to rebuild a database the primary checkout already has. The
same problem fun_time's branch sessions solved, and the same answer: the
library-derived state is *seeded* from the live install rather than rebuilt,
and the maintenance passes that keep it healthy — the import scan, the
backfills, the reconciles, the recovery-bin sweep — are the live app's job
alone, so a branch session skips them (``origenerator.app.main`` gates on
:func:`is_branch_session`).

The same line divides what a preview may do to the *shared ComfyUI*: it
generates on demand like any session, but it never schedules background
experiments for the coming absence (``GalleryView.queue_experiments_for_absence``
gates on the flag too). Those outlive the preview in a queue only the app that
queued them can cancel, so they run on against a live app that can't see them.

``ORIGENERATOR_BRANCH_SESSION=1`` in the environment is what marks one; the
preview launcher sets it, and the primary's launcher never does.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

ENV_FLAG = "ORIGENERATOR_BRANCH_SESSION"


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"


def session_trash(root: Path):
    """The trash this session may put files in: the real one, or nothing.

    A branch session deletes no files at all. Every file it can see is the live
    install's — its database is a copy, so its rows point at the live library,
    and what it generates itself the live app adopts at its next launch (see
    :func:`adopt_branch_rows`). So a delete in a preview drops the row from its
    own throwaway database and leaves the file alone; the live app's rows keep
    pointing at something real.

    What that used to cost: a delete in a preview moved the shared ComfyUI
    output file — and the live install's thumbnail, which the row names by
    absolute path — into the worktree's trash, while the live app's own row
    survived. That row then had nothing to show, and an experiment's stayed on
    the review shelf as a dead tile the user could only remove again.

    Its ``purge_orphans`` does nothing for the same reason, which also spares
    the trash previews filled before they stopped taking files: those batches
    hold the only copies left of what they took. Taking no files is also what
    keeps a preview's own deletes recoverable *within* the preview while the
    live install's held deletes stay out of reach — see
    ``GalleryView._bin_records``.
    """
    from origenerator.trash import NoTrash, Trash
    return NoTrash() if is_branch_session() else Trash(root)


def adopt_branch_rows(db, worktrees_root: Path, output_dir: Path,
                      thumb_dir: Path) -> int:
    """Adopt generations made in branch sessions into the live database.

    A branch session generates into the shared ComfyUI output like any session,
    but records the rows only in its own worktree database — so its results
    used to reach the live app only through the import scan, which reconstructs
    rows from the files and stamps them ``imported``: the exact params replaced
    by what the embedded graph gives up, and the results left off the Recents
    shelf (app-made results only). Adopting the branch's own rows keeps them
    what they are: generated here, by the user.

    Runs at live-app launch, before the import scan, so the scan finds the
    files already recorded. A file the scan already imported in an earlier
    launch is upgraded — the reconstructed row makes way for the original.
    Thumbnails are regenerated into the live state (the worktree's are on
    borrowed time), and the worktree databases are only ever read: a branch is
    unfinished code, and this is the one-way door back out of it.
    """
    from origenerator.media import media_type_from_filename
    from origenerator.thumbnail import generate_thumbnail

    worktrees_root = Path(worktrees_root)
    if not worktrees_root.is_dir():
        return 0
    primary_by_file = _rows_by_rel_path(db.list_generations())
    adopted = 0
    for branch_db in sorted(worktrees_root.glob("*/state/origenerator.db")):
        for row in _completed_rows(branch_db):
            if db.get_generation(row["prompt_id"]) is not None:
                continue  # already adopted (or a row the branch merely seeded)
            rel_paths = _rel_paths(row)
            claimed = [primary_by_file[p] for p in rel_paths if p in primary_by_file]
            if any((r.get("source") or "generated") != "imported" for r in claimed):
                continue  # the live app has its own first-class record
            first = rel_paths[0] if rel_paths else None
            if first is None or not (output_dir / first).exists():
                continue  # nothing on disk to adopt
            for reconstruction in claimed:
                db.delete_generation(reconstruction["prompt_id"])
            row.pop("id", None)  # the live table assigns its own
            row["thumbnail_path"] = None
            try:
                media = media_type_from_filename(first) or "image"
                row["thumbnail_path"] = str(generate_thumbnail(
                    output_dir / first, media, thumb_dir, name=row["prompt_id"]))
            except Exception:
                pass  # a tile can live without its thumbnail; the row cannot wait
            db.restore_generation(row)
            for path in rel_paths:
                primary_by_file[path] = row
            adopted += 1
    return adopted


def _completed_rows(branch_db: Path) -> list[dict]:
    """Every completed generation the branch session itself made, oldest first
    (so adoption preserves the order they were made in). Only ``generated``
    rows: a worktree database also holds thousands of seeded and imported rows
    describing the shared library, and "adopting" those would churn the live
    table with copies of records it already keeps. Unreadable databases —
    mid-write, corrupt, half-deleted worktrees — yield nothing rather than
    failing the launch."""
    try:
        source_uri = f"file:{Path(branch_db).as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM generations WHERE status = 'completed'"
                " AND (source IS NULL OR source = 'generated') ORDER BY id")]
    except sqlite3.Error:
        return []


def _rel_paths(row: dict) -> list[str]:
    """A row's output files as the output-dir-relative paths the import scan
    keys by, bad JSON tolerated as none."""
    try:
        files = json.loads(row.get("output_files") or "[]")
    except (TypeError, ValueError):
        return []
    paths = []
    for entry in files if isinstance(files, list) else []:
        name = entry.get("filename")
        if name:
            sub = entry.get("subfolder") or ""
            paths.append(f"{sub}/{name}" if sub else name)
    return paths


def _rows_by_rel_path(rows: list[dict]) -> dict:
    by_path = {}
    for row in rows:
        for path in _rel_paths(row):
            by_path.setdefault(path, row)
    return by_path


def seed_branch_db(primary_db: Path, branch_db: Path) -> bool:
    """Start the branch's database from the primary's, once; return whether it did.

    Copied with sqlite's online backup — the live app may be mid-write, and a
    plain file copy of a hot database can capture a torn page — and never
    written back: a branch is unfinished code, and the live session's library
    is not its to corrupt. Only when the branch has no database of its own yet;
    after that, its state is its own work. A branch that IS the primary (the
    flag set there by mistake) falls out naturally: its database either already
    exists or is the missing source.
    """
    primary_db, branch_db = Path(primary_db), Path(branch_db)
    if branch_db.exists() or not primary_db.exists():
        return False
    branch_db.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{primary_db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source, \
            closing(sqlite3.connect(branch_db)) as destination:
        source.backup(destination)
    return True
