from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import gallery
from origenerator.config import DB_PATH, OUTPUT_PLACES, THUMB_DIR
from origenerator.db import Database
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path, at_its_videos_pace


def videos_without_one(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if not animated_thumbnail_path(thumb_dir, row["prompt_id"]).exists()
            and gallery.video_file_of(row, places) is not None]


def videos_at_the_wrong_pace(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if (made := animated_thumbnail_path(thumb_dir, row["prompt_id"])).exists()
            and (video := gallery.video_file_of(row, places)) is not None
            and not at_its_videos_pace(made, video)]


def main(argv=None, *, db_path: Path = DB_PATH, places: OutputPlaces = OUTPUT_PLACES,
         thumb_dir: Path = THUMB_DIR) -> int:
    parser = argparse.ArgumentParser(
        description="Make the animated thumbnail of every finished video that has none, and again"
                    " for every one that changes at the wrong pace for its video's length")
    parser.add_argument("--apply", action="store_true",
                        help="actually make them; without this, only report")
    args = parser.parse_args(argv)

    listed = Database(db_path).list_generations()
    rows = videos_without_one(listed, places, thumb_dir)
    mispaced = videos_at_the_wrong_pace(listed, places, thumb_dir)
    print(f"{len(rows)} video(s) with no animated thumbnail")
    print(f"{len(mispaced)} video(s) whose animated thumbnail changes at the wrong pace")
    if not args.apply:
        print("re-run with --apply to make them")
        return 0
    made = sum(gallery.make_animated_preview(row, places, thumb_dir, again=row in mispaced)
               is not None for row in [*rows, *mispaced])
    print(f"made {made}; {len(rows) + len(mispaced) - made} could not be read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
