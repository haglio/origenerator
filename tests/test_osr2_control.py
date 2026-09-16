"""The app's one OSR2 switch, and the four states the console's group sets."""
from __future__ import annotations

from player_core.console import (
    OSR2_CONTROL_OFF,
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
)
from player_core.robot_hand import PARK_CENTER, RETRACT_CENTER

from origenerator.gui.osr2_control import Osr2Control


class FakeMotion:
    """The driver reduced to the hold it is being asked for."""

    def __init__(self):
        self.held_at = None
        self.calls = []

    def hold(self, center):
        self.held_at = center
        self.calls.append(("hold", center))

    def release(self):
        self.held_at = None
        self.calls.append("release")


def _control(motion=None):
    return Osr2Control(motion if motion is not None else FakeMotion())


def test_a_session_opens_with_the_device_let_go():
    assert _control().state() == OSR2_CONTROL_OFF


def test_each_state_is_asked_for_by_name():
    motion = FakeMotion()
    control = _control(motion)

    for state in (OSR2_DRIVING, OSR2_PARKED, OSR2_RETRACTED, OSR2_CONTROL_OFF):
        control.set_state(state)
        assert control.state() == state, state


def test_a_hold_stills_the_motion_at_the_end_it_names():
    motion = FakeMotion()
    control = _control(motion)

    control.set_state(OSR2_PARKED)
    control.set_state(OSR2_RETRACTED)
    control.set_state(OSR2_DRIVING)

    assert motion.calls == [("hold", PARK_CENTER), ("hold", RETRACT_CENTER), "release"]


def test_a_hold_asked_for_with_the_device_let_go_takes_it_back():
    """Pressing park on a console whose off button is lit turns control on and
    then stills the motion -- which is what the one lit button then says."""
    motion = FakeMotion()
    control = _control(motion)
    control.set_state(OSR2_CONTROL_OFF)

    control.set_state(OSR2_PARKED)

    assert control.isChecked() is True
    assert control.state() == OSR2_PARKED


def test_letting_go_leaves_the_hold_where_it_was():
    """Control off sends nothing; it does not move the device or spend what a
    hold wrote down, so driving afterwards puts back what park stilled."""
    motion = FakeMotion()
    control = _control(motion)
    control.set_state(OSR2_PARKED)
    motion.calls.clear()

    control.set_state(OSR2_CONTROL_OFF)

    assert motion.calls == []
    assert control.state() == OSR2_CONTROL_OFF


def test_the_switch_announces_a_move_and_not_a_re_statement():
    """A switch put where the app already is must not re-run what a click does:
    Esc puts the device back on, and a resumed session sets it again."""
    control = _control()
    heard = []
    control.toggled.connect(heard.append)

    control.setChecked(True)
    control.setChecked(True)
    control.setChecked(False)

    assert heard == [True, False]


def test_anything_that_changes_which_button_lights_says_so():
    """The console redraws on this, and a hold moves no switch -- so a group
    following the switch alone would keep the wrong button lit."""
    control = _control()
    heard = []
    control.changed.connect(lambda: heard.append(control.state()))

    control.set_state(OSR2_DRIVING)
    control.set_state(OSR2_PARKED)

    assert heard[0] == OSR2_DRIVING
    assert heard[-1] == OSR2_PARKED


def test_a_session_that_may_not_drive_cannot_be_switched_on():
    """Hosted by Fun Time the OSR2 is the session's main player's for the whole
    session, so nothing here may take it."""
    control = Osr2Control(None)

    control.setChecked(True)

    assert control.isEnabled() is False
    assert control.isChecked() is False
    assert control.state() == OSR2_CONTROL_OFF
