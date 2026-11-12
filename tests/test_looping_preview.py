from __future__ import annotations

import pytest
from PIL import Image
from PySide6.QtCore import QSize
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QLabel

from origenerator.gui import omnipause
from origenerator.gui.looping_preview import (
    fit_size,
    looping_movie,
    play_gray_in,
    play_in,
    set_in_sight,
)


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


def test_a_gray_video_is_turned_gray_at_the_size_it_is_shown(label, tmp_path):
    play_gray_in(label, _loop(tmp_path / "one.webp"), QSize(20, 20))

    assert label.pixmap().size() == QSize(20, 15), (
        "each frame is turned gray on its way to the label, a cost that stays small next to "
        "decoding it only because the frame is already at the size it is shown")


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


def test_a_clip_started_for_a_caller_who_paints_it_is_held_still_while_the_room_is_stopped(label, tmp_path):
    omnipause.freeze(True)
    try:
        movie = looping_movie(_loop(tmp_path / "one.webp"), QSize(40, 30), label)
        held = movie.state()
    finally:
        omnipause.freeze(False)

    assert held == QMovie.MovieState.Paused


def test_a_clip_started_while_the_room_is_stopped_is_held_still(label, tmp_path):
    omnipause.freeze(True)
    try:
        movie = play_in(label, _loop(tmp_path / "one.webp"), QSize(40, 30))
        held = movie.state()
    finally:
        omnipause.freeze(False)

    assert held == QMovie.MovieState.Paused


def test_a_clip_for_a_caller_who_paints_it_is_parented_to_the_one_it_is_given(label, tmp_path):
    movie = looping_movie(_loop(tmp_path / "one.webp"), QSize(40, 30), label)

    assert movie.parent() is label


def test_a_clip_whose_size_cannot_be_read_is_left_at_its_own_scale(tmp_path):
    assert fit_size(str(tmp_path / "missing.webp"), QSize(40, 30)) is None

