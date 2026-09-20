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

    active = False

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
    """Control off asks the motion for nothing and does not spend what a hold
    wrote down, so driving afterwards puts back what park stilled.  Settling the
    device home is the drivers' own hand-back, on the way out."""
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
    control.changed.connect(lambda: heard.append(control.isChecked()))

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


def test_a_saved_state_is_put_back_and_an_old_on_off_switch_still_reads():
    for saved, state in ((OSR2_RETRACTED, OSR2_RETRACTED), (True, OSR2_DRIVING),
                         (False, OSR2_CONTROL_OFF), (None, OSR2_CONTROL_OFF),
                         ("sideways", OSR2_CONTROL_OFF)):
        control = _control()

        control.restore(saved)

        assert control.state() == state, saved


class FakeScript:
    def __init__(self, active=False):
        self.active = active


def test_it_says_which_driver_has_the_device():
    motion = FakeMotion()
    motion.active = False
    control = Osr2Control(motion, script=FakeScript())

    assert control.source() is None

    motion.active = True
    assert control.source() == "robot_hand"

    control.script.active = True
    assert control.source() == "funscript"


def test_the_hold_is_in_place_before_the_switch_says_so():
    """Whatever reconciles on the switch has to see the hold already taken, or
    it re-aims the device at a funscript the hold is meant to have stood down."""
    motion = FakeMotion()
    control = _control(motion)
    seen = []
    control.changed.connect(lambda: seen.append(motion.held_at))

    control.set_state(OSR2_PARKED)

    assert seen == [PARK_CENTER]


def test_a_move_that_leaves_the_switch_alone_still_says_so():
    """Driving to parked flips nothing -- and if that reached nobody, the press
    would change the picture and leave the device where it was."""
    control = _control()
    control.set_state(OSR2_DRIVING)
    heard = []
    control.changed.connect(lambda: heard.append(control.state()))

    control.set_state(OSR2_PARKED)

    assert heard == [OSR2_PARKED]


def test_a_switch_handed_no_drivers_lets_go_and_cannot_be_turned_on():
    control = _control()
    control.set_state(OSR2_DRIVING)
    heard = []
    control.changed.connect(lambda: heard.append(control.state()))

    control.drive_with(None, None)
    control.setChecked(True)

    assert heard == [OSR2_CONTROL_OFF]
    assert not control.isEnabled() and control.state() == OSR2_CONTROL_OFF


def test_a_switch_handed_its_drivers_back_drives_them_again():
    motion, script = FakeMotion(), FakeScript(active=True)
    control = _control(motion)
    control.drive_with(None, None)

    control.drive_with(motion, script)
    control.set_state(OSR2_DRIVING)

    assert control.state() == OSR2_DRIVING and control.source() == "funscript"


def test_a_session_taking_the_device_puts_the_switch_off_and_keeps_it_there():
    control = _control()
    control.setChecked(True)
    changes = []
    control.changed.connect(lambda: changes.append(control.state()))

    control.the_session_has_it(True)

    assert changes == [OSR2_CONTROL_OFF]
    assert not control.isEnabled()
    control.setChecked(True)
    control.set_state(OSR2_DRIVING)
    assert control.state() == OSR2_CONTROL_OFF


def test_a_session_letting_the_device_go_hands_the_switch_back():
    control = _control()
    control.the_session_has_it(True)
    changes = []
    control.changed.connect(lambda: changes.append(control.state()))

    control.the_session_has_it(False)

    assert changes == [OSR2_CONTROL_OFF]
    assert control.isEnabled()
    control.setChecked(True)
    assert control.state() == OSR2_DRIVING


def test_the_same_claim_said_again_changes_nothing():
    control = _control()
    control.the_session_has_it(True)
    changes = []
    control.changed.connect(lambda: changes.append(control.state()))

    control.the_session_has_it(True)

    assert changes == []


def test_every_move_of_the_control_group_is_recorded(caplog):
    # The drivers log their own engage and release, which left the two holds
    # and the off silent -- so the log could not say whether the device was
    # under this app at all.
    control = _control()

    with caplog.at_level("INFO", logger="origenerator.gui.osr2_control"):
        caplog.clear()
        for state in (OSR2_DRIVING, OSR2_PARKED, OSR2_RETRACTED, OSR2_CONTROL_OFF):
            control.set_state(state)

    assert [record.message for record in caplog.records] == [
        f"OSR2 control: {state}" for state in
        (OSR2_DRIVING, OSR2_PARKED, OSR2_RETRACTED, OSR2_CONTROL_OFF)]


def test_the_device_changing_hands_with_a_session_is_recorded(caplog):
    control = _control()
    control.setChecked(True)

    with caplog.at_level("INFO", logger="origenerator.gui.osr2_control"):
        caplog.clear()
        control.the_session_has_it(True)
        control.the_session_has_it(False)

    assert [record.message for record in caplog.records] == [
        "The OSR2 is Fun Time's", f"OSR2 control: {OSR2_CONTROL_OFF}",
        "The OSR2 is ours again"]  # the release moved no state, so it says none
