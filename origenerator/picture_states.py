"""What a picture can be sorted as showing, and how its buttons are arranged,
from the content overlay (``content.example.json`` documents both)."""
from __future__ import annotations

from typing import NamedTuple

from origenerator.content import load_content


class Tile(NamedTuple):
    state: str
    row: int
    column: int
    columns: int = 1
    rows: int = 1


def state_names(content: dict | None = None) -> tuple[str, ...]:
    if content is None:
        content = load_content()
    listed = content.get("picture_states")
    if not isinstance(listed, list):
        return ()
    names = (entry.strip() for entry in listed if isinstance(entry, str))
    return tuple(dict.fromkeys(name for name in names if name))


def _reach(entry) -> tuple[str, int, int]:
    if isinstance(entry, str):
        return entry.strip(), 1, 1
    if isinstance(entry, list) and entry and isinstance(entry[0], str):
        spans = [n if isinstance(n, int) and n > 0 else 1 for n in entry[1:3]]
        return (entry[0].strip(), *spans, *(1,) * (2 - len(spans)))
    return "", 1, 1


def state_grid(content: dict | None = None) -> tuple[Tile, ...]:
    if content is None:
        content = load_content()
    names = state_names(content)
    arranged = content.get("picture_state_grid")
    tiles: list[Tile] = []
    placed: set[str] = set()
    down = 0
    for row in arranged if isinstance(arranged, list) else ():
        if not isinstance(row, list):
            continue
        across = 0
        for entry in row:
            state, columns, rows = _reach(entry)
            if state in names and state not in placed:
                tiles.append(Tile(state, down, across, columns, rows))
                placed.add(state)
            across += columns
        down += 1
    tiles.extend(Tile(name, down, across)
                 for across, name in enumerate(name for name in names
                                               if name not in placed))
    return tuple(tiles)
