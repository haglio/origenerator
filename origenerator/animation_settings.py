from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NamedTuple

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


def settings_for(lane: str, action: str, state: str, *, path: Path | None = None
               ) -> dict | None:
    held = _read(path).get(lane, {}).get(action, {}).get(state)
    if not isinstance(held, dict) or not (held.get("workflow") or held.get("params")):
        return None
    return held


class Setting(NamedTuple):
    workflow: str
    params: dict


def remember(lane: str, action: str, state: str, setting: Setting, *,
             path: Path | None = None) -> None:
    held = _read(path)
    held.setdefault(lane, {}).setdefault(action, {})[state] = {
        "workflow": setting.workflow, "params": dict(setting.params)}
    _write(held, path)


def forget(lane: str, action: str, state: str, *, path: Path | None = None) -> None:
    held = _read(path)
    actions = held.get(lane, {}).get(action, {})
    if actions.pop(state, None) is None:
        return
    _write(held, path)


def accepted(*, path: Path | None = None) -> set[tuple[str, str, str]]:
    held = _read(path)
    return {(lane, action, state)
            for lane, actions in held.items() if isinstance(actions, dict)
            for action, states in actions.items() if isinstance(states, dict)
            for state in states}


class AcceptedSettings:
    def remember(self, lane: str, action: str, state: str, *, workflow: str,
                 params: dict) -> None:
        remember(lane, action, state, Setting(workflow, params))

    def accepted_paths(self) -> set[tuple[str, str, str]]:
        return accepted()

    def assigned(self, lane: str, action: str, state: str) -> dict | None:
        return settings_for(lane, action, state)

