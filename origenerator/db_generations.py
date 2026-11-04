from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from origenerator.box_breaks import unboxed
from origenerator.db_connection import SqliteFile, Store
from origenerator.db_schema import GENERATION_COLUMNS, as_read, as_stored
from origenerator.generation_state import (
    MADE_ELSEWHERE,
    UNLISTED,
    GenerationSource,
    GenerationStatus,
)

LIFECYCLE_COLUMNS = frozenset({
    "status", "output_files", "original_files", "enhance_history",
    "thumbnail_path", "error_message", "completed_at", "duration_seconds",
    "progress_json", "shape",
})

SENT_COLUMNS = ("evolver_exported_at", "genau_exported_at")

_KNOWN_SOURCES = tuple(GenerationSource)
_OF_A_KNOWN_SOURCE = f"source IN ({', '.join('?' * len(_KNOWN_SOURCES))})"
_MADE_HERE = f"source NOT IN ({', '.join('?' * len(MADE_ELSEWHERE))})"
_LISTED = f"source NOT IN ({', '.join('?' * len(UNLISTED))})"


@dataclass(frozen=True, kw_only=True)
class NewGeneration:
    prompt_id: str
    workflow_name: str
    workflow_version: str
    positive_prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    params_json: str
    workflow_json: str
    source: str = GenerationSource.GENERATED
    provenance: str | None = None
    shielded: bool = False


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


def _read_whole(prompt: str | None) -> str | None:
    return None if prompt is None else unboxed(prompt)


