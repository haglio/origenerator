"""The OSR2 stroke's shared key cluster.

Every surface that can drive the device answers these keys through one helper, so
the muscle memory carries from genau — and so a slip here is a slip on all of
them at once. Nothing exercised it: giving J the speed-up L has, and taking the
cruise toggle off `/`, left 184 tests green across the five files that reach it.
"""

import pytest
from PyQt6.QtCore import Qt

from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND, apply_stroke_key


class _Stroke:
    """Records what a keystroke asked of the driver, in the driver's own words."""

    def __init__(self):
        self.asked = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)  # not a request, just Python looking around
        return lambda *args: self.asked.append((name, *args))


# Each key and the one move it makes. The signs are the point: J and L are the
# same call in opposite directions, as are 7/9 and U/O, and a pair that agreed
# would leave one of the two keys doing nothing a user could see.
_KEYS = [
    (Qt.Key.Key_Space, ("toggle",)),
    (Qt.Key.Key_J, ("adjust_speed", -5)),
    (Qt.Key.Key_L, ("adjust_speed", 5)),
    (Qt.Key.Key_7, ("adjust_amplitude", -10)),
    (Qt.Key.Key_9, ("adjust_amplitude", 10)),
    (Qt.Key.Key_U, ("adjust_center", -5)),
    (Qt.Key.Key_O, ("adjust_center", 5)),
    (Qt.Key.Key_I, ("cycle_shape",)),
    (Qt.Key.Key_Slash, ("toggle_cruise",)),
    (Qt.Key.Key_Backslash, ("quarter_offset",)),
]


@pytest.mark.parametrize("key, asked", _KEYS, ids=lambda v: getattr(v, "name", None))
def test_each_stroke_key_asks_the_driver_for_its_own_move(key, asked):
    stroke = _Stroke()

    handled = apply_stroke_key(stroke, key)

    assert handled is True
    assert stroke.asked == [asked]


def test_a_key_the_cluster_does_not_answer_falls_through_untouched():
    # False is how the caller learns the key is still its own to handle — a
    # surface's own shortcuts live on the other side of this return.
    stroke = _Stroke()

    assert apply_stroke_key(stroke, Qt.Key.Key_K) is False
    assert stroke.asked == []


def test_no_driver_means_every_key_falls_through():
    # Inside a Fun Time session the OSR2 is the main player's alone and this app
    # holds no driver at all, so none of these keys may be swallowed here.
    assert apply_stroke_key(None, Qt.Key.Key_Space) is False


def test_space_reaches_the_switch_it_is_given_rather_than_the_strokes_own():
    # Driving is one switch — the gallery's — which picks the funscript or the
    # stroke by what is playing. Space starting a second source alongside a
    # script already streaming is the failure this argument exists to prevent.
    stroke = _Stroke()
    pressed = []

    apply_stroke_key(stroke, Qt.Key.Key_Space, on_drive_toggle=lambda: pressed.append(1))

    assert pressed == [1]
    assert stroke.asked == []


def test_the_legend_names_every_key_the_cluster_answers():
    # The panel's tooltip is the only place these keys are written down, so a
    # legend that drifts from the table above is a cluster nobody can find.
    # Each key beside the word for what it does: "/" and "I" alone appear inside
    # "J/L" and elsewhere, so on their own they would say nothing.
    for written in ("Space drives", "J/L speed", "7/9 travel", "U/O center",
                    "I shape", "/ cruise", "\\ nudge"):
        assert written in STROKE_KEY_LEGEND
