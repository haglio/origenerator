from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QRect

LANDSCAPE_MONITOR = QRect(0, 0, 2560, 1440)
PORTRAIT_MONITOR = QRect(2560, 0, 1440, 2560)
TASKBAR = 48


def _monitor(area: QRect) -> SimpleNamespace:
    return SimpleNamespace(geometry=lambda: area,
                           availableGeometry=lambda: area.adjusted(0, 0, 0, -TASKBAR))


HIS_TWO_MONITORS = [_monitor(LANDSCAPE_MONITOR), _monitor(PORTRAIT_MONITOR)]
