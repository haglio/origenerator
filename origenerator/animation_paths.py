"""Which animations an image can be asked for, given what it already shows: a
lane, an act and a starting state, from the content overlay."""
from __future__ import annotations

from origenerator.act_settings import GENAU, VIDEO
from origenerator.content import load_content

LANES = (VIDEO, GENAU)


def _table(content: dict | None) -> dict:
    """The overlay's table as ``{lane: {act: (state, ...)}}``, malformed lines out."""
    if content is None:
        content = load_content()
    listed = content.get("animation_paths")
    if not isinstance(listed, dict):
        return {}
    table: dict[str, dict[str, tuple[str, ...]]] = {}
    for lane in LANES:
        acts = listed.get(lane)
        if not isinstance(acts, dict):
            continue
        for act, states in acts.items():
            if not isinstance(act, str) or not act.strip() or not isinstance(states, list):
                continue
            named = tuple(dict.fromkeys(
                state.strip() for state in states
                if isinstance(state, str) and state.strip()))
            if named:
                table.setdefault(lane, {})[act.strip()] = named
    return table


def acts(lane: str = VIDEO, *, content: dict | None = None) -> tuple[str, ...]:
    return tuple(_table(content).get(lane, {}))


def acts_for(state: str, lane: str = VIDEO, *, content: dict | None = None
             ) -> tuple[str, ...]:
    """The acts ``lane`` can animate an image already in ``state`` as, in the
    table's own order, and empty for a state the table says nothing about."""
    return tuple(act for act, states in _table(content).get(lane, {}).items()
                 if state in states)


def allows(lane: str, act: str, state: str, *, content: dict | None = None) -> bool:
    return state in _table(content).get(lane, {}).get(act, ())


def every_path(*, content: dict | None = None) -> tuple[tuple[str, str, str], ...]:
    """Every ``(lane, act, state)`` the table holds, lane by lane in its order."""
    table = _table(content)
    return tuple((lane, act, state)
                 for lane in LANES
                 for act, states in table.get(lane, {}).items()
                 for state in states)


