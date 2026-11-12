from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path

from app_support.gallery_rows import VideoRows
from app_support.json_store import read_json
from app_support.logging_utils import configure_logging, install_exception_logging

from origenerator import config
from origenerator.db import Database
from origenerator.outside_videos import Places, places_here, take_record
from origenerator.thumbnail import first_frame_of
from origenerator.warm_gun_records import PhoneRecords

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="origenerator.ai_video_records")
    verbs = parser.add_subparsers(dest="verb", required=True)
    record = verbs.add_parser("record")
    record.add_argument("--video", type=Path, required=True)
    record.add_argument("--record", type=Path, required=True)
    watched = verbs.add_parser("watched")
    watched.add_argument("--totals", type=Path, required=True)
    favorite = verbs.add_parser("favorite")
    favorite.add_argument("--video", type=Path, required=True)
    starred = favorite.add_mutually_exclusive_group(required=True)
    starred.add_argument("--on", dest="starred", action="store_true")
    starred.add_argument("--off", dest="starred", action="store_false")
    flipped = verbs.add_parser("flipped")
    flipped.add_argument("--video", type=Path, required=True)
    turned = flipped.add_mutually_exclusive_group(required=True)
    turned.add_argument("--on", dest="flipped", action="store_true")
    turned.add_argument("--off", dest="flipped", action="store_false")
    upscaled = verbs.add_parser("upscaled")
    upscaled.add_argument("--video", type=Path, required=True)
    upscaled.add_argument("--provenance", type=Path, required=True)
    return parser


def this_librarys_phone_records(db) -> PhoneRecords:
    return PhoneRecords.of_this_library(db, preview=False)


def main(argv: list[str] | None = None, *, db_path: Path | None = None,
         places: Callable[[], Places | None] = places_here, grab=first_frame_of,
         log_to: Callable[[str, Path], object] = configure_logging,
         phone_records: Callable[[Database], object] = this_librarys_phone_records) -> int:
    args = _parser().parse_args(argv)
    log_to("", config.STATE_DIR / "origenerator.log")
    install_exception_logging(logger)
    db = Database(config.DB_PATH if db_path is None else db_path)
    if args.verb == "record":
        found = [take_record(db, args.video, read_json(args.record), places=places(), grab=grab)]
    elif args.verb == "watched":
        found = [_on_its_row(db, Path(video), "set_watch_counts", counts)
                 for video, counts in read_json(args.totals).items()]
    elif args.verb == "favorite":
        found = [_on_its_row(db, args.video, "set_generation_favorite", args.starred)]
    elif args.verb == "flipped":
        found = [_on_its_row(db, args.video, "set_library_record", genau_flipped=int(args.flipped))]
    else:
        found = [_on_its_row(db, args.video, "set_library_record",
                             upscale_provenance=json.dumps(read_json(args.provenance)))]
    phone_records(db).write()
    print(json.dumps({"done": sum(found), "no_row": len(found) - sum(found)}))
    return 0


def _on_its_row(db, video: Path, write: str, *args, **kwargs) -> bool:
    prompt_id = VideoRows(db.list_generations())(video)
    if prompt_id is not None:
        getattr(db, write)(prompt_id, *args, **kwargs)
    return prompt_id is not None


if __name__ == "__main__":
    raise SystemExit(main())
