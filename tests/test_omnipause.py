"""The one freeze, and that nothing under it keeps its own copy of the flag.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from PyQt6.QtCore import QObject

from origenerator.gui import omnipause


class _Pane(QObject):
    """Something the freeze holds: it is told, and it does not remember."""

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
    """The whole reason the flag used to be remembered in four places: a pane
    built mid-freeze must not start playing. It asks instead."""
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
    omnipause.freeze(True)  # nothing raises for the pane that went
