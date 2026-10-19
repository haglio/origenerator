"""The app's one OSR2 switch: on drives the device, off parks it."""
from __future__ import annotations

from funestra.console import OSR2_DRIVING, OSR2_PARKED

from origenerator.gui.osr2_control import Osr2Control


class FakeMotion:
    """The driver reduced to the hold it is being asked for."""

    active = False

    def __init__(self):
        self.held = None
        self.calls = []

    def hold(self, control):
        self.held = control
        self.calls.append(("hold", control))

    def release(self):
        self.held = None
        self.calls.append("release")

    def set_max_intensity(self, level):
        self.calls.append(("max_intensity", level))


def _control(motion=None):
    return Osr2Control(motion if motion is not None else FakeMotion())


def test_a_session_opens_with_the_switch_off():
    assert _control().state() == OSR2_PARKED


def test_each_state_is_asked_for_by_name():
    motion = FakeMotion()
    control = _control(motion)

    for state in (OSR2_DRIVING, OSR2_PARKED):
        control.set_state(state)
        assert control.state() == state, state


def test_on_drives_and_off_parks():
    control = _control()

    control.set_state(OSR2_DRIVING)
    assert (control.isChecked(), control.state()) == (True, OSR2_DRIVING)

    control.set_state(OSR2_PARKED)
    assert (control.isChecked(), control.state()) == (False, OSR2_PARKED)


def test_off_stills_the_motion_at_home_and_on_lets_it_go():
    motion = FakeMotion()
    control = _control(motion)

    control.set_state(OSR2_PARKED)
    control.set_state(OSR2_DRIVING)

    assert motion.calls == [("hold", OSR2_PARKED), "release"]


def test_parking_a_switch_nothing_had_turned_on_holds_the_device_home():
    """Off is parked: the app takes the device and holds it at home, rather
    than leaving it wherever it was."""
    control = _control()

    control.set_state(OSR2_PARKED)

    assert control.engaged() is True
    assert control.state() == OSR2_PARKED


def test_the_park_is_in_place_before_the_switch_says_so():
    """Whatever reconciles on the switch has to see the park already taken, or
    it re-aims the device at a funscript the park is meant to have stood down."""
    motion = FakeMotion()
    control = _control(motion)
    seen = []
    control.changed.connect(lambda: seen.append(motion.held))

    control.set_state(OSR2_PARKED)

    assert seen == [OSR2_PARKED]


def test_driving_to_parked_still_says_so():
    """The app holds the device either way, so nothing engages anew -- and if
    that reached nobody, the press would change the picture and leave the
    device where it was."""
    control = _control()
    control.set_state(OSR2_DRIVING)
    heard = []
    control.changed.connect(lambda: heard.append(control.state()))

    control.set_state(OSR2_PARKED)

    assert heard == [OSR2_PARKED]


def test_the_switch_announces_a_move_and_not_a_re_statement():
    """A switch put where the app already is must not re-run what a click does:
    a resumed session sets it again."""
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
    """Hosted by Fun Time the OSR2 is the session's Main Funestra's for the whole
    session, so nothing here may take it."""
    control = Osr2Control(None)

    control.setChecked(True)

    assert control.isEnabled() is False
    assert control.isChecked() is False
    assert control.state() == OSR2_PARKED


def test_a_saved_state_is_put_back_and_anything_but_driving_comes_back_off():
    for saved, state in ((OSR2_DRIVING, OSR2_DRIVING), (True, OSR2_DRIVING),
                         (OSR2_PARKED, OSR2_PARKED), ("retracted", OSR2_PARKED),
                         ("control_off", OSR2_PARKED), (False, OSR2_PARKED),
                         (None, OSR2_PARKED), ("sideways", OSR2_PARKED)):
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


def test_a_switch_handed_no_drivers_lets_go_and_cannot_be_turned_on():
    control = _control()
    control.set_state(OSR2_DRIVING)
    heard = []
    control.changed.connect(lambda: heard.append(control.state()))

    control.drive_with(None, None)
    control.setChecked(True)

    assert heard == [OSR2_PARKED]
    assert not control.isEnabled() and control.state() == OSR2_PARKED


def test_a_switch_handed_its_drivers_back_drives_them_again():
    motion, script = FakeMotion(), FakeScript(active=True)
    control = _control(motion)
    control.drive_with(None, None)

    control.drive_with(motion, script)
    control.set_state(OSR2_DRIVING)

    assert control.state() == OSR2_DRIVING and control.source() == "funscript"


def test_the_max_intensity_reaches_both_drivers():
    motion, script = FakeMotion(), FakeScript()
    control = _control(motion)
    control.drive_with(motion, script)

    control.set_max_intensity(30)

    assert (control.max_intensity, motion.calls[-1], script.max_intensity) == (30, ("max_intensity", 30), 30)


def test_drivers_handed_over_after_the_max_intensity_was_set_are_held_to_it():
    control = _control()
    control.drive_with(None, None)
    control.set_max_intensity(30)
    motion, script = FakeMotion(), FakeScript()

    control.drive_with(motion, script)

    assert (motion.calls, script.max_intensity) == ([("max_intensity", 30)], 30)


def test_a_session_taking_the_device_puts_the_switch_off_and_keeps_it_there():
    control = _control()
    control.setChecked(True)
    changes = []
    control.changed.connect(lambda: changes.append(control.state()))

    control.the_session_has_it(True)

    assert changes == [OSR2_PARKED]
    assert not control.isEnabled()
    control.setChecked(True)
    control.set_state(OSR2_DRIVING)
    assert control.state() == OSR2_PARKED


def test_a_session_letting_the_device_go_hands_the_switch_back():
    control = _control()
    control.the_session_has_it(True)
    changes = []
    control.changed.connect(lambda: changes.append(control.state()))

    control.the_session_has_it(False)

    assert changes == [OSR2_PARKED]
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
    # The drivers log their own engage and release, which left the park
    # silent -- so the log could not say whether the device was under this app.
    control = _control()

    with caplog.at_level("INFO", logger="origenerator.gui.osr2_control"):
        caplog.clear()
        for state in (OSR2_DRIVING, OSR2_PARKED):
            control.set_state(state)

    assert [record.message for record in caplog.records] == [
        f"OSR2 control: {state}" for state in (OSR2_DRIVING, OSR2_PARKED)]


def test_the_device_changing_hands_with_a_session_is_recorded(caplog):
    control = _control()
    control.setChecked(True)

    with caplog.at_level("INFO", logger="origenerator.gui.osr2_control"):
        caplog.clear()
        control.the_session_has_it(True)
        control.the_session_has_it(False)

    assert [record.message for record in caplog.records] == [
        "The OSR2 is Fun Time's", f"OSR2 control: {OSR2_PARKED}",
        "The OSR2 is ours again"]  # the release moved no state, so it says none
