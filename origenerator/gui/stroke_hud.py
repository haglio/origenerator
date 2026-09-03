"""The OSR2 stroke's shared key cluster.

The stroke driver is app-global — the device shouldn't care which window is in
front — so every surface that can drive it (the gallery window, the fullscreen
show) answers the same keys through this helper,
and floats the same drive panel
(:mod:`origenerator.gui.stroke_panel`). The keys are genau's own, so the muscle
memory carries: Space starts/stops, J/L speed, 7/9 amplitude, U/O center,
I shape, / cruise control, backslash nudges a quarter cycle.
"""

from PyQt6.QtCore import Qt

# The key legend, shown as the drive panel's tooltip.
STROKE_KEY_LEGEND = ("Space drives · J/L speed · 7/9 travel · U/O center"
                     r" · I shape · / cruise · \ nudge")


def apply_stroke_key(stroke, key, *, on_drive_toggle=None) -> bool:
    """Route one of genau's stroke keys to ``stroke``; ``False`` for any other
    key (or with no driver wired), so the caller falls through to its own
    handling.

    ``on_drive_toggle`` takes Space instead of the stroke's own switch. Driving
    the OSR2 is one switch now — the gallery's — which picks the funscript or
    the stroke by what is playing, so Space has to reach *that* rather than
    start a second source alongside a script already streaming.
    """
    if stroke is None:
        return False
    if key == Qt.Key.Key_Space:
        (on_drive_toggle or stroke.toggle)()
    elif key == Qt.Key.Key_J:
        stroke.adjust_speed(-5)
    elif key == Qt.Key.Key_L:
        stroke.adjust_speed(5)
    elif key == Qt.Key.Key_7:
        stroke.adjust_amplitude(-10)
    elif key == Qt.Key.Key_9:
        stroke.adjust_amplitude(10)
    elif key == Qt.Key.Key_U:
        stroke.adjust_center(-5)
    elif key == Qt.Key.Key_O:
        stroke.adjust_center(5)
    elif key == Qt.Key.Key_I:
        stroke.cycle_shape()
    elif key == Qt.Key.Key_Slash:
        stroke.toggle_cruise()
    elif key == Qt.Key.Key_Backslash:
        stroke.quarter_offset()
    else:
        return False
    return True


