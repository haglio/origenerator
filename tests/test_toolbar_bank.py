"""The button bank, written from one state and read with no gallery around it.

Every button's enabled state, tooltip and visibility used to be recomputed by a
method of its own, and the only way to ask how the bank stood was to build the
app's central widget and read sixteen widgets off it. The state is a plain record
now, so a test writes one by hand.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest

from origenerator.gui.toolbar_bank import (
    AUTO_ELSEWHERE_TIP,
    BankActs,
    BankState,
    Button,
    ToolbarBank,
)


def _acts(**overrides) -> BankActs:
    """Handlers that record rather than act, so a press is observable."""
    fields = {name: (lambda *a: None) for name in BankActs._fields}
    fields.update(overrides)
    return BankActs(**fields)


def _state(**overrides) -> BankState:
    """A bank standing wholly available, with the parts a test cares about
    overridden."""
    fields = {name: Button(tip=name) for name in BankState._fields
              if name != "auto_tip"}
    fields["auto_tip"] = ""
    fields.update(overrides)
    return BankState(**fields)


@pytest.fixture
def bank(qtbot):
    def build(acts=None, *, hosted=False, device=True):
        made = ToolbarBank(acts or _acts(), hosted=hosted, device=device)
        qtbot.addWidget(made)
        return made
    return build


def test_the_room_s_own_appliances_are_absent_when_a_session_owns_them(bank):
    # Hosted, the session's main player owns the room's sound and the session
    # owns the mic, so a second switch for either would be a switch over
    # something this window does not hold.
    hosted = bank(hosted=True, device=False)

    assert hosted.audio is None and hosted.mic is None and hosted.drive is None
    assert bank().audio is not None


def test_the_device_switch_is_absent_where_the_app_may_not_touch_it(bank):
    assert bank(device=False).drive is None


def test_the_bank_opens_with_its_optional_buttons_away(bank):
    # A loop runs until it is stopped, so Auto is never hidden; the slideshow and
    # the grouping are offered only where they mean something.
    made = bank()

    assert made.slideshow.isHidden() and made.group.isHidden()
    assert not made.auto.isHidden()


def test_one_state_writes_every_button(bank):
    made = bank()

    made.apply(_state(
        back=Button(enabled=False, tip="Back"),
        undo=Button(tip="Undo: delete of 2 items"),
        delete=Button(enabled=False, tip="Nothing to delete"),
        slideshow=Button(visible=True, tip="Play Latest as a slideshow"),
    ))

    assert made.back.isEnabled() is False
    assert made.undo.toolTip() == "Undo: delete of 2 items"
    assert made.delete.isEnabled() is False and made.delete.toolTip() == "Nothing to delete"
    assert made.slideshow.toolTip() == "Play Latest as a slideshow"


def test_a_switch_put_where_the_app_already_is_does_not_re_run_the_press(bank):
    # Blocked around the write, not around the press: a bank re-aimed while a
    # loop is running must not toggle the loop off.
    pressed = []
    made = bank(_acts(toggle_auto=pressed.append))

    made.apply(_state(auto=Button(checked=True, tip="running here")))

    assert made.auto.isChecked() is True
    assert pressed == []


def test_a_state_that_says_nothing_about_a_switch_leaves_it_as_the_user_set_it(bank):
    made = bank()
    made.auto.setChecked(True)

    made.apply(_state())  # auto's `checked` is None

    assert made.auto.isChecked() is True


def test_the_loop_running_elsewhere_shows_the_clickable_tip_and_no_tooltip(bank):
    # Only one of the two ever appears: naming the folder is no use when a name
    # is a short code, so the tip offers to go there instead.
    made = bank()

    made.apply(_state(auto=Button(tip=""), auto_tip=AUTO_ELSEWHERE_TIP))

    assert made.auto.toolTip() == ""
    assert "Go to it" in made.auto_tip._html


def test_the_tip_s_link_leads_wherever_the_loop_is_now(bank):
    followed = []
    made = bank(_acts(go_to_looping_folder=followed.append))

    made.auto_tip.link_activated.emit("auto")

    assert followed == ["auto"]


def test_a_group_with_nothing_showing_wears_no_gap(bank):
    # A bank whose optional buttons are away must never wear a stray or doubled
    # gap, and must never start indented.
    made = bank()

    made.apply(_state(group=Button(visible=False), slideshow=Button(visible=False)))

    gaps = [gap.isVisible() for gap, buttons in made._groups]
    assert gaps[0] is False            # the leading group is never indented
    assert gaps[2] is False            # the grouping is away, so its space is too


def test_the_first_group_that_shows_is_the_one_left_unindented(bank):
    made = bank()
    made.show()

    made.apply(_state(back=Button(visible=False), forward=Button(visible=False)))

    gaps = [gap.isVisible() for gap, buttons in made._groups]
    assert gaps[0] is False and gaps[1] is False  # nothing before the second group
    assert gaps[3] is True                        # a space in front of the trio


def test_every_button_presses_its_own_handler(bank):
    pressed = []
    made = bank(_acts(
        go_back=lambda: pressed.append("back"),
        undo=lambda: pressed.append("undo"),
        star=lambda: pressed.append("star"),
        delete=lambda: pressed.append("delete"),
    ))

    made.back.click()
    made.undo.click()
    made.star.click()
    made.delete.click()

    assert pressed == ["back", "undo", "star", "delete"]


def test_a_switch_hands_its_handler_the_state_it_landed_in(bank):
    heard = []
    made = bank(_acts(toggle_drive=heard.append))

    made.drive.setChecked(True)
    made.drive.setChecked(False)

    assert heard == [True, False]
