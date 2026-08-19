"""Play a looping WebP preview inside a QLabel via ``QMovie``.

Video thumbnails across the gallery — the grid tiles, the Recents shelf, and the
"Animated in" strip — all show a short looping WebP rather than a static frame.
``QMovie`` plays them cheaply, with no video player per tile. The one shared
subtlety is scaling: ``QMovie``'s own scaling stretches a non-square clip to fill
the target, so we scale the native frame size into the target with
``KeepAspectRatio`` instead.
"""

from PyQt6.QtGui import QMovie, QImageReader
from PyQt6.QtCore import QSize, Qt


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
    """A ``QMovie`` for the WebP at ``path``, aspect-fit into ``size``.

    Parented to ``parent`` so the wrapper outlives the caller's local and the
    label's pointer can't dangle before the next paint. Not started — the caller
    sets it on its label and calls ``start()``.
    """
    movie = QMovie(str(path))
    movie.setParent(parent)
    target = fit_size(path, size)
    if target is not None:
        movie.setScaledSize(target)
    return movie
