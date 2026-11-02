from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import gallery
from origenerator.config import DB_PATH, OUTPUT_PLACES, THUMB_DIR
from origenerator.db import Database
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path


def videos_without_one(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if not animated_thumbnail_path(thumb_dir, row["prompt_id"]).exists()
            and gallery.video_file_of(row, places) is not None]


def main(argv=None, *, db_path: Path = DB_PATH, places: OutputPlaces = OUTPUT_PLACES,
         thumb_dir: Path = THUMB_DIR) -> int:
    parser = argparse.ArgumentParser(
        description="Make the animated thumbnail of every finished video that has none")
    parser.add_argument("--apply", action="store_true",
                        help="actually make them; without this, only report")
    args = parser.parse_args(argv)

    rows = videos_without_one(Database(db_path).list_generations(), places, thumb_dir)
    print(f"{len(rows)} video(s) with no animated thumbnail")
    if not args.apply:
        print("re-run with --apply to make them")
        return 0
    made = sum(gallery.make_animated_preview(row, places, thumb_dir) is not None for row in rows)
    print(f"made {made}; {len(rows) - made} could not be read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
