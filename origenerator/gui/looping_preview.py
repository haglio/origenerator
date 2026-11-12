from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt
from PySide6.QtGui import QImageReader, QMovie

from origenerator.gui import omnipause
from origenerator.gui.grayscale import play_grayscale


def fit_size(path: str, size: QSize) -> QSize | None:
    native = QImageReader(str(path)).size()
    if not native.isValid() or native.isEmpty():
        return None
    target = native.scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
    return None if target.isEmpty() else target


# Qt's QMovie plays an animated WebP through its image reader, with no video player behind it.
def looping_movie(path: str, size: QSize, parent) -> QMovie:
    return _running(_fitted(path, size, parent))


def play_in(label, path: str, size: QSize) -> QMovie:
    stop_what_plays_in(label)
    movie = _fitted(path, size, label)
    # A QLabel handed a running movie repaints only the rect its frames fill,
    # leaving the previous video showing around one of another shape.
    label.setMovie(movie)
    return _running(movie)


def play_gray_in(label, path: str, size: QSize) -> QMovie:
    stop_what_plays_in(label)
    movie = looping_movie(path, size, label)
    play_grayscale(movie, label)
    return movie


def what_plays_in(label) -> QMovie | None:
    return label.movie() or label.findChild(QMovie, options=Qt.FindChildOption.FindDirectChildrenOnly)


def set_in_sight(label, in_sight: bool) -> None:
    movie = what_plays_in(label)
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
    playing = what_plays_in(label)
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
    omnipause.holds(_Gate(movie))
    return movie

