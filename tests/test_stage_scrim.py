import pytest

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt

from origenerator.gui.stage_scrim import StageScrim


@pytest.fixture
def host(qtbot):
    w = QWidget()
    w.resize(200, 200)
    qtbot.addWidget(w)
    return w


def _picture(host):
    label = QLabel(host)
    label.setGeometry(10, 20, 120, 90)
    return label


def test_the_scrim_lies_over_the_picture_it_is_about(host):
    picture = _picture(host)
    scrim = StageScrim(host)

    scrim.cover(picture, "Generating…")

    assert scrim.text() == "Generating…"
    assert scrim.geometry() == picture.geometry()


def test_an_inset_holds_it_off_a_border_the_picture_draws_itself(host):
    # An in-flight card's blue "being made" edge says something; the scrim has no
    # business painting over it.
    picture = _picture(host)
    scrim = StageScrim(host)

    scrim.cover(picture, "Generating…", inset=2)

    assert scrim.geometry() == picture.geometry().adjusted(2, 2, -2, -2)


def test_no_message_takes_the_scrim_away(host):
    picture = _picture(host)
    scrim = StageScrim(host)
    scrim.cover(picture, "Enhancing…")

    scrim.cover(picture, None)

    assert scrim.isHidden()


def test_a_scrim_starts_out_of_the_way(host):
    assert StageScrim(host).isHidden()


def test_clicks_fall_through_to_the_tile_underneath(host):
    # It is a caption over the picture, not a lid on it: the tile still selects,
    # opens and drags with the scrim up.
    scrim = StageScrim(host)
    assert scrim.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_the_message_wraps_rather_than_running_off_the_picture(host):
    # "Waiting behind 2 jobs from another app" is a sentence, not a word.
    assert StageScrim(host).wordWrap()
