"""The OSR2 motion's shared key cluster.

The motion driver is app-global — the device shouldn't care which window is in
front — so every surface that can drive it (the gallery window, the fullscreen
show) answers the same keys through this helper,
and floats the same drive panel
(:mod:`origenerator.gui.motion_panel`). The keys are genau's own, so the muscle
memory carries: Space starts/stops, J/L speed, 7/9 amplitude, U/O center,
I shape, / cruise control, backslash nudges a quarter cycle.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt

# The key legend, shown as the drive panel's tooltip.
MOTION_KEY_LEGEND = ("Space drives · J/L speed · 7/9 travel · U/O center"
                     r" · I shape · / cruise · \ nudge")


def apply_motion_key(motion, key, *, on_drive_toggle=None) -> bool:
    """Route one of genau's motion keys to ``motion``; ``False`` for any other
    key (or with no driver wired), so the caller falls through to its own
    handling.

    ``on_drive_toggle`` takes Space instead of the motion's own switch. Driving
    the OSR2 is one switch now — the gallery's — which picks the funscript or
    the motion by what is playing, so Space has to reach *that* rather than
    start a second source alongside a script already streaming.
    """
    if motion is None:
        return False
    if key == Qt.Key.Key_Space:
        (on_drive_toggle or motion.toggle)()
    elif key == Qt.Key.Key_J:
        motion.adjust_speed(-5)
    elif key == Qt.Key.Key_L:
        motion.adjust_speed(5)
    elif key == Qt.Key.Key_7:
        motion.adjust_amplitude(-10)
    elif key == Qt.Key.Key_9:
        motion.adjust_amplitude(10)
    elif key == Qt.Key.Key_U:
        motion.adjust_center(-5)
    elif key == Qt.Key.Key_O:
        motion.adjust_center(5)
    elif key == Qt.Key.Key_I:
        motion.cycle_shape()
    elif key == Qt.Key.Key_Slash:
        motion.toggle_cruise()
    elif key == Qt.Key.Key_Backslash:
        motion.quarter_offset()
    else:
        return False
    return True


