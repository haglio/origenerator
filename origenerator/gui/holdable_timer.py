from __future__ import annotations

from PyQt6.QtCore import QTimer


class HoldableTimer(QTimer):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSingleShot(True)
        self._left_ms: int | None = None

    def run_for(self, ms: int) -> None:
        self._left_ms = None
        self.start(ms)

    def cancel(self) -> None:
        self._left_ms = None
        self.stop()

    def hold(self, held: bool) -> None:
        if held and self.isActive():
            self._left_ms = self.remainingTime()
            self.stop()
        elif not held and self._left_ms is not None:
            self.start(self._left_ms)
            self._left_ms = None
