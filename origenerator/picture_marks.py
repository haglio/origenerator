"""The drawing that stands for each action on a button: the user's own, named
after the action, kept beside the library; an action without one simply has none."""
from __future__ import annotations

import re
from pathlib import Path

from origenerator.config import LIBRARY_STATE_DIR

MARKS_DIR = LIBRARY_STATE_DIR / "picture_states"


def _slug(state: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", state.lower()).strip("-")


def mark_path(state: str) -> Path:
    return MARKS_DIR / f"{_slug(state)}.png"


def mark_for(state: str) -> Path | None:
    drawn = mark_path(state)
    return drawn if drawn.is_file() else None
