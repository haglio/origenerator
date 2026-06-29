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
    duration_seconds REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS idx_generations_workflow ON generations(workflow_name);
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at DESC);
"""


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
            "error_message", "completed_at", "duration_seconds",
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