class GenerationStore(Store):
    def __init__(self, file: SqliteFile):
        super().__init__(file)
        self._version = file.version
        self._listed: tuple[int, list[dict]] | None = None
        self._listing = threading.Lock()

    def _set(self, prompt_id: str, column: str, value):
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {column} = ? WHERE prompt_id = ?",
                (value, prompt_id),
            )

    def _stamp(self, prompt_id: str, column: str):
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {column} = datetime('now')"
                " WHERE prompt_id = ?",
                (prompt_id,),
            )

    def _record_send(self, prompt_id: str, at_column: str, unsent_column: str,
                     *, sent: bool):
        held, taken_back = ("datetime('now')", "NULL") if sent else ("NULL", "datetime('now')")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {at_column} = {held},"
                f" {unsent_column} = {taken_back} WHERE prompt_id = ?",
                (prompt_id,),
            )

    def insert_generation(self, new: NewGeneration):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO generations
                   (prompt_id, source, workflow_name, workflow_version,
                    positive_prompt, negative_prompt, seed,
                    params_json, workflow_json, provenance, shielded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new.prompt_id, new.source, new.workflow_name, new.workflow_version,
                 _read_whole(new.positive_prompt), _read_whole(new.negative_prompt), new.seed,
                 new.params_json, new.workflow_json, new.provenance, 1 if new.shielded else 0),
            )

    def update_generation(self, prompt_id: str, **fields):
        refused = set(fields) - LIFECYCLE_COLUMNS
        if refused:
            raise ValueError(
                f"update_generation does not write {', '.join(sorted(refused))}; "
                f"it writes a job's lifecycle ({', '.join(sorted(LIFECYCLE_COLUMNS))}). "
                "Provenance and the user's own marks have their own methods.")
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = [*list(fields.values()), prompt_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {set_clause} WHERE prompt_id = ?",
                values,
            )

    def set_workflow_name(self, prompt_id: str, workflow_name: str):
        self._set(prompt_id, "workflow_name", workflow_name)

    def set_params_json(self, prompt_id: str, params_json: str):
        self._set(prompt_id, "params_json", params_json)

    def set_params_and_workflow(self, prompt_id: str, *, params_json: str, workflow_json: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET params_json = ?, workflow_json = ? WHERE prompt_id = ?",
                (params_json, workflow_json, prompt_id),
            )

    def set_settings_source(self, prompt_id: str, *, category: str | None = None,
                            video_prompt_id: str | None = None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET recipe_category = ?, recipe_video_id = ? "
                "WHERE prompt_id = ?",
                (category or None, video_prompt_id or None, prompt_id),
            )

    def set_enhance_target(self, prompt_id: str, source_prompt_id: str | None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET enhance_of = ? WHERE prompt_id = ?",
                (source_prompt_id or None, prompt_id),
            )

    def fill_in(self, column: str, values: dict[str, str]):
        with self._connect() as conn:
            conn.executemany(
                f"UPDATE generations SET {column} = ? WHERE prompt_id = ?",
                [(value, prompt_id) for prompt_id, value in values.items()],
            )

    def set_recorded_fields(self, rows: list[dict]):
        with self._connect() as conn:
            conn.executemany(
                "UPDATE generations SET source = :source, workflow_name = :workflow_name,"
                " params_json = :params_json,"
                " positive_prompt = :positive_prompt, negative_prompt = :negative_prompt,"
                " seed = :seed, recipe_category = :action, created_at = :created_at,"
                " completed_at = :completed_at WHERE prompt_id = :prompt_id",
                rows,
            )

    def set_generation_favorite(self, prompt_id: str, favorite: bool):
        self._set(prompt_id, "starred", 1 if favorite else 0)

    def set_experiment_verdict(self, prompt_id: str, verdict: str | None):
        self._set(prompt_id, "experiment_verdict", verdict)

    def set_image_state(self, prompt_id: str, state: str | None):
        self._set(prompt_id, "picture_state", state or None)

    def set_action(self, prompt_id: str, action: str | None):
        self._set(prompt_id, "recipe_category", action or None)

    def set_shielded(self, prompt_id: str, shielded: bool):
        self._set(prompt_id, "shielded", 1 if shielded else 0)

    def set_backfill_of(self, prompt_id: str, video_prompt_id: str):
        self._set(prompt_id, "backfill_of", video_prompt_id)

    def set_source(self, prompt_id: str, source: str):
        self._set(prompt_id, "source", source)

    def take_the_content_of(self, prompt_id: str, remade: dict):
        self._set(prompt_id, "workflow_version", remade["workflow_version"])
        self._set(prompt_id, "positive_prompt", remade["positive_prompt"])
        self._set(prompt_id, "negative_prompt", remade["negative_prompt"])
        self._set(prompt_id, "seed", remade["seed"])
        self._set(prompt_id, "params_json", remade["params_json"])
        self._set(prompt_id, "workflow_json", remade["workflow_json"])
        self._set(prompt_id, "provenance", remade["provenance"])
        self.update_generation(prompt_id, output_files=remade["output_files"],
                               thumbnail_path=remade["thumbnail_path"],
                               duration_seconds=remade["duration_seconds"])

    def mark_remade(self, prompt_id: str):
        with self._connect() as conn:
            conn.execute("UPDATE generations SET remade_at = datetime('now') WHERE prompt_id = ?",
                         (prompt_id,))
    def pay_a_fun_time_favorite(self, prompt_id: str):
        self._set(prompt_id, "fun_time_favorite_owed", 0)

    def mark_evolver_exported(self, prompt_id: str):
        self._record_send(prompt_id, "evolver_exported_at", "evolver_unsent_at",
                          sent=True)

    def mark_evolver_unsent(self, prompt_id: str):
        self._record_send(prompt_id, "evolver_exported_at", "evolver_unsent_at",
                          sent=False)

    def mark_genau_exported(self, prompt_id: str):
        self._record_send(prompt_id, "genau_exported_at", "genau_unsent_at",
                          sent=True)

    def mark_genau_unsent(self, prompt_id: str):
        self._record_send(prompt_id, "genau_exported_at", "genau_unsent_at",
                          sent=False)

    def mark_genau_requested(self, prompt_id: str):
        self._stamp(prompt_id, "genau_requested_at")

    def recent_durations(self, workflow_name: str, limit: int = 10) -> list[float]:
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

    def output_files_of_every_row(self) -> list[str]:
        with self._connect() as conn:
            return [files for (files,) in conn.execute(
                "SELECT output_files FROM generations WHERE output_files IS NOT NULL")]

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
