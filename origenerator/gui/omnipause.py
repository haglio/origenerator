"""The room's freeze: one flag, asked rather than remembered.

A hosting Fun Time session's OmniPause stops the room, and so does a click on a
show standing on its own; a room with looping thumbnails, playing videos, an
audio bed or a moving OSR2 still going in it is not stopped.  Whatever is held
here is told when the room freezes, and is told the current answer the moment
it joins, so a pane built mid-freeze opens frozen because it asked, not because
whoever built it remembered to say so.

What a freeze reaches is registered rather than wired per widget:
:func:`~origenerator.gui.looping_preview.looping_movie` builds every looping
thumbnail in the app, so one call there covers the grid, the shelves, a tab's
history strip and the "Animated in" strip together.
"""

from __future__ import annotations

import weakref

from PyQt6.QtGui import QMovie

# Weak, because everything here is parented to the widget that shows it: PyQt
# keeps a parented wrapper alive as long as its parent, so an entry lives
# exactly as long as the thing it stands for and a rebuilt strip leaves nothing.
_frozen = False
_held: weakref.WeakSet = weakref.WeakSet()


def frozen() -> bool:
    """Whether the room is stopped."""
    return _frozen


def holds(thing) -> None:
    """Put *thing* under the freeze, and tell it where the room stands now.

    A ``QMovie`` is Qt's and answers ``setPaused``; ours answer ``set_frozen``.
    """
    _held.add(thing)
    _tell(thing, _frozen)


def freeze(on: bool) -> None:
    """Stop the room, or let it go again."""
    global _frozen
    _frozen = on
    for thing in list(_held):
        try:
            _tell(thing, on)
        except RuntimeError:
            _held.discard(thing)  # its widget went while we held a wrapper


def _tell(thing, on: bool) -> None:
    if isinstance(thing, QMovie):
        thing.setPaused(on)
    else:
        thing.set_frozen(on)
