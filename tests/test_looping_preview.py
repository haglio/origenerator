from __future__ import annotations

import pytest
from PIL import Image
from PySide6.QtCore import QSize
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QLabel

from origenerator.gui import looping_preview, omnipause
from origenerator.gui.looping_preview import (
    fit_size,
    looping_movie,
    play_gray_in,
    play_in,
    set_in_sight,
    stagger_ms,
)
from origenerator.thumbnail import FRAME_MS
from tests.children import HANG_AFTER_S


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



def _changing_loop(path):
    frames = [Image.new("RGB", (40, 30), color) for color in ("gray", "white")]
    frames[0].save(path, save_all=True, append_images=frames[1:], loop=0, duration=80)
    return str(path)


@pytest.fixture
def staggered(monkeypatch):
    monkeypatch.setattr(looping_preview, "STAGGER_SPAN_MS", 5 * FRAME_MS)


def test_thumbnails_start_at_moments_of_their_own_within_one_slow_frame(staggered, tmp_path):
    waits = {stagger_ms(str(tmp_path / f"{name}.webp")) for name in "abcdefgh"}

    assert len(waits) > 4
    assert all(0 <= wait < 5 * FRAME_MS for wait in waits)


def test_a_thumbnail_shows_its_first_frame_until_its_moment_then_runs(staggered, label, tmp_path,
                                                                      qtbot):
    path = _changing_loop(tmp_path / "one.webp")
    assert stagger_ms(path) > 0

    movie = play_in(label, path, QSize(40, 30))

    assert (movie.state(), movie.currentFrameNumber()) == (QMovie.MovieState.NotRunning, 0)
    qtbot.waitUntil(lambda: movie.state() == QMovie.MovieState.Running, timeout=HANG_AFTER_S * 1000)


def test_a_thumbnail_whose_moment_comes_while_the_room_is_stopped_is_held_still(
        staggered, label, tmp_path, qtbot):
    movie = play_in(label, _changing_loop(tmp_path / "one.webp"), QSize(40, 30))

    omnipause.freeze(True)

    qtbot.waitUntil(lambda: movie.state() == QMovie.MovieState.Paused, timeout=HANG_AFTER_S * 1000)
