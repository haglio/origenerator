from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from app_support.watch_weights import COUNT_FIELDS

from origenerator.box_breaks import unboxed
from origenerator.db_connection import SqliteFile, Store
from origenerator.db_schema import (
    GENERATION_COLUMNS,
    WAITS_FOR_ITS_FINISH,
    as_read,
    as_stored,
)
from origenerator.gallery.output import FilesMade
from origenerator.generation_state import (
    MADE_ELSEWHERE,
    UNLISTED,
    GenerationSource,
    GenerationStatus,
)
from origenerator.item_actions import ItemActions, columns, stored
from origenerator.output_files import library_paths_in

LIFECYCLE_COLUMNS = frozenset({
    "status", "output_files", "original_files", "enhance_history",
    "thumbnail_path", "error_message", "completed_at", "duration_seconds",
    "progress_json", "shape",
})

SENT_COLUMNS = ("evolver_exported_at", "genau_exported_at")

TRASH_WHEN_FINISHED = "trash"
ENHANCE_WHEN_FINISHED = "enhance"
_FORGET_THE_TRASH = "UPDATE generations SET trash_requested_at = NULL WHERE prompt_id = ?"
_FORGET_THE_ENHANCE = "UPDATE generations SET enhance_requested_at = NULL WHERE prompt_id = ?"
_ASKED_WHEN_FINISHED = (
    "SELECT prompt_id, trash_requested_at, enhance_requested_at FROM generations"
    f" WHERE status = ? AND ({WAITS_FOR_ITS_FINISH})")

WATCH_COLUMNS = tuple((field, f"watch_{field}") for field in COUNT_FIELDS)
def watch_columns_of(counts: dict) -> dict[str, int]:
    return {column: int(counts.get(field) or 0) for field, column in WATCH_COLUMNS}


LIBRARY_RECORD_COLUMNS = frozenset({"web_url", "library_id", "upscale_provenance",
                                    "video_seconds", "video_frames", "genau_flipped",
                                    "video_resolution",
                                    "video_aspect_ratio"})

_KNOWN_SOURCES = tuple(GenerationSource)
_OF_A_KNOWN_SOURCE = f"source IN ({', '.join('?' * len(_KNOWN_SOURCES))})"
MADE_HERE = f"source NOT IN ({', '.join('?' * len(MADE_ELSEWHERE))})"
_IDS_PER_QUERY = 500
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


def _read_whole(prompt: str | None) -> str | None:
    return None if prompt is None else unboxed(prompt)


