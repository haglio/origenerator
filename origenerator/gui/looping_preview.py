"""Play a looping WebP preview inside a QLabel via ``QMovie``.

Video thumbnails across the gallery — the grid tiles, the Recents shelf, the
"Animated in" strip and a combine slot — all show a short looping WebP rather
than a static frame. ``QMovie`` plays them cheaply, with no video player per
tile. The one shared subtlety is scaling: ``QMovie``'s own scaling stretches a
non-square clip to fill the target, so we scale the native frame size into the
target with ``KeepAspectRatio`` instead.

Every one of them is built here, which is why the app-wide freeze lives here
too: a hosting Fun Time session's OmniPause stops the room, and a room with
looping thumbnails still going in it is not stopped.  Wiring each widget to the
flag separately is how all but the tiles were missed — a strip nobody
remembered kept playing — so the switch is on the one function they all call,
and a preview built while the freeze is on comes up already held.
"""

from __future__ import annotations

import weakref

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImageReader, QMovie

# The freeze, and who is under it.  A weak set because a movie is parented to
# the widget that shows it: PyQt keeps a parented wrapper alive for as long as
# its parent, so an entry lives exactly as long as the preview it stands for
# and a rebuilt strip leaves nothing behind here.
_paused = False
_movies: weakref.WeakSet = weakref.WeakSet()


def fit_size(path: str, size: QSize) -> QSize | None:
    """The clip at ``path`` aspect-fit into ``size``, or ``None`` when its native
    size can't be read (so the caller leaves the movie's own scaling alone).

    Split out so a pane that re-fits its clip as it resizes can ask the same
    question again without rebuilding the movie and restarting the loop.
    """
    native = QImageReader(str(path)).size()
    if not native.isValid() or native.isEmpty():
        return None
    target = native.scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
    return None if target.isEmpty() else target


def looping_movie(path: str, size: QSize, parent) -> QMovie:
    """A running ``QMovie`` for the WebP at ``path``, aspect-fit into ``size``.

    Parented to ``parent`` so the wrapper outlives the caller's local and the
    label's pointer can't dangle before the next paint.  Started here rather
    than by the caller, because a caller's ``start()`` would resume a preview
    this function had just held for a freeze already in force.
    """
    movie = QMovie(str(path))
    movie.setParent(parent)
    target = fit_size(path, size)
    if target is not None:
        movie.setScaledSize(target)
    _movies.add(movie)
    movie.start()
    if _paused:
        movie.setPaused(True)
    return movie


def set_previews_paused(paused: bool) -> None:
    """Hold (or release) every looping preview in the app, and the ones built
    after this — a hosting session's OmniPause over the moving thumbnails."""
    global _paused
    _paused = paused
    for movie in list(_movies):
        try:
            movie.setPaused(paused)
        except RuntimeError:
            _movies.discard(movie)  # its widget went while we held a wrapper

