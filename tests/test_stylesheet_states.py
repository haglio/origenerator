"""A control that is ON sits on a lighter ground than one at rest.

One rule across the family, from shared_ui, so a toggled button reads the same
whichever app it is in -- the apps had each answered it their own way and some
had not answered it at all.
"""

from PyQt6.QtGui import QColor

from origenerator.gui.stylesheet import build_stylesheet
from shared_ui.colors import BG_BUTTON, BG_BUTTON_ACTIVE, BLUE


def _lightness(color: QColor) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def test_a_checked_button_takes_the_familys_on_ground(qtbot):
    sheet = build_stylesheet()

    assert BG_BUTTON_ACTIVE.name() in sheet
    assert "QToolButton:checked" in sheet
    assert "QPushButton:checked" in sheet


def test_the_on_ground_is_lighter_than_the_resting_one(qtbot):
    # Which is the whole content of the rule: a button coming forward when it is
    # engaged. A darker "on" would read as pressed-and-stuck.
    assert _lightness(BG_BUTTON_ACTIVE) > _lightness(BG_BUTTON)


def test_the_derived_size_padlock_keeps_its_own_blue(qtbot):
    # The one exception: unlocked means the size fields are overridable, which
    # says more than "this control is engaged", so it keeps a state color.
    sheet = build_stylesheet()

    assert "QToolButton#dimensionUnlock:checked" in sheet
    assert BLUE.name() in sheet
