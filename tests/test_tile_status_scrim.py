from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui.tile_status_scrim import TileStatusScrim


@pytest.fixture
def host(qtbot):
    w = QWidget()
    w.resize(200, 200)
    qtbot.addWidget(w)
    return w


def _thumbnail(host):
    label = QLabel(host)
    label.setGeometry(10, 20, 120, 90)
    return label


def test_the_scrim_lies_over_the_thumbnail_it_is_about(host):
    thumbnail = _thumbnail(host)
    scrim = TileStatusScrim(host)

    scrim.cover(thumbnail, "Generating…")

    assert scrim.text() == "Generating…"
    assert scrim.geometry() == thumbnail.geometry()
    assert not thumbnail.isHidden(), (
        "over the thumbnail, never in its place: what is under it is what the user came to look at")


def test_covering_again_follows_a_thumbnail_laid_out_since_the_last_time(host):
    thumbnail = _thumbnail(host)
    scrim = TileStatusScrim(host)
    scrim.cover(thumbnail, "Generating…")

    thumbnail.setGeometry(30, 40, 60, 50)
    scrim.cover(thumbnail, "Generating…")

    assert scrim.geometry() == thumbnail.geometry()


def test_an_inset_holds_it_off_a_border_the_thumbnail_draws_itself(host):
    thumbnail = _thumbnail(host)
    scrim = TileStatusScrim(host)

    scrim.cover(thumbnail, "Generating…", inset=2)

    assert scrim.geometry() == thumbnail.geometry().adjusted(2, 2, -2, -2)


def test_no_message_takes_the_scrim_away(host):
    thumbnail = _thumbnail(host)
    scrim = TileStatusScrim(host)
    scrim.cover(thumbnail, "Enhancing…")

    scrim.cover(thumbnail, None)

    assert scrim.isHidden()


def test_a_scrim_starts_out_of_the_way(host):
    assert TileStatusScrim(host).isHidden()


def test_clicks_fall_through_to_the_tile_underneath(host):
    scrim = TileStatusScrim(host)
    assert scrim.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_the_message_wraps_rather_than_running_off_the_thumbnail(host):
    assert TileStatusScrim(host).wordWrap()
