from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from shared_ui.alert import AlertDialog, Level

from origenerator import alert

TITLE = "Generation failed"


class GenerationFailed:
    def __init__(self, window: QWidget):
        self._window = window
        self._box: AlertDialog | None = None
        self._reasons: Counter[str] = Counter()

    def say(self, reason: str) -> None:
        if self._box is None:
            self._reasons = Counter()
        else:
            self._put_away(self._box)
        self._reasons[reason] += 1
        self._box = self._window_saying(worded(self._reasons))
        self._box.open()

    def _window_saying(self, message: str) -> AlertDialog:
        box = AlertDialog(TITLE, message, level=Level.WARNING, icon=alert.window_icon())
        box.setParent(self._window, box.windowFlags())
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.finished.connect(self._dismissed)
        return box

    def _put_away(self, box: AlertDialog) -> None:
        box.finished.disconnect(self._dismissed)
        box.close()

    def _dismissed(self) -> None:
        self._box = None


def worded(reasons: Counter[str]) -> str:
    return "\n\n".join(reason if times == 1 else f"{reason} ({times} generations)"
                       for reason, times in reasons.items())
