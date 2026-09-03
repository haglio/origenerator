"""Every image and video this app knows about: one row per generation.

The largest of the six tables `Database` used to hold all of, and the one every
other part of the app eventually reads. A row carries the run that made it (the
workflow and its params, the prompts, the seed), what became of it (status,
output files, thumbnail, how long it took), and the marks the user and the two
export lanes leave on it.

The DDL and the column list are in :mod:`origenerator.db_schema`; evolver reads
seven of these columns read-only, so tests/test_db_schema.py holds them.
"""
from origenerator.db_connection import Store
from origenerator.db_schema import GENERATION_COLUMNS

#: The columns :meth:`GenerationStore.update_generation` writes: a job's
#: lifecycle, from queued to finished or failed. Everything else on the row is
#: either provenance -- the workflow, its params, the prompts, the seed, all
#: fixed when the job was submitted -- or a mark the user or an export lane
#: leaves, and each of those has its own named method below. So a key outside
#: this set is a caller reaching for the wrong method, which is worth saying.
LIFECYCLE_COLUMNS = frozenset({
    "status", "output_files", "original_files", "enhance_history",
    "thumbnail_path", "error_message", "completed_at", "duration_seconds",
    "progress_json",
})


class GenerationStore(Store):
    """The sixteen queries over the `generations` table."""

    def _set(self, prompt_id: str, column: str, value):
        """Write one column outside :data:`LIFECYCLE_COLUMNS`.

        *column* is interpolated into the statement, which is safe because every
        one is a literal written below and a real column of the table --
        tests/test_db_stores.py reads that off this file's syntax tree rather
        than leaving it to care.
        """
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {column} = ? WHERE prompt_id = ?",
                (value, prompt_id),
            )

    def _stamp(self, prompt_id: str, column: str):
        """Set one column to now. The three export marks, whose value is only
        ever tested for presence; the database's clock, so the stamp reads the
        same as every other one on the row."""
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {column} = datetime('now')"
                " WHERE prompt_id = ?",
                (prompt_id,),
            )

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
        """Move a job along: any of :data:`LIFECYCLE_COLUMNS`, in one statement.

        A column outside that set is refused by name rather than dropped -- the
        drop was silent, so a typo, or a caller reaching for a provenance field
        this does not write, was a no-op with nothing said. Callers build the
        field dict conditionally, so no fields at all is a normal outcome and
        stays a no-op.
        """
        refused = set(fields) - LIFECYCLE_COLUMNS
        if refused:
            raise ValueError(
                f"update_generation does not write {', '.join(sorted(refused))}; "
                f"it writes a job's lifecycle ({', '.join(sorted(LIFECYCLE_COLUMNS))}). "
                "Provenance and the user's own marks have their own methods.")
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [prompt_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {set_clause} WHERE prompt_id = ?",
                values,
            )

    def set_workflow_name(self, prompt_id: str, workflow_name: str):
        """Correct a row's workflow_name (e.g. backfilling 'unknown' imports).

        Its own method rather than a key of update_generation, which writes a
        job's lifecycle and not its provenance.
        """
        self._set(prompt_id, "workflow_name", workflow_name)

    def set_params_json(self, prompt_id: str, params_json: str):
        """Rewrite a row's params_json (e.g. backfilling model/LoRA onto imports).

        Its own method rather than a key of update_generation: the params are
        provenance, normally fixed at insert time.
        """
        self._set(prompt_id, "params_json", params_json)

    def set_recipe_source(self, prompt_id: str, *, category: str | None = None,
                          video_prompt_id: str | None = None):
        """Record where a combine launch got its recipe: the act picked in the
        dropdown, and the video whose settings the run re-uses.

        Written straight after the launch rather than at insert time, because the
        row goes in as the job is submitted and only the caller that built the
        combination knows either of these. Empty values are stored as NULL, so a
        dropped video (no act) and a curated act (no video) each record only the
        half they have. Two columns in one statement, so it keeps its own.
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

        Its own method rather than a key of update_generation, which covers a
        job's lifecycle rather than a user gesture like this.
        """
        self._set(prompt_id, "starred", 1 if starred else 0)

    def set_experiment_verdict(self, prompt_id: str, verdict: str | None):
        """Record the user's review of a background experiment: ``'up'`` (keep),
        ``'down'`` (reject), or ``None`` (back to unreviewed — an undone verdict).

        Its own method rather than a key of update_generation, which covers a
        job's lifecycle rather than a user gesture like this.
        """
        self._set(prompt_id, "experiment_verdict", verdict)

    def mark_evolver_exported(self, prompt_id: str):
        """Record that this generation's video was sent to Evolver's inbox.

        Stamps the current time so the gallery remembers the send across sessions
        (a plain marker — the value is only ever tested for presence).
        """
        self._stamp(prompt_id, "evolver_exported_at")

    def mark_genau_exported(self, prompt_id: str):
        """Record that this generation's clip was sent down the Genau lane.

        The twin of :meth:`mark_evolver_exported`, and equally a plain marker: the
        value is only ever tested for presence, so the button can show the send
        across sessions.
        """
        self._stamp(prompt_id, "genau_exported_at")

    def mark_genau_requested(self, prompt_id: str):
        """Record that a spoken "genau it" started this run.

        Stamped at launch, read at completion: it is what tells the finished clip
        to hand itself to the Genau lane without a second ask. Only ever tested
        for presence.
        """
        self._stamp(prompt_id, "genau_requested_at")

    def completed_generated(self) -> list[dict]:
        """Completed rows this install generated itself, oldest first.

        What a branch session's database is adopted from (see
        :mod:`origenerator.branch_session`). Only ``generated`` rows: a worktree
        database also holds thousands of seeded and imported rows describing the
        shared library, and "adopting" those would churn the live table with
        copies of records it already keeps. Oldest first, so adoption preserves
        the order they were made in.
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM generations WHERE status = 'completed'"
                " AND (source IS NULL OR source = 'generated') ORDER BY id")]

    def starred_prompt_ids(self) -> list[str]:
        """Every starred generation, by prompt id, in a stable order.

        The item half of what a branch session had bookmarked. Ordered by id
        rather than by row, because the list is recorded as a baseline and
        diffed against the next reading of it.
        """
        with self._connect() as conn:
            return [r["prompt_id"] for r in conn.execute(
                "SELECT prompt_id FROM generations WHERE starred = 1"
                " ORDER BY prompt_id")]

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
        cols = [c for c in GENERATION_COLUMNS if c in row]
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
