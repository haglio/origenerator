from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from app_support import haglio_settings
from app_support import overlay as _overlay

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONTENT = PROJECT_DIR / "content.local.json"
EXAMPLE_CONTENT = PROJECT_DIR / "content.example.json"


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def overlay_path(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> Path:
    return _overlay.overlay_path(LOCAL_CONTENT if local_path is None else local_path,
                                 EXAMPLE_CONTENT if example_path is None else example_path)


_RENAMED_KEYS = {"combine_recipes": "pinned_kino_settings",
                 "genau_recipes": "pinned_genau_settings"}


def _current(content: dict[str, Any]) -> dict[str, Any]:
    for old, new in _RENAMED_KEYS.items():
        if old in content and new not in content:
            content[new] = content.pop(old)
    return content


def load_content(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> dict[str, Any]:
    return _current(json.loads(_text(overlay_path(local_path, example_path))))


load_content.cache_clear = _text.cache_clear


def missing_overlay_keys(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> tuple[str, ...]:
    missing = _overlay.missing_keys(LOCAL_CONTENT if local_path is None else local_path,
                                    EXAMPLE_CONTENT if example_path is None else example_path)
    present = load_content(local_path, example_path)
    return tuple(key for key in missing if _RENAMED_KEYS.get(key, key) not in present)


def genau_flick_word() -> str:
    return haglio_settings.value("genau_flick_words", "one")
