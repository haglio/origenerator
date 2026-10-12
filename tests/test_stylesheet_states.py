"""A control that is ON sits on a lighter ground than one at rest.

One rule across the family, from shared_ui, so a toggled button reads the same
whichever app it is in -- the apps had each answered it their own way and some
had not answered it at all.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor
from shared_ui.colors import BG_BUTTON, BG_BUTTON_ACTIVE, BLUE

from origenerator.gui.stylesheet import CHOSEN, build_stylesheet


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


def test_a_button_whose_on_state_is_a_choice_goes_blue(qtbot):
    # The one exception, and one rule for every control that takes it: unlocked
    # means the size fields are overridable, Separate means the folder list is
    # kept apart by shape -- each says more than "this control is engaged", so
    # each wears the blue of any other selection. Keyed off the property, so a
    # third such control needs no rule of its own.
    sheet = build_stylesheet()

    assert f'QAbstractButton[{CHOSEN}="true"]:checked' in sheet
    assert BLUE.name() in sheet
