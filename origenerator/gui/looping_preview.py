"""Play a looping WebP preview inside a QLabel via ``QMovie``.

Video thumbnails across the gallery — the grid tiles, the Recents collection, the
"Animated in" strip and a combine slot — all show a short looping WebP rather
than a static frame. ``QMovie`` plays them cheaply, with no video player per
tile.

Every one of them is built here, which is why every one of them is put under
the session's freeze here too (:mod:`origenerator.gui.omnipause`): wiring each
widget to it separately is how all but the grid tiles were missed once, and a
strip nobody remembered kept playing through a stopped room.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QSize, Qt
from PyQt6.QtGui import QImageReader, QMovie

from origenerator.gui import omnipause


def fit_size(path: str, size: QSize) -> QSize | None:
    """The video at ``path`` aspect-fit into ``size``, or ``None`` when its native
    size can't be read (so the caller leaves the movie's own scaling alone).

    Split out so a pane that re-fits its video as it resizes can ask the same
    question again without rebuilding the movie and restarting the loop.
    """
    native = QImageReader(str(path)).size()
    if not native.isValid() or native.isEmpty():
        return None
    target = native.scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
    return None if target.isEmpty() else target


def looping_movie(path: str, size: QSize, parent) -> QMovie:
    """A running video for a caller that paints the frames itself rather than
    handing it to a label (:mod:`origenerator.gui.grayscale`); everything else
    takes :func:`play_in`.

    Parented so the wrapper outlives the caller's local, and started here
    because a caller's ``start()`` would resume a preview the freeze had held.
    """
    return _running(_fitted(path, size, parent))


def play_in(label, path: str, size: QSize) -> QMovie:
    """Give ``label`` the looping WebP at ``path`` in place of whatever it was
    playing, aspect-fit into ``size``.

    The order is the point: a label handed a movie that is already running draws
    only the rect its frames fill, so a video of another shape left the one before
    it showing around the edges, one per video ever shown.
    """
    stop_what_plays_in(label)
    movie = _fitted(path, size, label)
    label.setMovie(movie)
    return _running(movie)


def set_in_sight(label, in_sight: bool) -> None:
    movie = label.movie()
    gate = movie.findChild(_Gate) if movie is not None else None
    if gate is not None:
        gate.set_in_sight(in_sight)


class _Gate(QObject):
    def __init__(self, movie: QMovie):
        super().__init__(movie)
        self._movie, self._frozen, self._in_sight = movie, False, True

    def set_frozen(self, frozen: bool) -> None:
        self._frozen = frozen
        self._movie.setPaused(frozen or not self._in_sight)

    def set_in_sight(self, in_sight: bool) -> None:
        self._in_sight = in_sight
        self._movie.setPaused(self._frozen or not in_sight)


def stop_what_plays_in(label) -> None:
    playing = label.movie()
    label.setMovie(None)
    if playing is None:
        return
    playing.stop()
    playing.setParent(None)
    playing.deleteLater()


def _fitted(path: str, size: QSize, parent) -> QMovie:
    movie = QMovie(str(path))
    movie.setParent(parent)
    target = fit_size(path, size)
    if target is not None:
        movie.setScaledSize(target)
    return movie


def _running(movie: QMovie) -> QMovie:
    movie.start()
    omnipause.holds(_Gate(movie))  # stopped at once if the room already is
    return movie

