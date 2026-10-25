"""The settings each animation runs, once accepted: one set per lane, act and
starting state, in a file beside the library that reads as empty if it will not
parse."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from origenerator.config import LIBRARY_STATE_DIR

logger = logging.getLogger(__name__)

SETTINGS_PATH = LIBRARY_STATE_DIR / "animation_recipes.json"


def _read(path: Path | None = None) -> dict:
    path = path or SETTINGS_PATH
    if not path.is_file():
        return {}
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("animation settings unreadable (%s): starting empty", e)
        return {}
    return held if isinstance(held, dict) else {}


def _write(held: dict, path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    beside = path.with_suffix(".partial.json")
    beside.write_text(json.dumps(held, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    beside.replace(path)


def settings_for(lane: str, act: str, state: str, *, path: Path | None = None
               ) -> dict | None:
    """One animation's accepted settings, shaped like the overlay's pinned settings."""
    held = _read(path).get(lane, {}).get(act, {}).get(state)
    if not isinstance(held, dict) or not (held.get("workflow") or held.get("params")):
        return None
    return held


def remember(lane: str, act: str, state: str, *, workflow: str, params: dict,
             path: Path | None = None) -> None:
    held = _read(path)
    held.setdefault(lane, {}).setdefault(act, {})[state] = {
        "workflow": workflow, "params": dict(params)}
    _write(held, path)


def forget(lane: str, act: str, state: str, *, path: Path | None = None) -> None:
    held = _read(path)
    acts = held.get(lane, {}).get(act, {})
    if acts.pop(state, None) is None:
        return
    _write(held, path)


def accepted(*, path: Path | None = None) -> set[tuple[str, str, str]]:
    held = _read(path)
    return {(lane, act, state)
            for lane, acts in held.items() if isinstance(acts, dict)
            for act, states in acts.items() if isinstance(states, dict)
            for state in states}


class AcceptedSettings:
    """The store the window writes through, handed in so a test can stand in."""

    def remember(self, lane: str, act: str, state: str, *, workflow: str,
                 params: dict) -> None:
        remember(lane, act, state, workflow=workflow, params=params)

    def accepted_paths(self) -> set[tuple[str, str, str]]:
        return accepted()

    def assigned(self, lane: str, act: str, state: str) -> dict | None:
        return settings_for(lane, act, state)

