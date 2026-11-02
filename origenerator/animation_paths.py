from __future__ import annotations

from origenerator.action_settings import GENAU, VIDEO
from origenerator.content import load_content

LANES = (VIDEO, GENAU)


def _table(content: dict | None) -> dict:
    if content is None:
        content = load_content()
    listed = content.get("animation_paths")
    if not isinstance(listed, dict):
        return {}
    table: dict[str, dict[str, tuple[str, ...]]] = {}
    for lane in LANES:
        actions = listed.get(lane)
        if not isinstance(actions, dict):
            continue
        for action, states in actions.items():
            if not isinstance(action, str) or not action.strip() or not isinstance(states, list):
                continue
            named = tuple(dict.fromkeys(
                state.strip() for state in states
                if isinstance(state, str) and state.strip()))
            if named:
                table.setdefault(lane, {})[action.strip()] = named
    return table


def actions(lane: str = VIDEO, *, content: dict | None = None) -> tuple[str, ...]:
    return tuple(_table(content).get(lane, {}))


def actions_for(state: str, lane: str = VIDEO, *, content: dict | None = None
             ) -> tuple[str, ...]:
    return tuple(action for action, states in _table(content).get(lane, {}).items()
                 if state in states)


def allows(lane: str, action: str, state: str, *, content: dict | None = None) -> bool:
    return state in _table(content).get(lane, {}).get(action, ())


def every_path(*, content: dict | None = None) -> tuple[tuple[str, str, str], ...]:
    table = _table(content)
    return tuple((lane, action, state)
                 for lane in LANES
                 for action, states in table.get(lane, {}).items()
                 for state in states)


