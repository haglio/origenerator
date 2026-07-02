"""Play a looping WebP preview inside a QLabel via ``QMovie``.

Video thumbnails across the gallery — the grid tiles, the Recents shelf, a
Generate tab's history strip, and the "Animated in" strip — all show a short
looping WebP rather than a static frame. ``QMovie`` plays them cheaply, with no
video player per tile. The one shared subtlety is scaling: ``QMovie``'s own
scaling stretches a non-square clip to fill the target, so we scale the native
frame size into the target with ``KeepAspectRatio`` instead.
"""

from PyQt6.QtGui import QMovie, QImageReader
from PyQt6.QtCore import QSize, Qt


def looping_movie(path: str, size: QSize, parent) -> QMovie:
    """A ``QMovie`` for the WebP at ``path``, aspect-fit into ``size``.

    Parented to ``parent`` so the wrapper outlives the caller's local and the
    label's pointer can't dangle before the next paint. Not started — the caller
    sets it on its label and calls ``start()``.
    """
    movie = QMovie(str(path))
    movie.setParent(parent)
    native = QImageReader(str(path)).size()
    if native.isValid() and not native.isEmpty():
        target = native.scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
        if not target.isEmpty():
            movie.setScaledSize(target)
    return movie
