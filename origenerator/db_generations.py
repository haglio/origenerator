"""Every image and video this app knows about: one row per generation.

A row carries the run that made it (the workflow and its params, the prompts, the
seed), what became of it (status, output files, thumbnail, how long it took), and
the marks the user and the two export lanes leave on it. The DDL and the column
list are in :mod:`origenerator.db_schema`; evolver reads seven of these columns
read-only, so tests/test_db_schema.py holds them.
"""
from __future__ import annotations

import json
import threading

from origenerator.db_connection import SqliteFile, Store
from origenerator.db_schema import GENERATION_COLUMNS, as_read, as_stored
from origenerator.generation_state import (
    MADE_ELSEWHERE,
    UNLISTED,
    GenerationSource,
    GenerationStatus,
)

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

#: Set while a sibling app is holding a copy of the row's clip, one column per
#: lane it can be sent down (:meth:`GenerationStore._record_send` clears it
#: again when the send is taken back).
SENT_COLUMNS = ("evolver_exported_at", "genau_exported_at")

_KNOWN_SOURCES = tuple(GenerationSource)
_OF_A_KNOWN_SOURCE = f"source IN ({', '.join('?' * len(_KNOWN_SOURCES))})"
_MADE_HERE = f"source NOT IN ({', '.join('?' * len(MADE_ELSEWHERE))})"
_LISTED = f"source NOT IN ({', '.join('?' * len(UNLISTED))})"


def was_sent(row: dict) -> bool:
    return any(map(row.get, SENT_COLUMNS))


def was_kept(row: dict) -> bool:
    return bool(row.get("starred")) or was_sent(row)


def library_paths_in(output_files: str | None) -> set[str]:
    try:
        files = json.loads(output_files or "[]")
    except (ValueError, TypeError):
        return set()
    return {file["library_path"] for file in files
            if isinstance(file, dict) and file.get("library_path")} if isinstance(files, list) else set()


