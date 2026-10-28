"""Handing a label the looping clip it shows.

Fixture clips are fabricated (see CLAUDE.md): two frames of flat color.
"""
from __future__ import annotations

import pytest
from PIL import Image
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QLabel

from origenerator.gui import omnipause
from origenerator.gui.looping_preview import play_in, set_in_sight


def _loop(path, color="gray"):
    frames = [Image.new("RGB", (40, 30), color) for _ in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], loop=0,
                   duration=80)
    return str(path)


@pytest.fixture
def label(qtbot):
    made = QLabel()
    qtbot.addWidget(made)
    return made


def test_the_label_has_the_clip_before_it_runs(label, tmp_path, monkeypatch):
    """A QLabel handed a movie that is already running leaves its own repaint to
    that movie's first frame, which covers only the rect the frame fills -- so
    the clip before it stayed on screen around the new one."""
    held = []
    monkeypatch.setattr(QMovie, "start",
                        lambda movie: held.append(label.movie() is movie))

    play_in(label, _loop(tmp_path / "one.webp"), QSize(40, 30))

    assert held == [True]


def test_the_clip_before_it_goes_rather_than_stacking_up(label, tmp_path):
    first = play_in(label, _loop(tmp_path / "one.webp"), QSize(40, 30))

    second = play_in(label, _loop(tmp_path / "two.webp", "white"), QSize(40, 30))

    assert label.movie() is second
    assert label.findChildren(QMovie) == [second]
    assert first.state() == QMovie.MovieState.NotRunning


def test_the_clip_is_fit_into_the_space_it_is_given(label, tmp_path):
    movie = play_in(label, _loop(tmp_path / "one.webp"), QSize(20, 20))

    assert movie.scaledSize() == QSize(20, 15)


def test_a_clip_out_of_sight_holds_still_until_it_is_back_in_sight(label, tmp_path):
    movie = play_in(label, _loop(tmp_path / "one.webp"), QSize(40, 30))

    set_in_sight(label, False)
    assert movie.state() == QMovie.MovieState.Paused

    set_in_sight(label, True)
    assert movie.state() == QMovie.MovieState.Running


def test_a_clip_out_of_sight_stays_still_when_the_room_lets_go(label, tmp_path):
    movie = play_in(label, _loop(tmp_path / "one.webp"), QSize(40, 30))
    set_in_sight(label, False)

    omnipause.freeze(True)
    omnipause.freeze(False)

    assert movie.state() == QMovie.MovieState.Paused


def test_a_clip_back_in_sight_stays_still_while_the_room_is_stopped(label, tmp_path):
    movie = play_in(label, _loop(tmp_path / "one.webp"), QSize(40, 30))
    set_in_sight(label, False)
    omnipause.freeze(True)

    set_in_sight(label, True)

    assert movie.state() == QMovie.MovieState.Paused
