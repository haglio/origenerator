import sqlite3
from pathlib import Path

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
    ref_prompt_id TEXT
);
"""

# Every column of the generations table, in declaration order. Used to restore a
# previously-captured row verbatim (see ``restore_generation``).
_GENERATION_COLUMNS = (
    "id", "prompt_id", "source", "workflow_name", "workflow_version", "status",
    "positive_prompt", "negative_prompt", "seed", "params_json", "workflow_json",
    "output_files", "thumbnail_path", "error_message", "starred", "progress_json",
    "experiment_verdict", "duration_seconds", "created_at", "completed_at",
    "evolver_exported_at",
)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with sqlite3.connect(self.path) as conn:
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
        folder_cols = {row[1] for row in conn.execute("PRAGMA table_info(folder_meta)")}
        if "level" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN level TEXT")
        if "ref_prompt_id" not in folder_cols:
            conn.execute("ALTER TABLE folder_meta ADD COLUMN ref_prompt_id TEXT")

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

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
            "status", "output_files", "thumbnail_path",
            "error_message", "completed_at", "duration_seconds", "progress_json",
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
