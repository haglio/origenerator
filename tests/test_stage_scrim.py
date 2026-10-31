from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui.stage_scrim import StageScrim


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
    scrim = StageScrim(host)

    scrim.cover(thumbnail, "Generating…")

    assert scrim.text() == "Generating…"
    assert scrim.geometry() == thumbnail.geometry()


def test_an_inset_holds_it_off_a_border_the_thumbnail_draws_itself(host):
    # An in-flight tile's blue "being made" edge says something; the scrim has no
    # business painting over it.
    thumbnail = _thumbnail(host)
    scrim = StageScrim(host)

    scrim.cover(thumbnail, "Generating…", inset=2)

    assert scrim.geometry() == thumbnail.geometry().adjusted(2, 2, -2, -2)


def test_no_message_takes_the_scrim_away(host):
    thumbnail = _thumbnail(host)
    scrim = StageScrim(host)
    scrim.cover(thumbnail, "Enhancing…")

    scrim.cover(thumbnail, None)

    assert scrim.isHidden()


def test_a_scrim_starts_out_of_the_way(host):
    assert StageScrim(host).isHidden()


def test_clicks_fall_through_to_the_tile_underneath(host):
    # It is a caption over the thumbnail, not a lid on it: the tile still selects,
    # opens and drags with the scrim up.
    scrim = StageScrim(host)
    assert scrim.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_the_message_wraps_rather_than_running_off_the_thumbnail(host):
    # "Waiting on 2 jobs from another app" is a sentence, not a word.
    assert StageScrim(host).wordWrap()
