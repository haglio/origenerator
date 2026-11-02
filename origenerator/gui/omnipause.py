from __future__ import annotations

import weakref

from PyQt6.QtGui import QMovie


class _TheRoom:
    frozen = False


# Weak: PyQt keeps a parented wrapper alive as long as its parent, so an entry lives as long as the widget it stands for.
_held: weakref.WeakSet = weakref.WeakSet()


def frozen() -> bool:
    return _TheRoom.frozen


def holds(thing) -> None:
    """A QMovie is Qt's and answers setPaused; ours answer set_frozen."""
    _held.add(thing)
    _tell(thing, _TheRoom.frozen)


def freeze(on: bool) -> None:
    _TheRoom.frozen = on
    for thing in list(_held):
        try:
            _tell(thing, on)
        except RuntimeError:
            _held.discard(thing)


def _tell(thing, on: bool) -> None:
    if isinstance(thing, QMovie):
        thing.setPaused(on)
    else:
        thing.set_frozen(on)
