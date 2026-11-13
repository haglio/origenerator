from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from app_support import haglio_settings, siblings
from app_support import overlay as _overlay

from origenerator.branch_session import is_branch_session

PROJECT_DIR = Path(__file__).resolve().parent.parent
_OVERLAY_NAME = "content.local.json"


def local_overlay(checkout: Path, production_checkout: Path | None) -> Path:
    own = checkout / _OVERLAY_NAME
    if own.exists() or production_checkout is None:
        return own
    return production_checkout / _OVERLAY_NAME


def _production_checkout() -> Path | None:
    if not is_branch_session():
        return None
    return siblings.project_dir("origenerator", haglio_settings.project_roots())


LOCAL_CONTENT = local_overlay(PROJECT_DIR, _production_checkout())
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
    under_an_old_name = {new for new in _RENAMED_KEYS.values() if new in present}
    return tuple(key for key in missing if key not in under_an_old_name)


def genau_flick_word() -> str:
    return haglio_settings.value("genau_flick_words", "one")
