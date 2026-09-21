"""The hosting session's freeze: one flag, asked rather than remembered.

A Fun Time session stops the room, and a room with looping thumbnails and
playing videos still going in it is not stopped. What made that hard is that
the freeze has to reach things built *after* it was set -- a tab opened
mid-freeze, a pane re-pointed at a video, a strip rebuilt -- so four places
each kept their own copy of the flag under four names (``_paused``,
``_session_paused``, ``_previews_paused``, ``_playback_paused``), each
re-applying it to whatever it built, and each with a docstring explaining the
same lesson.

There is one flag here instead, and nothing under it keeps a copy: whatever is
held is told when the room freezes, and is told the current answer the moment
it joins. So a pane built mid-freeze opens frozen because it asked, not because
whoever built it remembered to say so -- which is how all but the grid tiles
were missed the first time.

What a freeze reaches is registered rather than wired per widget, for the same
reason: :func:`~origenerator.gui.looping_preview.looping_movie` builds every
looping thumbnail in the app, so one call there covers the grid, the shelves, a
tab's history strip and the "Animated in" strip together.
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
