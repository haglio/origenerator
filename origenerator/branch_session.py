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
    primary_rows = db.list_generations()
    primary_by_file = _rows_by_rel_path(primary_rows)
    # Nearly every row a worktree database holds is one of *these* -- it was
    # seeded from this database, so its whole library came across. Recognizing
    # them here, against rows already in hand, is what keeps the pass flat:
    # asking the database about each one instead cost a query per seeded row per
    # worktree, and with a worktree open per branch in flight that was ten
    # thousand round trips and twelve seconds of every launch, growing with both
    # the library and the number of branches.
    known = {row["prompt_id"] for row in primary_rows}
    adopted = 0
    for branch_db in sorted(worktrees_root.glob("*/state/origenerator.db")):
        requests = _request_records(branch_db)
        for row in _completed_rows(branch_db):
            if row["prompt_id"] in known:
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
            # A generation asked for out loud comes over with the request that
            # asked for it, or it would land in the live gallery as an ordinary
            # re-roll — the one thing it isn't.
            record = requests.get(row["prompt_id"])
            if record is not None:
                db.record_request(**record)
            for path in rel_paths:
                primary_by_file[path] = row
            known.add(row["prompt_id"])  # two worktrees can carry the same row
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


def _request_records(branch_db: Path) -> dict:
    """The spoken requests a branch session recorded, by the generation each
    queued — so an adopted row keeps its place on the Requests shelf.

    ``created_at`` is dropped: the live record is written now, and a stamp from
    a database that was never the live one is not a time this app can vouch for.
    A branch database predating the table (or unreadable) yields nothing rather
    than failing the launch, exactly as :func:`_completed_rows` does.
    """
    try:
        source_uri = f"file:{Path(branch_db).as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("SELECT * FROM requests")]
    except sqlite3.Error:
        return {}
    for row in rows:
        row.pop("created_at", None)
    return {row["prompt_id"]: row for row in rows}


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


def adopt_branch_curation(db, worktrees_root: Path) -> int:
    """Bring the stars and folder bookmarks a branch session made home too.

    :func:`adopt_branch_rows` carries a star only on a generation the branch made
    itself, because there the star is one column of the row being adopted. Every
    other star had nowhere to go: a preview's database is a *copy* of this one,
    so starring a library item there writes a row this app already has -- exactly
    the rows adoption skips -- and folder bookmarks were never read at all. Both
    were simply lost when the worktree went.

    What makes this safe to run at every launch is remembering what each worktree
    looked like the last time it was read (``branch_curation``). Only what
    *changed* there since is applied, so a star the user has since removed here
    is not reinstated on every launch by a worktree copy that still carries it,
    and an unstar made in a preview crosses over exactly once. A worktree seen
    for the first time has no such baseline -- its database may have been seeded
    from a much older state of this one, and a zero in it is as likely to be that
    age as the user's intent -- so that first pass adds but never takes away, and
    records the baseline the passes after it diff against.

    Returns how many bookmarks were applied. Runs after the rows are adopted, so
    a star on a generation the branch itself made finds its row already here, and
    before the folder reconcile, which heals any key the branch derived under a
    formula this code has since moved on from.
    """
    worktrees_root = Path(worktrees_root)
    if not worktrees_root.is_dir():
        return 0
    rows = db.list_generations()
    known = {row["prompt_id"] for row in rows}
    starred = {row["prompt_id"] for row in rows if row.get("starred")}
    folders = {row["folder_key"]: row for row in db.folder_meta_full()}
    applied = 0
    for branch_db in sorted(worktrees_root.glob("*/state/origenerator.db")):
        branch = Path(branch_db).parts[-3]
        state = _curation_state(branch_db)
        if state is None:
            continue  # mid-write, half-deleted, or older than the columns read here
        prior = db.branch_curation_state(branch)
        for prompt_id, star in _star_changes(state, prior):
            if prompt_id not in known:
                continue  # nothing here to bookmark (the file never came over)
            if (prompt_id in starred) == star:
                continue  # already the way the branch left it
            db.set_generation_starred(prompt_id, star)
            if star:
                starred.add(prompt_id)
            else:
                starred.discard(prompt_id)
            applied += 1
        for folder_key, meta in _folder_changes(state, prior):
            live = folders.get(folder_key)
            if meta is None:
                if live is None:
                    continue
                db.delete_folder_meta(folder_key)
                del folders[folder_key]
                applied += 1
                continue
            merged = _merged_folder_meta(live, meta, additive=prior is None)
            if merged is None:
                continue
            db.upsert_folder_meta(
                folder_key, custom_name=merged["custom_name"],
                starred=merged["starred"], level=merged["level"],
                ref_prompt_id=merged["ref_prompt_id"])
            folders[folder_key] = dict(merged, folder_key=folder_key)
            applied += 1
        db.set_branch_curation_state(branch, state)
    return applied


