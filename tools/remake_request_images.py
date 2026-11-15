from __future__ import annotations

import argparse
import gc
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import gallery
from origenerator.config import DB_PATH
from origenerator.db import Database
from origenerator.gallery.source_image import source_image_of
from origenerator.media import MediaType
from origenerator.request_seed_remake import wrong_seed_request_images


def _read(copy: Path) -> tuple[list[dict], list[dict]]:
    db = Database(copy)
    rows = db.list_generations()
    return rows, [remake.item for remake in wrong_seed_request_images(rows, db.list_requests())]


def main(argv=None, *, db_path: Path = DB_PATH) -> int:
    argparse.ArgumentParser(
        description="Count the Request images that took the wrong seed, which production "
                    "Origenerator makes again by itself at launch").parse_args(argv)
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / db_path.name
        with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as source, \
                closing(sqlite3.connect(copy)) as into:
            source.backup(into)
        rows, wrong = _read(copy)
        gc.collect()
    ids = {item["prompt_id"] for item in wrong}
    images = [row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE]
    videos = [row for row in rows if gallery.media_type_of_row(row) == MediaType.VIDEO
              and (source_image_of(row, images) or {}).get("prompt_id") in ids]
    enhancements = [row for row in rows if row.get("enhance_of") in ids]
    print(f"{len(wrong)} Request image(s) took the wrong seed, "
          f"{sum(1 for item in wrong if item.get('starred'))} of them starred")
    print(f"{len(videos)} video(s) were animated from them and "
          f"{len(enhancements)} enhancement(s) made of them")
    print("production Origenerator makes them again by itself at its next launch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
