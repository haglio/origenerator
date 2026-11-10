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
    assert _lightness(BG_BUTTON_ACTIVE) > _lightness(BG_BUTTON), (
        "a button comes forward when it is engaged: a darker ground when on would read as pressed and stuck")


def test_a_button_whose_on_state_is_a_choice_goes_blue(qtbot):
    sheet = build_stylesheet()

    assert f'QAbstractButton[{CHOSEN}="true"]:checked' in sheet
    assert BLUE.name() in sheet
