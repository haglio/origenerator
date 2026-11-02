from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from origenerator.gui.motion_hud import apply_motion_key


class _Motion:
    def __init__(self):
        self.asked = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args: self.asked.append((name, *args))


_KEYS = [
    (Qt.Key.Key_Space, ("toggle",)),
    (Qt.Key.Key_J, ("adjust_speed", -5)),
    (Qt.Key.Key_L, ("adjust_speed", 5)),
    (Qt.Key.Key_7, ("adjust_amplitude", -10)),
    (Qt.Key.Key_9, ("adjust_amplitude", 10)),
    (Qt.Key.Key_U, ("adjust_center", -5)),
    (Qt.Key.Key_O, ("adjust_center", 5)),
    (Qt.Key.Key_I, ("cycle_shape",)),
    (Qt.Key.Key_Semicolon, ("toggle_learned",)),
]


@pytest.mark.parametrize(("key", "asked"), _KEYS, ids=lambda v: getattr(v, "name", None))
def test_each_motion_key_asks_the_driver_for_its_own_move(key, asked):
    motion = _Motion()

    handled = apply_motion_key(motion, key)

    assert handled is True
    assert motion.asked == [asked]


@pytest.mark.parametrize("key", [Qt.Key.Key_K, Qt.Key.Key_Slash],
                         ids=lambda v: getattr(v, "name", None))
def test_a_key_the_cluster_does_not_answer_falls_through_untouched(key):
    motion = _Motion()

    assert apply_motion_key(motion, key) is False
    assert motion.asked == []


def test_no_driver_means_every_key_falls_through():
    assert apply_motion_key(None, Qt.Key.Key_Space) is False


def test_space_reaches_the_switch_it_is_given_rather_than_the_motions_own():
    motion = _Motion()
    pressed = []

    apply_motion_key(motion, Qt.Key.Key_Space, on_drive_toggle=lambda: pressed.append(1))

    assert pressed == [1]
    assert motion.asked == []
