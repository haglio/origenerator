"""Play a looping WebP preview inside a QLabel via ``QMovie``.

Video thumbnails across the gallery — the grid tiles, the Recents shelf, the
"Animated in" strip and a combine slot — all show a short looping WebP rather
than a static frame. ``QMovie`` plays them cheaply, with no video player per
tile. The one shared subtlety is scaling: ``QMovie``'s own scaling stretches a
non-square clip to fill the target, so we scale the native frame size into the
target with ``KeepAspectRatio`` instead.

Every one of them is built here, which is why every one of them is put under
the session's freeze here too (:mod:`origenerator.gui.omnipause`): wiring each
widget to it separately is how all but the grid tiles were missed once, and a
strip nobody remembered kept playing through a stopped room.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImageReader, QMovie

from origenerator.gui import omnipause


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
    the freeze had just held.
    """
    movie = QMovie(str(path))
    movie.setParent(parent)
    target = fit_size(path, size)
    if target is not None:
        movie.setScaledSize(target)
    movie.start()
    omnipause.holds(movie)  # stopped at once if the room already is
    return movie

