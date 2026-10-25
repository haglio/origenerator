"""The drawing that stands for each action on a button: the user's own, named
after the action, kept beside the library; an action without one simply has none."""
from __future__ import annotations

import re
from pathlib import Path

from origenerator.config import LIBRARY_STATE_DIR, STATE_DIR

DRAWINGS_DIR = LIBRARY_STATE_DIR / "picture_states"
OWN_DRAWINGS_DIR = STATE_DIR / "picture_states"


def _slug(state: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", state.lower()).strip("-")


def drawing_path(state: str) -> Path:
    return DRAWINGS_DIR / f"{_slug(state)}.png"


def drawing_for(state: str) -> Path | None:
    own = OWN_DRAWINGS_DIR / f"{_slug(state)}.png"
    if own.is_file():
        return own
    drawn = drawing_path(state)
    return drawn if drawn.is_file() else None
