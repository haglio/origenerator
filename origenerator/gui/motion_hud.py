"""The OSR2 motion's shared key cluster.

The motion driver is app-global — the device shouldn't care which window is in
front — so every surface that can drive it (the gallery window, the fullscreen
slideshow) answers the same keys through this helper, and each shows the same drive
readout: at Core's top left on a console of its own
(:mod:`origenerator.gui.osr2_controls`), and over a slideshow on the one HUD it
wears (:mod:`origenerator.gui.slideshow_hud`).  The keys are genau's own, so the
muscle memory carries: Space starts/stops, J/L speed, 7/9 amplitude, U/O center,
I shape, ; human-inspired motion.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt


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
    elif key == Qt.Key.Key_Semicolon:
        motion.toggle_learned()
    else:
        return False
    return True


