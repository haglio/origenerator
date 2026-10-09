"""The "Generation failed" dialog: one, however many failures arrive while it is up."""
from __future__ import annotations

from collections import Counter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QWidget

TITLE = "Generation failed"


class GenerationFailed:
    def __init__(self, window: QWidget):
        self._window = window
        self._box: QMessageBox | None = None
        self._reasons: Counter[str] = Counter()

    def say(self, reason: str) -> None:
        if self._box is None:
            self._box = QMessageBox(QMessageBox.Icon.Warning, TITLE, "",
                                    QMessageBox.StandardButton.Ok, self._window)
            self._box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._box.finished.connect(self._dismissed)
            self._reasons = Counter()
        self._reasons[reason] += 1
        self._box.setText(worded(self._reasons))
        self._box.open()

    def _dismissed(self) -> None:
        self._box = None


def worded(reasons: Counter[str]) -> str:
    return "\n\n".join(reason if times == 1 else f"{reason} ({times} generations)"
                       for reason, times in reasons.items())
