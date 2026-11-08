from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app_support import kino_folder

from origenerator.funscript import funscript_path_for
from origenerator.gallery.output import parse_file_list, place_of_its_own
from origenerator.output_places import OutputPlaces

logger = logging.getLogger(__name__)

FILE_LISTS = ("output_files", "original_files")


def _by_name(places: OutputPlaces) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for path, subfolder in places.files():
        index[path.name].add(subfolder)
    return index


def _followed(files: list, index: dict[str, set[str]], places: OutputPlaces) -> int:
    moved = 0
    for record in files:
        if not isinstance(record, dict) or place_of_its_own(record):
            continue
        name = record.get("filename") or ""
        holders = index.get(name, set())
        was = record.get("subfolder") or ""
        if len(holders) != 1 or was in holders:
            continue
        record["subfolder"] = next(iter(holders))
        _move_script(places.folder(was) / name, places.folder(record["subfolder"]) / name,
                     places)
        moved += 1
    return moved


def _move_script(was: Path, now: Path, places: OutputPlaces) -> None:
    script = funscript_path_for(was, places=places)
    destination = funscript_path_for(now, places=places)
    if script.is_file() and not destination.exists():
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            script.rename(destination)
        except OSError as e:
            logger.warning("A moved video's script stayed at %s: %s", script, e)


def relocate_moved_outputs(db, places: OutputPlaces) -> int:
    index = _by_name(places)
    moved = 0
    for row in db.list_generations():
        updates = {}
        for column in FILE_LISTS:
            files = parse_file_list(row.get(column))
            followed = _followed(files, index, places) if files else 0
            if followed:
                updates[column] = json.dumps(files)
                moved += followed
        if updates:
            db.update_generation(row["prompt_id"], **updates)
    return moved


@dataclass(frozen=True)
class _OutOf2Outbox:
    library_root: Path
    kino: Path

    def __call__(self, value):
        if isinstance(value, dict):
            return {key: self._a_file_list(inner) if key in FILE_LISTS else self(inner)
                    for key, inner in value.items()}
        if isinstance(value, list):
            return [self(inner) for inner in value]
        if isinstance(value, str) and value:
            went = kino_folder.where_it_went(Path(value), self.library_root, self.kino)
            return value if went is None else str(went)
        return value

    def _a_file_list(self, listed):
        if not isinstance(listed, str):
            return self(listed)
        files = parse_file_list(listed)
        now = self(files)
        return listed if now == files else json.dumps(now)


def follow_kinos_upscales_out_of_2_outbox(db, library_root: Path, kino: Path) -> int:
    out_of_2_outbox = _OutOf2Outbox(library_root, kino)
    followed = 0
    for row in db.list_generations():
        updates = {column: json.dumps(now) for column in FILE_LISTS
                   if (was := parse_file_list(row.get(column))) and (now := out_of_2_outbox(was)) != was}
        if updates:
            db.update_generation(row["prompt_id"], **updates)
            followed += 1
    return followed + db.follow_trashed(out_of_2_outbox)
