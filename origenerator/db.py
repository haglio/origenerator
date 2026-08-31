import json
from pathlib import Path

from origenerator.db_connection import SqliteFile
from origenerator.db_custom_folders import CustomFolderStore
from origenerator.db_deletions import DeletionStore
from origenerator.db_folder_meta import FolderMetaStore
from origenerator.db_salvage import salvage_if_malformed
from origenerator.db_schema import GENERATION_COLUMNS, SCHEMA, create


class Database:
    """Every table of the app's one database, under one object.

    The schema lives in :mod:`origenerator.db_schema` and the connection policy
    in :mod:`origenerator.db_connection`; what is left here is the queries, and
    they are on their way out to one module per table.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salvage_if_malformed(self.path, SCHEMA)
        file = SqliteFile(self.path)
        self._connect = file.connect
        with self._connect() as conn:
            create(conn)
        # One store per table. Hand a unit the store it needs rather than the
        # whole database: recovery and gallery_actions want `deletions`,
        # reconcile wants `folder_meta` and `custom_folders`, and neither has
        # any business with the rest.
        self.deletions = DeletionStore(file)
        self.folder_meta = FolderMetaStore(file)
        self.custom_folders = CustomFolderStore(file)

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

    # --- the recovery bin (see origenerator.db_deletions) --------------------

    def record_deletion(self, prompt_id: str, row: dict, batch: dict):
        return self.deletions.record_deletion(prompt_id, row, batch)

    def list_deletions(self) -> list[dict]:
        return self.deletions.list_deletions()

    def get_deletion(self, prompt_id: str) -> dict | None:
        return self.deletions.get_deletion(prompt_id)

    def forget_deletion(self, prompt_id: str):
        return self.deletions.forget_deletion(prompt_id)

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

    # --- folder metadata (see origenerator.db_folder_meta) ------------------

    def folder_meta_map(self) -> dict[str, dict]:
        return self.folder_meta.folder_meta_map()

    def rename_folder(self, folder_key: str, custom_name: str | None):
        return self.folder_meta.rename_folder(folder_key, custom_name)

    def set_folder_starred(self, folder_key: str, starred: bool):
        return self.folder_meta.set_folder_starred(folder_key, starred)

    def folder_meta_full(self) -> list[dict]:
        return self.folder_meta.folder_meta_full()

    def upsert_folder_meta(self, folder_key: str, *, custom_name: str | None,
                           starred: bool, level: str | None, ref_prompt_id: str | None):
        return self.folder_meta.upsert_folder_meta(
            folder_key, custom_name=custom_name, starred=starred,
            level=level, ref_prompt_id=ref_prompt_id)

    def delete_folder_meta(self, folder_key: str):
        return self.folder_meta.delete_folder_meta(folder_key)

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

    # --- custom folders (see origenerator.db_custom_folders) ----------------

    def create_custom_folder(self, name: str, folder_id: int | None = None) -> int:
        return self.custom_folders.create_custom_folder(name, folder_id)

    def rename_custom_folder(self, folder_id: int, name: str):
        return self.custom_folders.rename_custom_folder(folder_id, name)

    def delete_custom_folder(self, folder_id: int):
        return self.custom_folders.delete_custom_folder(folder_id)

    def add_custom_folder_members(self, folder_id: int, members: list[tuple]):
        return self.custom_folders.add_custom_folder_members(folder_id, members)

    def remove_custom_folder_member(self, folder_id: int, folder_key: str):
        return self.custom_folders.remove_custom_folder_member(folder_id, folder_key)

    def list_custom_folders(self) -> list[dict]:
        return self.custom_folders.list_custom_folders()

    def custom_folder_members_full(self) -> list[dict]:
        return self.custom_folders.custom_folder_members_full()

    def repoint_custom_folder_member(self, folder_id: int, old_key: str, new_key: str,
                                     *, level: str | None, ref_prompt_id: str | None):
        return self.custom_folders.repoint_custom_folder_member(
            folder_id, old_key, new_key, level=level, ref_prompt_id=ref_prompt_id)

    def stamp_custom_folder_member(self, folder_id: int, folder_key: str,
                                   *, level: str | None, ref_prompt_id: str | None):
        return self.custom_folders.stamp_custom_folder_member(
            folder_id, folder_key, level=level, ref_prompt_id=ref_prompt_id)
