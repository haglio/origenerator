from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from app_support.logging_utils import configure_logging, install_exception_logging

from origenerator import config
from origenerator.db import Database
from origenerator.outside_videos import Places, places_here, scan_in_turn

logger = logging.getLogger(__name__)


def _log_where_the_app_does() -> None:
    configure_logging("", config.STATE_DIR / "origenerator.log")
    install_exception_logging(logger)


def main(db_path: Path | None = None, *, places: Callable[[], Places | None] = places_here,
         start_logging: Callable[[], None] = _log_where_the_app_does) -> int:
    start_logging()
    where = places()
    library = Database(config.DB_PATH if db_path is None else db_path)
    brought_in = scan_in_turn(library, where) if where is not None else 0
    if brought_in:
        logger.info("Brought in %d video(s) other sources made", brought_in)
    print(json.dumps({"brought_in": brought_in}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
