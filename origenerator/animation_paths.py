from __future__ import annotations

from origenerator.action_settings import GENAU, VIDEO
from origenerator.action_vocabulary import vocabulary
from origenerator.animation_names import Animation, named
from origenerator.content import load_content
from origenerator.media import MediaType

LANES = (VIDEO, GENAU)


def _table(content: dict) -> dict:
    block = content.get("video_actions")
    listed = block.get("starts_from") if isinstance(block, dict) else None
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
            named_states = tuple(dict.fromkeys(
                state.strip() for state in states
                if isinstance(state, str) and state.strip()))
            if named_states:
                table.setdefault(lane, {})[action.strip()] = named_states
    return table


def _read(content: dict | None) -> dict:
    return load_content() if content is None else content


def actions(lane: str = VIDEO, *, content: dict | None = None) -> tuple[str, ...]:
    return tuple(_table(_read(content)).get(lane, {}))


def actions_for(state: str, lane: str = VIDEO, *, content: dict | None = None
             ) -> tuple[str, ...]:
    return tuple(action for action, states in _table(_read(content)).get(lane, {}).items()
                 if state in states)


def allows(lane: str, name: str, state: str, *, content: dict | None = None) -> bool:
    content = _read(content)
    action = named(name, vocabulary(MediaType.VIDEO, content)).action
    return state in _table(content).get(lane, {}).get(action, ())


def every_path(*, content: dict | None = None) -> tuple[tuple[str, str, str], ...]:
    content = _read(content)
    table = _table(content)
    boxes = vocabulary(MediaType.VIDEO, content).checkboxes
    return tuple((lane, Animation(action, checked).name, state)
                 for lane in LANES
                 for action, states in table.get(lane, {}).items()
                 for checked in ((), *((box,) for box in boxes))
                 for state in states)
