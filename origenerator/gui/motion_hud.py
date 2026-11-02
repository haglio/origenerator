from __future__ import annotations

from PyQt6.QtCore import Qt


def apply_motion_key(motion, key, *, on_drive_toggle=None) -> bool:
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


