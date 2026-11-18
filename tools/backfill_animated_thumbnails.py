from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import gallery
from origenerator.config import DB_PATH, OUTPUT_PLACES, THUMB_DIR
from origenerator.db import Database
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import (
    animated_thumbnail_path,
    at_its_videos_pace,
    generate_thumbnail,
    is_black_where_its_video_is_not,
    shows_black_among_other_frames,
    still_thumbnail_path,
)


def videos_without_one(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if not animated_thumbnail_path(thumb_dir, row["prompt_id"]).exists()
            and gallery.video_file_of(row, places) is not None]


def videos_at_the_wrong_pace(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if (made := animated_thumbnail_path(thumb_dir, row["prompt_id"])).exists()
            and (video := gallery.video_file_of(row, places)) is not None
            and not at_its_videos_pace(made, video)]


def videos_showing_a_black_frame(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if gallery.video_file_of(row, places) is not None
            and shows_black_among_other_frames(animated_thumbnail_path(thumb_dir, row["prompt_id"]))]


def videos_with_a_black_still(rows: list[dict], places: OutputPlaces, thumb_dir: Path) -> list[dict]:
    return [row for row in rows
            if gallery.video_file_of(row, places) is not None
            and row.get("thumbnail_path") == str(still := still_thumbnail_path(thumb_dir, row["prompt_id"]))
            and is_black_where_its_video_is_not(
                still, animated_thumbnail_path(thumb_dir, row["prompt_id"]))]


def main(argv=None, *, db_path: Path = DB_PATH, places: OutputPlaces = OUTPUT_PLACES,
         thumb_dir: Path = THUMB_DIR) -> int:
    parser = argparse.ArgumentParser(
        description="Make the animated thumbnail of every finished video that has none, and again"
                    " for every one that changes at the wrong pace for its video's length or shows"
                    " a black frame its video has better than")
    parser.add_argument("--apply", action="store_true",
                        help="actually make them; without this, only report")
    args = parser.parse_args(argv)

    listed = Database(db_path).list_generations()
    rows = videos_without_one(listed, places, thumb_dir)
    mispaced = videos_at_the_wrong_pace(listed, places, thumb_dir)
    print(f"{len(rows)} video(s) with no animated thumbnail")
    print(f"{len(mispaced)} video(s) whose animated thumbnail changes at the wrong pace")
    showing_black = videos_showing_a_black_frame(listed, places, thumb_dir)
    print(f"{len(showing_black)} video(s) whose animated thumbnail shows a black frame")
    print(f"{len(videos_with_a_black_still(listed, places, thumb_dir))} video(s) whose still "
          "thumbnail is black")
    if not args.apply:
        print("re-run with --apply to make them")
        return 0
    again = [*mispaced, *(row for row in showing_black if row not in mispaced)]
    made = sum(gallery.make_animated_preview(row, places, thumb_dir, again=row in again)
               is not None for row in [*rows, *again])
    print(f"made {made}; {len(rows) + len(again) - made} could not be read")
    for row in videos_with_a_black_still(listed, places, thumb_dir):
        generate_thumbnail(gallery.video_file_of(row, places), MediaType.VIDEO, thumb_dir,
                           name=row["prompt_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