class GenerationStore(Store):
    def __init__(self, file: SqliteFile):
        super().__init__(file)
        self._version = file.version
        self._file = file
        self._own_changes = file.log_own_changes("generations", "prompt_id")
        self._listed: list[dict] | None = None
        self._listed_ids: frozenset[str] = frozenset()
        self._files_made = FilesMade()
        self._listing = threading.Lock()

    def _set(self, prompt_id: str, column: str, value):
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {column} = ? WHERE prompt_id = ?",
                (value, prompt_id),
            )

    def _set_columns(self, prompt_id: str, fields: dict):
        if not fields:
            return
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {', '.join(f'{k} = ?' for k in fields)}"
                " WHERE prompt_id = ?",
                (*fields.values(), prompt_id),
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
        self._set_columns(prompt_id, fields)

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

    def set_cut_from(self, prompt_id: str, source_prompt_id: str | None):
        self._set(prompt_id, "trimmed_from", source_prompt_id or None)

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

    def say_why_it_cannot_be_made_again(self, prompt_id: str, reason: str):
        self._set(prompt_id, "why_it_cannot_be_made_again", reason)

    def set_image_state(self, prompt_id: str, state: str | None):
        self._set(prompt_id, "picture_state", state or None)

    def set_action(self, prompt_id: str, action: str | None):
        self._set(prompt_id, "recipe_category", action or None)

    def set_actions(self, prompt_id: str, side: str, item_actions: ItemActions | None):
        self.set_many_actions(side, {prompt_id: item_actions})

    def set_many_actions(self, side: str, actions_by_id: dict[str, ItemActions | None]):
        actions, checked = columns(side)
        with self._connect() as conn:
            conn.executemany(
                f"UPDATE generations SET {actions} = ?, {checked} = ? WHERE prompt_id = ?",
                [(*(stored(item_actions) if item_actions is not None else (None, None)), prompt_id)
                 for prompt_id, item_actions in actions_by_id.items()],
            )

    def set_shielded(self, prompt_id: str, shielded: bool):
        self._set(prompt_id, "shielded", 1 if shielded else 0)

    def save_running_progress(self, prompt_id: str, progress_json: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET progress_json = ? WHERE prompt_id = ? AND status = ?",
                (progress_json, prompt_id, GenerationStatus.RUNNING),
            )

    def set_source(self, prompt_id: str, source: str):
        self._set(prompt_id, "source", source)

    def set_backfill_of(self, prompt_id: str, item_prompt_id: str):
        self._set(prompt_id, "backfill_of", item_prompt_id)

    def remake_in_place(self, prompt_id: str, remade: dict):
        taken = ("workflow_version", "positive_prompt", "negative_prompt", "seed", "params_json",
                 "workflow_json", "provenance", "output_files", "thumbnail_path",
                 "duration_seconds")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE generations SET {', '.join(f'{column} = ?' for column in taken)},"
                " remade_at = datetime('now') WHERE prompt_id = ?",
                [*(remade.get(column) for column in taken), prompt_id])
            conn.execute("DELETE FROM generations WHERE prompt_id = ?", (remade["prompt_id"],))

    def set_evolver_upscale(self, prompt_id: str, path: str, upscaled_at: str | None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE generations SET evolver_upscale = ?, evolver_upscaled_at = ? "
                "WHERE prompt_id = ?",
                (path, upscaled_at, prompt_id),
            )

    def set_watch_counts(self, prompt_id: str, counts: dict):
        self._set_columns(prompt_id, watch_columns_of(counts))

    def set_many_watch_counts(self, counts_by_id: dict[str, dict]):
        if not counts_by_id:
            return
        columns = [column for _field, column in WATCH_COLUMNS]
        with self._connect() as conn:
            conn.executemany(
                f"UPDATE generations SET {', '.join(f'{c} = ?' for c in columns)}"
                " WHERE prompt_id = ?",
                [(*watch_columns_of(counts).values(), prompt_id)
                 for prompt_id, counts in counts_by_id.items()])

    def set_library_record(self, prompt_id: str, **fields):
        refused = set(fields) - LIBRARY_RECORD_COLUMNS
        if refused:
            raise ValueError(
                f"set_library_record does not write {', '.join(sorted(refused))}; it writes "
                f"{', '.join(sorted(LIBRARY_RECORD_COLUMNS))}.")
        self._set_columns(prompt_id, fields)

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

    def ask_when_finished(self, prompt_id: str, wish: str):
        if wish == TRASH_WHEN_FINISHED:
            self._stamp(prompt_id, "trash_requested_at")
        else:
            self._stamp(prompt_id, "enhance_requested_at")

    def forget_when_finished(self, prompt_id: str, wish: str):
        statement = (_FORGET_THE_TRASH if wish == TRASH_WHEN_FINISHED
                     else _FORGET_THE_ENHANCE)
        with self._connect() as conn:
            conn.execute(statement, (prompt_id,))

    def asked_when_finished(self) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(_ASKED_WHEN_FINISHED, (GenerationStatus.COMPLETED,)).fetchall()
        return ([(row[0], TRASH_WHEN_FINISHED) for row in rows if row[1]]
                + [(row[0], ENHANCE_WHEN_FINISHED) for row in rows if row[2]])

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
                     AND {MADE_HERE}
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

    def in_one_go(self):
        return self._connect()

    def get_generations(self, prompt_ids) -> dict[str, dict]:
        prompt_ids = list(dict.fromkeys(prompt_ids))
        found = {}
        with self._connect() as conn:
            for start in range(0, len(prompt_ids), _IDS_PER_QUERY):
                chunk = prompt_ids[start:start + _IDS_PER_QUERY]
                for row in conn.execute(
                        f"SELECT * FROM generations WHERE prompt_id IN ({', '.join('?' * len(chunk))})"
                        f" AND {_OF_A_KNOWN_SOURCE}", (*chunk, *_KNOWN_SOURCES)):
                    read = as_read(row)
                    found[read["prompt_id"]] = read
        return found

    def library_version(self) -> int:
        return self._version()

    def when_changed(self, told: Callable[[], None]) -> None:
        self._file.when_written(told)

    def list_generations(self) -> list[dict]:
        with self._listing:
            return [dict(r) for r in self._brought_up_to_date()]

    def generation_of_file(self, path) -> str | None:
        with self._listing:
            listed = self._brought_up_to_date()
            found = self._files_made.generation_of(path)
            if found is None or found in self._listed_ids:
                return found
            return FilesMade.of(listed).generation_of(path)

    def _brought_up_to_date(self) -> list[dict]:
        changed = self._own_changes.changed_since_last_asked()
        if self._listed is None or changed is None:
            self._listed = self._read_listed("", ())
            self._files_made = FilesMade.of(self._listed)
        elif changed:
            read_again = self._read_listed_among(sorted(changed))
            self._listed = sorted(
                [row for row in self._listed if row["prompt_id"] not in changed] + read_again,
                key=lambda row: row["id"], reverse=True)
            self._files_made.add(read_again)
        else:
            return self._listed
        self._listed_ids = frozenset(row["prompt_id"] for row in self._listed)
        return self._listed

    def _read_listed_among(self, prompt_ids: list[str]) -> list[dict]:
        return [row for start in range(0, len(prompt_ids), _IDS_PER_QUERY)
                for chunk in [prompt_ids[start:start + _IDS_PER_QUERY]]
                for row in self._read_listed(
                    f" AND prompt_id IN ({', '.join('?' * len(chunk))})", chunk)]

    def _read_listed(self, narrowed: str, among) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM generations WHERE {_OF_A_KNOWN_SOURCE}"
                f" AND {_LISTED}{narrowed} ORDER BY id DESC",
                (*_KNOWN_SOURCES, *UNLISTED, *among),
            ).fetchall()
        return [as_read(r) for r in rows]

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
