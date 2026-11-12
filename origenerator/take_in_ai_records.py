from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from app_support.json_store import read_json
from app_support.mirrored_tree import library_roots_beside, mirrored_source
from app_support.video_ids import VIDEO_SUFFIXES
from app_support.watch_weights import WATCH_BLOCK, add_counts

from origenerator.db import Database
from origenerator.db_generations import WATCH_COLUMN_OF
from origenerator.gallery.signatures import parse_params
from origenerator.generation_state import GenerationSource, source_of
from origenerator.media import MediaType
from origenerator.outside_videos import made_of, seed_number
from origenerator.video_rows import VideoRows
from origenerator.workflows.outside import PLACES

AI_RECORDS = (("kino",), ("origenerator", "video"), ("genau",))
NON_AI_FOLDER = "non_AI"
COUNTED = ("records read", "unreadable", "no video", "no row", "matched", "stars added",
           "counts written", "library records written", "actions added", "settings filled in")


class Call(NamedTuple):
    method: str
    args: tuple
    kwargs: dict | None = None


class Write(NamedTuple):
    counted_as: str
    calls: tuple[Call, ...]


def take_in(db, library: Path, *, dry_run: bool = False) -> Counter:
    counts: Counter = Counter()
    records_folder = Path(library) / "videos" / "metadata"
    row_of = VideoRows(db.list_generations())
    for sidecar in _ai_sidecars(records_folder):
        counts["records read"] += 1
        try:
            record = read_json(sidecar)
        except (OSError, ValueError):
            counts["unreadable"] += 1
            continue
        video = mirrored_source(sidecar, roots=library_roots_beside(records_folder),
                                mirror_root=records_folder, suffixes=VIDEO_SUFFIXES)
        if video is None:
            counts["no video"] += 1
            continue
        prompt_id = row_of(video)
        if prompt_id is None:
            counts["no row"] += 1
            continue
        counts["matched"] += 1
        for write in writes_for(db.get_generation(prompt_id), record):
            counts[write.counted_as] += 1
            for call in write.calls if not dry_run else ():
                getattr(db, call.method)(*call.args, **(call.kwargs or {}))
    return counts


def writes_for(row: dict, record: dict) -> list[Write]:
    prompt_id = row["prompt_id"]
    writes = []
    if record.get("favorite") is True and not row.get("starred"):
        writes.append(Write("stars added", (Call("set_generation_favorite", (prompt_id, True)),)))
    watched = add_counts(_block(record, WATCH_BLOCK))
    if watched != add_counts({field: row.get(column) for field, column in WATCH_COLUMN_OF.items()}):
        writes.append(Write("counts written", (Call("set_watch_counts", (prompt_id, watched)),)))
    kept = _library_record(record)
    if any(row.get(column) != value for column, value in kept.items()):
        writes.append(Write("library records written",
                            (Call("set_library_record", (prompt_id,), kept),)))
    action = _block(record, "video").get("action")
    if action and not row.get("action"):
        writes.append(Write("actions added", (Call("set_action", (prompt_id, action)),)))
    if source_of(row) == GenerationSource.OUTSIDE and (filled := _settings_filled_in(row, record)):
        writes.append(Write("settings filled in", filled))
    return writes


def _settings_filled_in(row: dict, record: dict) -> tuple[Call, ...]:
    prompt_id, params = row["prompt_id"], parse_params(row.get("params_json"))
    recorded = made_of(_block(record, "video"), PLACES[MediaType.VIDEO]).params
    missing = {key: value for key, value in recorded.items() if params.get(key) in (None, "")}
    if not missing:
        return ()
    columns = {"positive_prompt": missing.get("positive_prompt"),
               "seed": seed_number(missing.get("seed"))}
    return (Call("set_params_json", (prompt_id, json.dumps({**params, **missing}))),
            *(Call("fill_in", (column, {prompt_id: value})) for column, value in columns.items()
              if value is not None and row.get(column) is None))


def _library_record(record: dict) -> dict:
    upscale = _block(record, "provenance").get("upscale")
    kept = {"web_url": record.get("web_url"), "library_id": record.get("id"),
            "upscale_provenance": json.dumps(upscale) if upscale else None}
    return {column: value for column, value in kept.items() if value}


def _block(record: dict, name: str) -> dict:
    block = record.get(name)
    return block if isinstance(block, dict) else {}


def _ai_sidecars(records_folder: Path) -> list[Path]:
    return [sidecar for parts in AI_RECORDS
            for sidecar in sorted(records_folder.joinpath(*parts).rglob("*.json"))
            if NON_AI_FOLDER not in sidecar.relative_to(records_folder).parts]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m origenerator.take_in_ai_records")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print("no gallery at the path given")
        return 2
    counts = take_in(Database(args.db), args.library, dry_run=args.dry_run)
    for name in COUNTED:
        print(f"{name}: {counts[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
