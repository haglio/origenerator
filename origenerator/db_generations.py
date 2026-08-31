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


class GenerationStore(Store):
    """The sixteen queries over the `generations` table."""

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
