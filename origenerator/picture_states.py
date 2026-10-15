"""What a picture can be sorted as showing, and how its buttons are arranged,
from the content overlay (``content.example.json`` documents both)."""
from __future__ import annotations

from origenerator.content import load_content


def state_names(content: dict | None = None) -> tuple[str, ...]:
    if content is None:
        content = load_content()
    listed = content.get("picture_states")
    if not isinstance(listed, list):
        return ()
    names = (entry.strip() for entry in listed if isinstance(entry, str))
    return tuple(dict.fromkeys(name for name in names if name))


def state_grid(content: dict | None = None) -> tuple[tuple[str, ...], ...]:
    """The rows of actions the sorting window lays its buttons out in, every
    action in exactly one row; the order the dropdowns offer is a separate key."""
    if content is None:
        content = load_content()
    names = state_names(content)
    arranged = content.get("picture_state_grid")
    rows: list[tuple[str, ...]] = []
    placed: set[str] = set()
    for row in arranged if isinstance(arranged, list) else ():
        if not isinstance(row, list):
            continue
        named = (entry.strip() for entry in row if isinstance(entry, str))
        kept = tuple(dict.fromkeys(name for name in named
                                   if name in names and name not in placed))
        placed.update(kept)
        if kept:
            rows.append(kept)
    left = tuple(name for name in names if name not in placed)
    if left:
        rows.append(left)
    return tuple(rows)