class GenerationStore(Store):
    """The queries over the `generations` table."""

    def __init__(self, file: SqliteFile):
        super().__init__(file)
        self._version = file.version
        self._listed: tuple[int, list[dict]] | None = None
        self._listing = threading.Lock()

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
        """Set one column to now. A marker whose value is only ever tested for
        presence; the database's clock, so the stamp reads the same as every
        other one on the row."""
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {column} = datetime('now')"
                " WHERE prompt_id = ?",
                (prompt_id,),
            )

    def _record_send(self, prompt_id: str, at_column: str, unsent_column: str,
                     *, sent: bool):
        """Say whether a sibling app is holding this clip — both stamps at once,
        because half-written the row would either hide a copy the sibling still
        holds or condemn one that was just handed over."""
        held, taken_back = ("datetime('now')", "NULL") if sent else ("NULL", "datetime('now')")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {at_column} = {held},"
                f" {unsent_column} = {taken_back} WHERE prompt_id = ?",
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
        source: str = GenerationSource.GENERATED,
        provenance: str | None = None,
        shielded: bool = False,
    ):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO generations
                   (prompt_id, source, workflow_name, workflow_version,
                    positive_prompt, negative_prompt, seed,
                    params_json, workflow_json, provenance, shielded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prompt_id, source, workflow_name, workflow_version,
                 positive_prompt, negative_prompt, seed,
                 params_json, workflow_json, provenance, 1 if shielded else 0),
            )

    def update_generation(self, prompt_id: str, **fields):
        """Move a job along: any of :data:`LIFECYCLE_COLUMNS`, in one statement.

        A column outside that set is refused by name rather than dropped, because
        the drop was silent. Callers build the field dict conditionally, so no
        fields at all is a normal outcome and stays a no-op.
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

    def set_params_and_workflow(self, prompt_id: str, *, params_json: str, workflow_json: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET params_json = ?, workflow_json = ? WHERE prompt_id = ?",
                (params_json, workflow_json, prompt_id),
            )

    def set_settings_source(self, prompt_id: str, *, category: str | None = None,
                            video_prompt_id: str | None = None):
        """Record where a combine launch got its settings: the act picked in the
        dropdown, and the video whose settings the run re-uses. Written after the
        launch, because only the caller that built the combination knows either;
        empty values are stored as NULL, so each records the half it has."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET recipe_category = ?, recipe_video_id = ? "
                "WHERE prompt_id = ?",
                (category or None, video_prompt_id or None, prompt_id),
            )

    def set_enhance_target(self, prompt_id: str, source_prompt_id: str | None):
        """Record which image the standalone enhance ``prompt_id`` is of.

        Written straight after the launch, like :meth:`set_settings_source`: the
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

    def set_provenance(self, blocks: dict[str, str]):
        """Write each row's provenance block, keyed by prompt_id, in one
        transaction: the first launch after this shipped writes every row in
        the library, and a commit apiece took half a minute of it."""
        with self._connect() as conn:
            conn.executemany(
                "UPDATE generations SET provenance = ? WHERE prompt_id = ?",
                [(block, prompt_id) for prompt_id, block in blocks.items()],
            )

    def set_recorded_fields(self, rows: list[dict]):
        with self._connect() as conn:
            conn.executemany(
                "UPDATE generations SET source = :source, workflow_name = :workflow_name,"
                " params_json = :params_json,"
                " positive_prompt = :positive_prompt, negative_prompt = :negative_prompt,"
                " seed = :seed, recipe_category = :act, created_at = :created_at,"
                " completed_at = :completed_at WHERE prompt_id = :prompt_id",
                rows,
            )

    def set_generation_favorite(self, prompt_id: str, favorite: bool):
        """Favorite (or unfavorite) one generation — the user's per-item bookmark.

        Its own method rather than a key of update_generation, which covers a
        job's lifecycle rather than a user gesture like this.
        """
        self._set(prompt_id, "starred", 1 if favorite else 0)

    def set_experiment_verdict(self, prompt_id: str, verdict: str | None):
        """Record the user's review of a background experiment: ``'up'`` (keep),
        ``'down'`` (reject), or ``None`` (back to unreviewed — an undone verdict).

        Its own method rather than a key of update_generation, which covers a
        job's lifecycle rather than a user gesture like this.
        """
        self._set(prompt_id, "experiment_verdict", verdict)

    def set_picture_state(self, prompt_id: str, state: str | None):
        """Record what a still picture was sorted as showing, or ``None`` to take
        the sorting back, which puts it among the ones still to be looked at."""
        self._set(prompt_id, "picture_state", state or None)

    def set_act(self, prompt_id: str, act: str | None):
        self._set(prompt_id, "recipe_category", act or None)

    def set_shielded(self, prompt_id: str, shielded: bool):
        self._set(prompt_id, "shielded", 1 if shielded else 0)

    def set_backfill_of(self, prompt_id: str, video_prompt_id: str):
        self._set(prompt_id, "backfill_of", video_prompt_id)

    def set_source(self, prompt_id: str, source: str):
        self._set(prompt_id, "source", source)

    def owe_a_fun_time_favorite(self, prompt_id: str):
        self._set(prompt_id, "fun_time_favorite_owed", 1)

    def mark_evolver_exported(self, prompt_id: str):
        """Record that this generation's video was sent to Evolver's inbox.

        Stamps the current time so the gallery remembers the send across
        sessions, and retracts any earlier withdrawal in the same write: a clip
        handed over again must not still be down for deletion.
        """
        self._record_send(prompt_id, "evolver_exported_at", "evolver_unsent_at",
                          sent=True)

    def mark_evolver_unsent(self, prompt_id: str):
        """Take that send back: Evolver is to delete every copy it holds.

        The send was a file copy into another app's folders, so undoing it is a
        file delete, and only that app can find the copies — it has sorted,
        upscaled and re-filed them since. This stamp is the whole of the ask, and
        Evolver reads it out of this table on its next run.
        """
        self._record_send(prompt_id, "evolver_exported_at", "evolver_unsent_at",
                          sent=False)

    def mark_genau_exported(self, prompt_id: str):
        """Record that this generation's clip was sent down the Genau lane.

        The twin of :meth:`mark_evolver_exported`, down to retracting a
        withdrawal: the two lanes are separate errands and each keeps its own
        pair of stamps.
        """
        self._record_send(prompt_id, "genau_exported_at", "genau_unsent_at",
                          sent=True)

    def mark_genau_unsent(self, prompt_id: str):
        """Take the Genau send back — the twin of :meth:`mark_evolver_unsent`.

        A clip this far down the lane has left the pipeline for the folder Genau
        plays from, which is the reason the delete cannot be done from here.
        """
        self._record_send(prompt_id, "genau_exported_at", "genau_unsent_at",
                          sent=False)

    def mark_genau_requested(self, prompt_id: str):
        """Record that a spoken animation started this run.

        Stamped at launch, read at completion: it is what tells the finished clip
        to hand itself to the Genau lane without a second ask.
        """
        self._stamp(prompt_id, "genau_requested_at")

    def recent_durations(self, workflow_name: str, limit: int = 10) -> list[float]:
        """Most-recent measured generation times for a workflow, newest first.

        Only completed rows with a recorded ``duration_seconds`` count, so the
        result feeds duration estimates directly.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT duration_seconds FROM generations
                   WHERE workflow_name = ?
                     AND status = ?
                     AND duration_seconds IS NOT NULL
                   ORDER BY id DESC
                   LIMIT ?""",
                (workflow_name, GenerationStatus.COMPLETED, limit),
            ).fetchall()
            return [r[0] for r in rows]

    def completed_without_duration(self) -> list[dict]:
        """Completed rows that have a finish time but no recorded duration.

        These are the candidates for log-based backfill: their ``completed_at``
        (the output file's mtime) is what a log line gets matched against.
        """
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM generations
                   WHERE status = ?
                     AND duration_seconds IS NULL
                     AND completed_at IS NOT NULL
                     AND {_OF_A_KNOWN_SOURCE}
                     AND {_MADE_HERE}
                   ORDER BY id""",
                (GenerationStatus.COMPLETED, *_KNOWN_SOURCES, *MADE_ELSEWHERE),
            ).fetchall()
            return [as_read(r) for r in rows]

    def highest_id_issued(self) -> int:
        """The largest id this table has ever handed out, deleted rows included.

        ``max(id)`` answers what is still here; the gap between the two is every
        row that has been and gone, such as the transient row an enhancement runs
        under. AUTOINCREMENT keeps the real high-water mark in ``sqlite_sequence``,
        which says whether an id recorded elsewhere could ever have been one of
        this table's own (:func:`~origenerator.branch_session.disown_foreign_runs`).
        A table that has issued nothing answers 0.
        """
        with self._connect() as conn:
            for sql in ("SELECT seq FROM sqlite_sequence WHERE name = 'generations'",
                        "SELECT max(id) FROM generations"):
                row = conn.execute(sql).fetchone()
                if row is not None and row[0] is not None:
                    return int(row[0])
            return 0

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
        self.insert_rows([row])

    def insert_rows(self, rows: list[dict]):
        with self._connect() as conn:
            for row in map(as_stored, rows):
                cols = [c for c in GENERATION_COLUMNS if c in row]
                conn.execute(
                    f"INSERT INTO generations ({', '.join(cols)})"
                    f" VALUES ({', '.join('?' for _ in cols)})",
                    [row[c] for c in cols],
                )

    def get_generation(self, prompt_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM generations WHERE prompt_id = ? AND {_OF_A_KNOWN_SOURCE}",
                (prompt_id, *_KNOWN_SOURCES),
            ).fetchone()
            return as_read(row) if row else None

    def library_version(self) -> int:
        return self._version()

    def list_generations(self) -> list[dict]:
        with self._listing:
            version = self._version()
            if self._listed is None or self._listed[0] != version:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT * FROM generations WHERE {_OF_A_KNOWN_SOURCE}"
                        f" AND {_LISTED} ORDER BY id DESC",
                        (*_KNOWN_SOURCES, *UNLISTED),
                    ).fetchall()
                self._listed = (version, [as_read(r) for r in rows])
            return [dict(r) for r in self._listed[1]]

    def replaced_generations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM generations WHERE source = ?",
                                (GenerationSource.REPLACED,)).fetchall()
        return [dict(row) for row in rows]

    def rows_made_by(self, workflow_name: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM generations WHERE workflow_name = ? AND {_OF_A_KNOWN_SOURCE}"
                " AND source != ? ORDER BY id DESC",
                (workflow_name, *_KNOWN_SOURCES, GenerationSource.LEFT_OUT),
            ).fetchall()
            return [dict(row) for row in rows]

    def library_paths(self) -> set[str]:
        with self._connect() as conn:
            lists = conn.execute("SELECT output_files FROM generations"
                                 " WHERE output_files LIKE '%library_path%'").fetchall()
        return {path for files in lists for path in library_paths_in(files[0])}

    def seed_history_rows(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompt_id, seed, params_json, output_files, thumbnail_path, status,"
                " workflow_name, created_at FROM generations ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def custom_combinations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompt_id, recipe_video_id, created_at FROM generations"
                " WHERE recipe_video_id IS NOT NULL AND recipe_category IS NULL"
                " ORDER BY id DESC"
            ).fetchall()
            return [as_read(r) for r in rows]
