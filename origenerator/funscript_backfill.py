"""Give every already-generated video the funscript it would get today.

    python -c "from origenerator.funscript_backfill import main; main()"
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from origenerator import config
from origenerator.db import Database
from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    resynthesize_funscript,
    synthesize_funscript,
)
from origenerator.gallery import media_type_of_row, resolve_preview
from origenerator.generation_state import made_here
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces

logger = logging.getLogger(__name__)


def backfill(db, places: OutputPlaces | None = None, *, hz: float | None = None,
             write=synthesize_funscript, rewrite=resynthesize_funscript,
             resolve=resolve_preview) -> dict:
    places = config.OUTPUT_PLACES if places is None else places
    hz = config.MOTION_DEFAULT_HZ if hz is None else hz
    result = {"written": 0, "rewritten": 0, "skipped": 0, "missing": 0, "failed": 0}
    videos = []
    for row in db.list_generations():
        if media_type_of_row(row) != MediaType.VIDEO or not made_here(row):
            continue
        preview = resolve(row, places)
        if preview is None or preview[1] != MediaType.VIDEO:
            result["missing"] += 1
            continue
        videos.append(preview[0])
    shared_stems = _stems_more_than_one_video_has(videos)
    for path in videos:
        script = _script_of(path, places, shared_stems)
        if script is None:
            written = write(path, hz=hz, places=places)
            result["failed" if written is None else "written"] += 1
        elif rewrite(path, script, hz=hz):
            result["rewritten"] += 1
        else:
            result["skipped"] += 1
    return result


def _stems_more_than_one_video_has(videos) -> set[str]:
    stems = Counter(video.stem for video in set(videos))
    return {stem for stem, count in stems.items() if count > 1}


def _script_of(video: Path, places: OutputPlaces, shared_stems) -> Path | None:
    if video.stem not in shared_stems:
        return funscript_of(video, places=places)
    own = funscript_path_for(video, places=places)
    return own if own.is_file() else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = backfill(Database(config.DB_PATH))
    logger.info(
        "Funscript backfill: %d written, %d rewritten at today's pace, %d left as they are, "
        "%d missing file, %d failed",
        result["written"], result["rewritten"], result["skipped"], result["missing"],
        result["failed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
