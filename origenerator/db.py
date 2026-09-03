import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from origenerator.db_salvage import salvage_if_malformed

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS generations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id       TEXT    NOT NULL UNIQUE,
    source          TEXT    NOT NULL DEFAULT 'generated',
    workflow_name   TEXT    NOT NULL,
    workflow_version TEXT   NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    positive_prompt TEXT,
    negative_prompt TEXT,
    seed            INTEGER,
    params_json     TEXT    NOT NULL,
    workflow_json   TEXT    NOT NULL,
    output_files    TEXT,
    -- Set when a standalone enhance was folded into this row: the output_files
    -- it had before (the pre-enhance file, still on disk and listed among the
    -- current output_files). Presence marks the row enhanced-in-place.
    original_files  TEXT,
    -- One entry per enhancement folded into this row, newest first: the file it
    -- produced and the settings that produced it. What lets the info pane list
    -- every level an image has received rather than just "enhanced".
    enhance_history TEXT,
    thumbnail_path  TEXT,
    error_message   TEXT,
    -- The user's per-item bookmark: a starred image or video, independent of the
    -- folder-level star in folder_meta.
    starred         INTEGER NOT NULL DEFAULT 0,
    -- Last live progress of a still-running job (a ProgressTracker snapshot), so a
    -- restart mid-generation can resume the bar at its last position instead of an
    -- indeterminate spin while ComfyUI's next per-step push is awaited.
    progress_json   TEXT,
    -- The user's review of a background experiment (source 'experiment'):
    -- 'up' admits it to the gallery, 'down' rejects it, NULL awaits review.
    experiment_verdict TEXT,
    duration_seconds REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    evolver_exported_at TEXT,
    -- The twin of evolver_exported_at for the Genau lane: a clip sent to be
    -- upscaled and delivered to Genau's folder. Separate because the two sends
    -- go to different source folders and mean different things, so a video can
    -- have had one, the other, or both.
    genau_exported_at TEXT,
    -- Set at launch on a run a spoken "genau it" started, so its completion hands
    -- the clip on without being asked again. On the row rather than in memory
    -- because a restart mid-generation is routine, and it is the only thing
    -- separating such a run from the identical loop workflow started by hand,
    -- which must stay put until Send-to-Genau is pressed.
    genau_requested_at TEXT,
    -- Where a combine launch got its recipe: the act picked in the Combine
    -- panel's dropdown, and the video whose settings the run re-uses. Either can
    -- stand alone — a dropped video names no act, and an act the overlay curates
    -- a recipe for is answered from no past video. Nothing else about the run
    -- records it: the params carry the recipe's values, never which video they
    -- came from or what the user called the act. Stamped at launch, because a
    -- queue row is read while the run is still pending.
    recipe_category TEXT,
    recipe_video_id TEXT,
    -- The image a standalone enhance run is *of*, by that image's prompt_id.
    -- The run's params name the file it reads, and a file name is not an
    -- identity: ComfyUI's counters are per prefix, a trashed file frees its
    -- number, and several rows have ended up naming one file. Stamped at
    -- launch, so every surface that shows the run on its image's tile, and the
    -- fold that lands its result there, agree on which image that is (see
    -- origenerator.gallery.enhance.enhance_target_id). NULL on a row from
    -- before this was recorded, which falls back to matching the file.
    enhance_of TEXT
);

CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS idx_generations_workflow ON generations(workflow_name);
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at DESC);

CREATE TABLE IF NOT EXISTS folder_meta (
    folder_key    TEXT PRIMARY KEY,
    custom_name   TEXT,
    starred       INTEGER NOT NULL DEFAULT 0,
    -- A bookmark's identity: the tree tier it sits at and a member generation, so
    -- its key can be recomputed under any future key formula (see reconcile).
    level         TEXT,
    ref_prompt_id TEXT
);

