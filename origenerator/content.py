from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from app_support import haglio_settings
from app_support import overlay as _overlay

from origenerator.branch_session import THIS_CHECKOUT, production_checkout
from origenerator.media import ItemType

PROJECT_DIR = THIS_CHECKOUT
_OVERLAY_NAME = "content.local.json"


def local_overlay(checkout: Path, production: Path) -> Path:
    own = checkout / _OVERLAY_NAME
    return own if own.exists() else production / _OVERLAY_NAME


LOCAL_CONTENT = local_overlay(PROJECT_DIR, production_checkout())
EXAMPLE_CONTENT = PROJECT_DIR / "content.example.json"


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_which_answers = cache(_overlay.overlay_path)


def overlay_path(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> Path:
    return _which_answers(LOCAL_CONTENT if local_path is None else local_path,
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



def missing_overlay_keys(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> tuple[str, ...]:
    missing = _overlay.missing_keys(LOCAL_CONTENT if local_path is None else local_path,
                                    EXAMPLE_CONTENT if example_path is None else example_path)
    present = load_content(local_path, example_path)
    under_an_old_name = {new for new in _RENAMED_KEYS.values() if new in present}
    return tuple(key for key in missing if key not in under_an_old_name)


def genau_flick_words() -> tuple[str, str]:
    words = haglio_settings.value("genau_flick_words")
    return words["one"], words["many"]


def as_sentence(said: str) -> str:
    return said[:1].upper() + said[1:]


def genau_flick_word() -> str:
    return genau_flick_words()[0]


def item_words(item_type: str) -> tuple[str, str]:
    item_type = ItemType(item_type)
    return genau_flick_words() if item_type is ItemType.FLICK else (item_type, f"{item_type}s")


def an_item(item_type: str) -> str:
    one = item_words(item_type)[0]
    return f"{'an' if one[:1] in 'aeiou' else 'a'} {one}"


def non_ai_clip_heading() -> str:
    try:
        return haglio_settings.value("non_ai_clip_heading")
    except haglio_settings.MissingSetting:
        return "Clip"