def _curation_state(branch_db: Path) -> dict | None:
    """A worktree database's bookmarks, in the shape ``branch_curation`` stores:
    the prompt ids it stars, and its folder_meta rows by key.

    ``None`` when the database cannot be read this way -- a worktree mid-write, a
    half-deleted one, or one seeded before these columns existed. Skipping it
    beats adopting from a partial reading and then recording that reading as the
    baseline, which would make the branch's untouched bookmarks look like
    deletions on the very next launch.
    """
    try:
        source_uri = f"file:{Path(branch_db).as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            stars = [r["prompt_id"] for r in conn.execute(
                "SELECT prompt_id FROM generations WHERE starred = 1"
                " ORDER BY prompt_id")]
            folders = {r["folder_key"]: {
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
                "level": r["level"],
                "ref_prompt_id": r["ref_prompt_id"],
            } for r in conn.execute(
                "SELECT folder_key, custom_name, starred, level, ref_prompt_id"
                " FROM folder_meta")}
    except sqlite3.Error:
        return None
    return {"stars": stars, "folders": folders}


def _star_changes(state: dict, prior: dict | None) -> list[tuple[str, bool]]:
    """Which item stars the branch itself changed, as ``(prompt_id, starred)``.

    Against a prior reading that is the symmetric difference -- what it starred
    and what it unstarred. With no prior reading there is no telling a star the
    branch added from one this app has since dropped, so only its stars are
    offered, never its unstars.
    """
    now = set(state.get("stars") or ())
    if prior is None:
        return [(prompt_id, True) for prompt_id in sorted(now)]
    was = set(prior.get("stars") or ())
    return ([(prompt_id, True) for prompt_id in sorted(now - was)]
            + [(prompt_id, False) for prompt_id in sorted(was - now)])


def _folder_changes(state: dict, prior: dict | None) -> list[tuple[str, dict | None]]:
    """Which folder bookmarks the branch itself changed, as ``(key, meta)`` --
    ``meta`` ``None`` for one it dropped.

    Same asymmetry as :func:`_star_changes`: with no prior reading only what the
    branch *holds* is offered, since a bookmark missing from a copy is
    indistinguishable from one this app never had.
    """
    now = state.get("folders") or {}
    if prior is None:
        return sorted(now.items())
    was = prior.get("folders") or {}
    changed = [(key, meta) for key, meta in sorted(now.items()) if was.get(key) != meta]
    return changed + [(key, None) for key in sorted(was) if key not in now]


def _merged_folder_meta(live: dict | None, branch: dict, *,
                        additive: bool) -> dict | None:
    """The folder_meta values to write for a bookmark the branch changed, or
    ``None`` when there is nothing to write.

    A diffed pass takes the branch's row whole: it is what the user left there.
    A first, baseline-less pass may only add -- it lights a star this app lacks
    and fills in a name it has none for, and leaves the rest alone.
    """
    base = {"custom_name": None, "starred": False, "level": None,
            "ref_prompt_id": None}
    if live is not None:
        base = {key: live.get(key) for key in base}
    if not additive:
        merged = {key: branch.get(key) for key in base}
        return merged if merged != base else None
    merged = dict(base)
    if branch.get("starred"):
        merged["starred"] = True
    if branch.get("custom_name") and not merged["custom_name"]:
        merged["custom_name"] = branch["custom_name"]
    if merged == base:
        return None
    # Carry the branch's bookmark identity onto a key this app had nothing for,
    # so the reconcile can re-point it when the key formula next moves.
    merged["level"] = merged["level"] or branch.get("level")
    merged["ref_prompt_id"] = merged["ref_prompt_id"] or branch.get("ref_prompt_id")
    return merged


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
