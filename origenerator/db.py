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
    evolver_exported_at TEXT
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
    ref_prompt_id TEXT,
    -- This folder's enhancement settings, as the Enhance subpanel left them:
    -- ``{"auto": bool, "params": {...}}``. What Enhance All, a single enhance,
    -- and the auto-enhance of newly generated members all run with.
    enhance_json  TEXT
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
"""

# Every column of the generations table, in declaration order. Used to restore a
# previously-captured row verbatim (see ``restore_generation``).
_GENERATION_COLUMNS = (
    "id", "prompt_id", "source", "workflow_name", "workflow_version", "status",
    "positive_prompt", "negative_prompt", "seed", "params_json", "workflow_json",
    "output_files", "original_files", "enhance_history", "thumbnail_path",
    "error_message", "starred", "progress_json", "experiment_verdict",
    "duration_seconds", "created_at", "completed_at", "evolver_exported_at",
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
        folder_cols = {row[1] for row in conn.execute("PRAGMA table_info(folder_meta)")}
        if "level" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN level TEXT")
        if "ref_prompt_id" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN ref_prompt_id TEXT")
        if "enhance_json" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN enhance_json TEXT")

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

    def folder_enhance_map(self) -> dict[str, str]:
        """``{folder_key: enhance_json}`` for every folder that has settings.

        Read whole rather than per folder because the gallery consults it on each
        rebuild — once per open folder, and once per row an auto-enhance might
        claim — and the table is small.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, enhance_json FROM folder_meta"
                " WHERE enhance_json IS NOT NULL"
            ).fetchall()
        return {r["folder_key"]: r["enhance_json"] for r in rows}

    def set_folder_enhance(self, folder_key: str, enhance_json: str | None):
        """Store (or clear, when ``None``) a folder's enhancement settings.

        Deliberately its own column and its own writer: :meth:`upsert_folder_meta`
        names only the bookmark columns, so the reconcile re-stamping a folder's
        identity leaves these settings untouched.
        """
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, enhance_json)
                   VALUES (?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET enhance_json = excluded.enhance_json""",
                (folder_key, enhance_json),
            )

    def folder_meta_full(self) -> list[dict]:
        """Every folder_meta row with its bookmark identity, for the reconcile.

        Unlike :meth:`folder_meta_map` (which the view uses for labels/stars), this
        also carries ``level``, ``ref_prompt_id`` and the folder's enhancement
        settings, so a stale key can be re-derived and everything hanging off it
        moved across.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, custom_name, starred, level, ref_prompt_id, "
                "enhance_json FROM folder_meta"
            ).fetchall()
        return [
            {
                "folder_key": r["folder_key"],
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
                "level": r["level"],
                "ref_prompt_id": r["ref_prompt_id"],
                "enhance_json": r["enhance_json"],
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
