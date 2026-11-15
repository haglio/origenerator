from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from app_support.logging_utils import configure_logging, install_exception_logging

from origenerator import config, non_ai_videos
from origenerator.db import Database
from origenerator.non_ai_videos import NonAiPlaces
from origenerator.outside_videos import Places, places_here, scan_in_turn
from origenerator.own_upscales import mark_own_upscales

logger = logging.getLogger(__name__)


def main(db_path: Path | None = None, *, places: Callable[[], Places | None] = places_here,
         non_ai: Callable[[], NonAiPlaces | None] = non_ai_videos.places_here,
         log_to: Callable[[str, Path], object] = configure_logging) -> int:
    log_to("", config.STATE_DIR / "origenerator.log")
    install_exception_logging(logger)
    where, non_ai_where = places(), non_ai()
    library = Database(config.DB_PATH if db_path is None else db_path)
    mark_own_upscales(library)
    brought_in = scan_in_turn(library, where) if where is not None else 0
    if brought_in:
        logger.info("Brought in %d video(s) other sources made", brought_in)
    if non_ai_where is not None:
        non_ai_brought_in = non_ai_videos.scan_in_turn(library, non_ai_where)
        if non_ai_brought_in:
            logger.info("Brought in %d Non-AI video(s)", non_ai_brought_in)
        brought_in += non_ai_brought_in
    print(json.dumps({"brought_in": brought_in}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
