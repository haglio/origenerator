"""What color a switch on the button bank is lit in while it is on, read off its
own style and named the way a person would name it."""
from __future__ import annotations

import re

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QToolButton


def lit_in(switch: QToolButton) -> str:
    lit = re.search(r":checked \{ background-color: (#[0-9a-fA-F]{6})", switch.styleSheet())
    hue = QColor(lit.group(1)).hsvHue()
    if 40 <= hue <= 70:
        return "yellow"
    if 190 <= hue <= 250:
        return "blue"
    return f"hue {hue}"
