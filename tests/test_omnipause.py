from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QMovie

from origenerator.gui import omnipause


class _Pane(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.told: list[bool] = []

    def set_frozen(self, frozen: bool) -> None:
        self.told.append(frozen)


def test_nothing_is_frozen_until_the_room_is():
    assert omnipause.frozen() is False


def test_the_room_freezing_reaches_everything_it_holds():
    pane = _Pane()
    omnipause.holds(pane)
    omnipause.freeze(True)
    assert pane.told[-1] is True
    omnipause.freeze(False)
    assert pane.told[-1] is False


def test_something_built_into_a_frozen_room_opens_frozen():
    omnipause.freeze(True)
    pane = _Pane()
    omnipause.holds(pane)
    assert pane.told == [True]
    assert omnipause.frozen() is True


def test_the_freeze_lets_go_of_what_has_gone(qtbot):
    pane = _Pane()
    omnipause.holds(pane)
    pane.deleteLater()
    pane.setParent(None)
    del pane
    omnipause.freeze(True)


def test_a_looping_picture_held_by_the_room_is_paused_with_it(tmp_path):
    two_frames = tmp_path / "loop.gif"
    first, second = Image.new("RGB", (4, 4), "red"), Image.new("RGB", (4, 4), "blue")
    first.save(two_frames, save_all=True, append_images=[second], duration=50, loop=0)
    movie = QMovie(str(two_frames))
    movie.start()
    omnipause.holds(movie)

    omnipause.freeze(True)
    paused = movie.state()
    omnipause.freeze(False)

    assert paused == QMovie.MovieState.Paused
    assert movie.state() == QMovie.MovieState.Running