-- A folder the user composed by hand out of other folders (see
-- origenerator.gallery.custom). The name is the whole of it; what it holds lives
-- in custom_folder_members.
CREATE TABLE IF NOT EXISTS custom_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS custom_folder_members (
    folder_id     INTEGER NOT NULL REFERENCES custom_folders(id) ON DELETE CASCADE,
    -- The gathered folder, by tree key, plus the same identity a folder_meta
    -- bookmark carries so the reconcile can re-point it when a key formula moves.
    folder_key    TEXT    NOT NULL,
    level         TEXT,
    ref_prompt_id TEXT,
    -- Membership order, so a custom folder lists what it holds the way it was built.
    position      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (folder_id, folder_key)
);

-- A request and the generation it queued: the item it was made about, what was
-- heard, and the prompt pair before the edit (the pair after it is the queued
-- generation's own params). What the Requests shelf lists, and the only record
-- of why that generation differs from the one it came from. Kept even when its
-- generation goes: a delete here is undoable, and a restored item should come
-- back with the request that made it, so the shelf skips a record it can't
-- resolve rather than the record being dropped.
--
-- Spoken ("Request … over") or typed: a folder rewrite asks the same thing of
-- every picture in a folder at once and records one of these per picture, which
-- is what links each result to the one it was rewritten from. Such a record has
-- nothing heard and no single term — it says what it wanted by rewriting the
-- prompt, which the old/new pair holds — so `heard` is empty there and
-- `term`/`polarity`/`action` are unset.
CREATE TABLE IF NOT EXISTS requests (
    prompt_id        TEXT PRIMARY KEY,
    source_prompt_id TEXT NOT NULL,
    heard            TEXT NOT NULL,
    term             TEXT,
    polarity         TEXT,
    action           TEXT,
    old_positive     TEXT,
    old_negative     TEXT,
    new_positive     TEXT,
    new_negative     TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A deleted generation the recovery bin is still holding: the whole row the
-- delete dropped, and where in the trash its files went, so the Trash shelf can
-- list it, put both back, or end it for good (see origenerator.recovery). The
-- record goes away when the item is restored, purged, or ages out of the
-- retention window; the generations row itself is gone the moment it is deleted,
-- which is why the row travels here rather than staying behind a flag.
-- What a branch session had bookmarked when the live app last adopted from it:
-- the items that worktree's database starred, and its folder bookmarks. Only
-- what has *changed* there since is applied at the next launch, so a star the
-- user has removed here is not reinstated on every launch by a worktree copy
-- that still carries it, and an unstar made in a preview crosses exactly once
-- (see origenerator.branch_session.adopt_branch_curation). Keyed by worktree
-- directory name; a row outlives its worktree harmlessly.
CREATE TABLE IF NOT EXISTS branch_curation (
    branch     TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    adopted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deletions (
    prompt_id  TEXT PRIMARY KEY,
    row_json   TEXT NOT NULL,
    batch_json TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Every column of the generations table, in declaration order. Used to restore a
# previously-captured row verbatim (see ``restore_generation``).
_GENERATION_COLUMNS = (
    "id", "prompt_id", "source", "workflow_name", "workflow_version", "status",
    "positive_prompt", "negative_prompt", "seed", "params_json", "workflow_json",
    "output_files", "original_files", "enhance_history", "thumbnail_path",
    "error_message", "starred", "progress_json", "experiment_verdict",
    "duration_seconds", "created_at", "completed_at", "evolver_exported_at",
    "genau_exported_at", "genau_requested_at", "recipe_category", "recipe_video_id",
    "enhance_of",
)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salvage_if_malformed(self.path, _SCHEMA)
        self._init_schema()

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn):
        """Bring an older database up to the current schema.

        ``CREATE TABLE IF NOT EXISTS`` leaves a pre-existing table untouched, so
        columns added after a user's table was first created must be patched in
        here. Each step is guarded to stay idempotent.
        """
        existing = {row[1] for row in conn.execute("PRAGMA table_info(generations)")}
        if "duration_seconds" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN duration_seconds REAL")
        if "evolver_exported_at" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN evolver_exported_at TEXT")
        if "genau_exported_at" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN genau_exported_at TEXT")
        if "genau_requested_at" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN genau_requested_at TEXT")
        if "progress_json" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN progress_json TEXT")
        if "starred" not in existing:
            conn.execute(
                "ALTER TABLE generations ADD COLUMN starred INTEGER NOT NULL DEFAULT 0"
            )
        if "experiment_verdict" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN experiment_verdict TEXT")
        if "original_files" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN original_files TEXT")
        if "enhance_history" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN enhance_history TEXT")
        if "recipe_category" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN recipe_category TEXT")
        if "recipe_video_id" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN recipe_video_id TEXT")
        if "enhance_of" not in existing:
            conn.execute("ALTER TABLE generations ADD COLUMN enhance_of TEXT")
        folder_cols = {row[1] for row in conn.execute("PRAGMA table_info(folder_meta)")}
        if "level" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN level TEXT")
        if "ref_prompt_id" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN ref_prompt_id TEXT")

    @contextmanager
    def _connect(self):
        """A connection that commits on the way out, and always closes.

        Closing is what the plain ``with sqlite3.connect(...)`` this replaced
        never did -- that one commits and then leaves the connection to the
        garbage collector, which on Windows keeps the file open long enough for
        the next rename or replace of it to be refused (see
        :mod:`origenerator.db_salvage`).
        """
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def insert_generation(
        self,
        *,
        prompt_id: str,
        workflow_name: str,
        workflow_version: str,
        positive_prompt: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        params_json: str,
        workflow_json: str,
        source: str = "generated",
    ):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO generations
                   (prompt_id, source, workflow_name, workflow_version,
                    positive_prompt, negative_prompt, seed,
                    params_json, workflow_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prompt_id, source, workflow_name, workflow_version,
                 positive_prompt, negative_prompt, seed,
                 params_json, workflow_json),
            )

    def update_generation(self, prompt_id: str, **fields):
        allowed = {
            "status", "output_files", "original_files", "enhance_history",
            "thumbnail_path", "error_message", "completed_at", "duration_seconds",
            "progress_json",
        }
        to_set = {k: v for k, v in fields.items() if k in allowed}
        if not to_set:
            return
        set_clause = ", ".join(f"{k} = ?" for k in to_set)
        values = list(to_set.values()) + [prompt_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {set_clause} WHERE prompt_id = ?",
                values,
            )

    def set_workflow_name(self, prompt_id: str, workflow_name: str):
        """Correct a row's workflow_name (e.g. backfilling 'unknown' imports).

        Deliberately separate from update_generation, whose allowlist excludes
        provenance fields like workflow_name.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET workflow_name = ? WHERE prompt_id = ?",
                (workflow_name, prompt_id),
            )

    def set_params_json(self, prompt_id: str, params_json: str):
        """Rewrite a row's params_json (e.g. backfilling model/LoRA onto imports).

        Deliberately separate from update_generation, whose allowlist excludes
        params_json since it is normally fixed at insert time.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET params_json = ? WHERE prompt_id = ?",
                (params_json, prompt_id),
            )

    def set_recipe_source(self, prompt_id: str, *, category: str | None = None,
                          video_prompt_id: str | None = None):
        """Record where a combine launch got its recipe: the act picked in the
        dropdown, and the video whose settings the run re-uses.

        Written straight after the launch rather than at insert time, because the
        row goes in as the job is submitted and only the caller that built the
        combination knows either of these. Empty values are stored as NULL, so a
        dropped video (no act) and a curated act (no video) each record only the
        half they have. Separate from ``update_generation``, whose allowlist
        excludes provenance fields.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET recipe_category = ?, recipe_video_id = ? "
                "WHERE prompt_id = ?",
                (category or None, video_prompt_id or None, prompt_id),
            )

    def set_enhance_target(self, prompt_id: str, source_prompt_id: str | None):
        """Record which image the standalone enhance ``prompt_id`` is of.

        Written straight after the launch, like :meth:`set_recipe_source`: the
        row goes in as the job is submitted, and only the caller that chose the
        image knows which row it was. The run's params name a *file*, and a
        file name can belong to more than one row; this is the one thing on the
        run that names the row. Separate from ``update_generation``, whose
        allowlist excludes provenance fields.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET enhance_of = ? WHERE prompt_id = ?",
                (source_prompt_id or None, prompt_id),
            )

    def set_generation_starred(self, prompt_id: str, starred: bool):
        """Star (or unstar) one generation — the user's per-item bookmark.

        Deliberately separate from update_generation, whose allowlist covers a
        job's lifecycle fields rather than a user gesture like this.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET starred = ? WHERE prompt_id = ?",
                (1 if starred else 0, prompt_id),
            )

    def set_experiment_verdict(self, prompt_id: str, verdict: str | None):
        """Record the user's review of a background experiment: ``'up'`` (keep),
        ``'down'`` (reject), or ``None`` (back to unreviewed — an undone verdict).

        Deliberately separate from update_generation, whose allowlist covers a
        job's lifecycle fields rather than a user gesture like this.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET experiment_verdict = ? WHERE prompt_id = ?",
                (verdict, prompt_id),
            )

    def mark_evolver_exported(self, prompt_id: str):
        """Record that this generation's video was sent to Evolver's inbox.

        Stamps the current time so the gallery remembers the send across sessions
        (a plain marker — the value is only ever tested for presence).
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET evolver_exported_at = datetime('now')"
                " WHERE prompt_id = ?",
                (prompt_id,),
            )

    def mark_genau_exported(self, prompt_id: str):
        """Record that this generation's clip was sent down the Genau lane.

        The twin of :meth:`mark_evolver_exported`, and equally a plain marker: the
        value is only ever tested for presence, so the button can show the send
        across sessions.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET genau_exported_at = datetime('now')"
                " WHERE prompt_id = ?",
                (prompt_id,),
            )

    def mark_genau_requested(self, prompt_id: str):
        """Record that a spoken "genau it" started this run.

        Stamped at launch, read at completion: it is what tells the finished clip
        to hand itself to the Genau lane without a second ask. Only ever tested
        for presence.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET genau_requested_at = datetime('now')"
                " WHERE prompt_id = ?",
                (prompt_id,),
            )

    def recent_durations(self, workflow_name: str, limit: int = 10) -> list[float]:
        """Most-recent measured generation times for a workflow, newest first.

        Only completed rows with a recorded ``duration_seconds`` count, so the
        result feeds duration estimates directly.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT duration_seconds FROM generations
                   WHERE workflow_name = ?
                     AND status = 'completed'
                     AND duration_seconds IS NOT NULL
                   ORDER BY id DESC
                   LIMIT ?""",
                (workflow_name, limit),
            ).fetchall()
            return [r[0] for r in rows]

    def completed_without_duration(self) -> list[dict]:
        """Completed rows that have a finish time but no recorded duration.

        These are the candidates for log-based backfill: their ``completed_at``
        (the output file's mtime) is what a log line gets matched against.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM generations
                   WHERE status = 'completed'
                     AND duration_seconds IS NULL
                     AND completed_at IS NOT NULL
                   ORDER BY id"""
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_generation(self, prompt_id: str):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM generations WHERE prompt_id = ?", (prompt_id,)
            )

    def restore_generation(self, row: dict):
        """Re-insert a row captured by ``get_generation``, exactly as it was.

        Unlike ``insert_generation``, this writes every column present in
        ``row`` — including the original ``id`` and ``created_at`` — so an undone
        deletion reappears in its former gallery position rather than on top.
        """
        cols = [c for c in _GENERATION_COLUMNS if c in row]
        placeholders = ", ".join("?" for _ in cols)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO generations ({', '.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )

    def get_generation(self, prompt_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM generations WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_generations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM generations ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- the recovery bin (deletions held until restored, purged, or expired) --

    def record_deletion(self, prompt_id: str, row: dict, batch: dict):
        """Hold a just-deleted ``row`` and its trash ``batch`` for recovery.

        Replaces any earlier record for the same generation, so an item deleted,
        restored, and deleted again is held from the *latest* delete rather than
        expiring on the first one's clock.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO deletions (prompt_id, row_json, batch_json)"
                " VALUES (?, ?, ?)",
                (prompt_id, json.dumps(row, default=str), json.dumps(batch)),
            )

    def list_deletions(self) -> list[dict]:
        """Every held deletion, newest first — what the Trash shelf lists.

        The stamp only has second resolution, so a batch deleted together ties;
        the rowid breaks it, and an ``INSERT OR REPLACE`` takes a fresh one, so
        the order stays the order things were deleted in.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompt_id, row_json, batch_json, deleted_at FROM deletions"
                " ORDER BY deleted_at DESC, rowid DESC"
            ).fetchall()
            return [_deletion(r) for r in rows]

    def get_deletion(self, prompt_id: str) -> dict | None:
        with self._connect() as conn:
            record = conn.execute(
                "SELECT prompt_id, row_json, batch_json, deleted_at FROM deletions"
                " WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()
            return _deletion(record) if record else None

    def forget_deletion(self, prompt_id: str):
        """Drop a held deletion — the item was restored, purged, or expired."""
        with self._connect() as conn:
            conn.execute("DELETE FROM deletions WHERE prompt_id = ?", (prompt_id,))

    # --- spoken requests (what the Requests shelf lists) --------------------

    def record_request(self, *, prompt_id: str, source_prompt_id: str, heard: str,
                       term: str | None = None, polarity: str | None = None,
                       action: str | None = None, old_positive: str = "",
                       old_negative: str = "", new_positive: str = "",
                       new_negative: str = ""):
        """Record that ``prompt_id`` was queued by a request about
        ``source_prompt_id`` — spoken, or typed as one picture of a folder-wide
        rewrite, which leaves ``heard`` empty. Replaces any earlier record for
        the same generation, which only a re-used prompt id could produce."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO requests
                       (prompt_id, source_prompt_id, heard, term, polarity, action,
                        old_positive, old_negative, new_positive, new_negative)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prompt_id, source_prompt_id, heard, term, polarity, action,
                 old_positive, old_negative, new_positive, new_negative),
            )

    def list_requests(self) -> list[dict]:
        """Every recorded request, newest first — the Requests shelf's listing.

        The stamp has second resolution, so requests made in one burst tie; the
        rowid breaks it, keeping them in the order they were spoken.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_request(self, prompt_id: str) -> dict | None:
        """The request that queued this generation, or ``None`` if none did."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE prompt_id = ?", (prompt_id,)
            ).fetchone()
            return dict(row) if row else None

    # --- folder metadata (custom names + stars for gallery folders) --------

    def folder_meta_map(self) -> dict[str, dict]:
        """Return ``{folder_key: {"custom_name": str|None, "starred": bool}}``."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, custom_name, starred FROM folder_meta"
            ).fetchall()
        return {
            r["folder_key"]: {
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
            }
            for r in rows
        }

    def rename_folder(self, folder_key: str, custom_name: str | None):
        """Set (or clear, when ``None``) a folder's custom display name."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, custom_name)
                   VALUES (?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET custom_name = excluded.custom_name""",
                (folder_key, custom_name),
            )

    def set_folder_starred(self, folder_key: str, starred: bool):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, starred)
                   VALUES (?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET starred = excluded.starred""",
                (folder_key, 1 if starred else 0),
            )

    def folder_meta_full(self) -> list[dict]:
        """Every folder_meta row with its bookmark identity, for the reconcile.

        Unlike :meth:`folder_meta_map` (which the view uses for labels/stars), this
        also carries ``level`` and ``ref_prompt_id`` so a stale key can be re-derived.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, custom_name, starred, level, ref_prompt_id "
                "FROM folder_meta"
            ).fetchall()
        return [
            {
                "folder_key": r["folder_key"],
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
                "level": r["level"],
                "ref_prompt_id": r["ref_prompt_id"],
            }
            for r in rows
        ]

    def upsert_folder_meta(self, folder_key: str, *, custom_name: str | None,
                           starred: bool, level: str | None, ref_prompt_id: str | None):
        """Write a folder_meta row in full — the reconcile's tool for re-pointing a
        bookmark onto a new key and for stamping identity onto a matched one."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta
                       (folder_key, custom_name, starred, level, ref_prompt_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(folder_key) DO UPDATE SET
                       custom_name = excluded.custom_name,
                       starred = excluded.starred,
                       level = excluded.level,
                       ref_prompt_id = excluded.ref_prompt_id""",
                (folder_key, custom_name, 1 if starred else 0, level, ref_prompt_id),
            )

    def delete_folder_meta(self, folder_key: str):
        """Drop a folder_meta row — used to clear a bookmark's old key after the
        reconcile has re-pointed it onto its current one."""
        with self._connect() as conn:
            conn.execute("DELETE FROM folder_meta WHERE folder_key = ?", (folder_key,))

    # --- branch-session curation (what each worktree had bookmarked) ---------

    def branch_curation_state(self, branch: str) -> dict | None:
        """What was last adopted from the worktree named *branch*.

        ``None`` when this worktree has never been read — which is precisely what
        tells adoption it has no baseline to diff against, and so may add
        bookmarks but not take any away (see
        :func:`~origenerator.branch_session.adopt_branch_curation`). A record
        written by a future version and unreadable here counts as never read, for
        the same reason: guessing is what a missing baseline forbids.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM branch_curation WHERE branch = ?",
                (branch,),
            ).fetchone()
        if row is None:
            return None
        try:
            state = json.loads(row["state_json"])
        except (TypeError, ValueError):
            return None
        return state if isinstance(state, dict) else None

    def set_branch_curation_state(self, branch: str, state: dict):
        """Remember a worktree's bookmarks as of now, so the next launch can tell
        what the branch changed from what it merely inherited."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO branch_curation (branch, state_json, adopted_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(branch) DO UPDATE SET
                       state_json = excluded.state_json,
                       adopted_at = excluded.adopted_at""",
                (branch, json.dumps(state)),
            )

    # --- custom folders: the groupings the user composes by hand -------------

    def create_custom_folder(self, name: str, folder_id: int | None = None) -> int:
        """Make an empty custom folder and return its id.

        ``folder_id`` re-creates one at the id it had, so an undone removal comes
        back under the very key the session was saved with (see
        :meth:`GalleryActions.delete_custom_folder`)."""
        with self._connect() as conn:
            if folder_id is None:
                cur = conn.execute("INSERT INTO custom_folders (name) VALUES (?)", (name,))
                return int(cur.lastrowid)
            conn.execute("INSERT INTO custom_folders (id, name) VALUES (?, ?)",
                         (folder_id, name))
            return int(folder_id)

    def rename_custom_folder(self, folder_id: int, name: str):
        with self._connect() as conn:
            conn.execute("UPDATE custom_folders SET name = ? WHERE id = ?",
                         (name, folder_id))

    def delete_custom_folder(self, folder_id: int):
        """Drop a custom folder and its membership. The gathered folders and their
        generations are untouched — a custom folder holds references, not items."""
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_folder_members WHERE folder_id = ?",
                         (folder_id,))
            conn.execute("DELETE FROM custom_folders WHERE id = ?", (folder_id,))

    def add_custom_folder_members(self, folder_id: int, members: list[tuple]):
        """Add ``(folder_key, level, ref_prompt_id)`` members to a custom folder,
        appended after whatever it already holds. A key already in the folder keeps
        its position and refreshes its identity, so re-dropping a folder is a no-op
        rather than a duplicate."""
        if not members:
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM custom_folder_members "
                "WHERE folder_id = ?", (folder_id,)
            ).fetchone()
            position = int(row[0]) + 1
            for folder_key, level, ref_prompt_id in members:
                conn.execute(
                    """INSERT INTO custom_folder_members
                           (folder_id, folder_key, level, ref_prompt_id, position)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(folder_id, folder_key) DO UPDATE SET
                           level = excluded.level,
                           ref_prompt_id = excluded.ref_prompt_id""",
                    (folder_id, folder_key, level, ref_prompt_id, position),
                )
                position += 1

    def remove_custom_folder_member(self, folder_id: int, folder_key: str):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM custom_folder_members WHERE folder_id = ? AND folder_key = ?",
                (folder_id, folder_key),
            )

    def list_custom_folders(self) -> list[dict]:
        """Every custom folder as ``{"id", "name", "members": [folder_key, ...]}``,
        oldest first, each member list in the order it was built up."""
        with self._connect() as conn:
            folders = [
                {"id": r["id"], "name": r["name"], "members": []}
                for r in conn.execute(
                    "SELECT id, name FROM custom_folders ORDER BY id"
                )
            ]
            by_id = {f["id"]: f for f in folders}
            for r in conn.execute(
                "SELECT folder_id, folder_key FROM custom_folder_members "
                "ORDER BY folder_id, position, rowid"
            ):
                folder = by_id.get(r["folder_id"])
                if folder is not None:
                    folder["members"].append(r["folder_key"])
            return folders

    def custom_folder_members_full(self) -> list[dict]:
        """Every membership row with its stored identity, for the reconcile."""
        with self._connect() as conn:
            return [
                {"folder_id": r["folder_id"], "folder_key": r["folder_key"],
                 "level": r["level"], "ref_prompt_id": r["ref_prompt_id"]}
                for r in conn.execute(
                    "SELECT folder_id, folder_key, level, ref_prompt_id "
                    "FROM custom_folder_members"
                )
            ]

    def repoint_custom_folder_member(self, folder_id: int, old_key: str, new_key: str,
                                     *, level: str | None, ref_prompt_id: str | None):
        """Move a membership onto ``new_key``, keeping its place in the folder.

        Used by the reconcile when a member's folder key drifts. If the folder
        already holds ``new_key`` the stale row is simply dropped — the grouping
        already contains that folder once, which is all it can mean.
        """
        with self._connect() as conn:
            held = conn.execute(
                "SELECT position FROM custom_folder_members "
                "WHERE folder_id = ? AND folder_key = ?", (folder_id, old_key)
            ).fetchone()
            position = int(held["position"]) if held is not None else 0
            conn.execute(
                "DELETE FROM custom_folder_members WHERE folder_id = ? AND folder_key = ?",
                (folder_id, old_key),
            )
            conn.execute(
                """INSERT INTO custom_folder_members
                       (folder_id, folder_key, level, ref_prompt_id, position)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(folder_id, folder_key) DO UPDATE SET
                       level = excluded.level,
                       ref_prompt_id = excluded.ref_prompt_id""",
                (folder_id, new_key, level, ref_prompt_id, position),
            )

    def stamp_custom_folder_member(self, folder_id: int, folder_key: str,
                                   *, level: str | None, ref_prompt_id: str | None):
        """Refresh a live membership's stored identity, so a future key formula
        change can re-derive it from a member generation."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE custom_folder_members SET level = ?, ref_prompt_id = ? "
                "WHERE folder_id = ? AND folder_key = ?",
                (level, ref_prompt_id, folder_id, folder_key),
            )


def _deletion(record) -> dict:
    """One ``deletions`` row with its JSON columns parsed back into data."""
    return {
        "prompt_id": record["prompt_id"],
        "row": json.loads(record["row_json"]),
        "batch": json.loads(record["batch_json"]),
        "deleted_at": record["deleted_at"],
    }
