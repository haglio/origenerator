from __future__ import annotations

import json
from pathlib import Path

from app_support.file_channel import read_whole, write_whole

from origenerator.config import LIBRARY_STATE_DIR

GALLERY_NAMES_FILE = "gallery_names.json"
GALLERY_NAMES_PATH = LIBRARY_STATE_DIR / GALLERY_NAMES_FILE


def publish(names_by_file: dict[str, str], *, path: Path = GALLERY_NAMES_PATH) -> None:
    text = json.dumps(names_by_file, sort_keys=True)
    if _published(path) != text:
        write_whole(path, text)


def _published(path: Path) -> str | None:
    try:
        return read_whole(path)
    except FileNotFoundError:
        return None
