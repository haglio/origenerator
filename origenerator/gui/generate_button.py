"""The Generate button, doubling as the run's progress bar.

Clicking it launches a re-roll; while that job is in flight the button itself
fills left-to-right with ComfyUI's real per-step progress (no separate status
bar) — and stays pressable, since another press queues another job rather than
relaunching over the one running. It also flashes a form guard — e.g. "select an
input image" — when a Generate is blocked, so the panel needs no standing status
line.
"""

from PyQt6.QtWidgets import QPushButton
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import QTimer

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BLUE

_GUARD_MS = 2500  # how long a blocked-Generate guard message lingers on the button


class GenerateButton(QPushButton):
    """A Generate button whose face is also the progress bar.

    ``start`` puts it in progress mode (disabled, "Generating…", filling from 0);
    ``set_progress`` advances the fill; ``finish`` restores the idle button.
    ``flash_guard`` briefly shows a guard message while idle.
    """

    def __init__(self, parent=None):
        super().__init__("Generate", parent)
        self.setObjectName("generateBtn")
        self._fraction: float | None = None   # None while idle; 0..1 while running
        self._guard_timer = QTimer(self)
        self._guard_timer.setSingleShot(True)
        self._guard_timer.timeout.connect(self._clear_guard)

    def start(self):
        """Enter progress mode: the face fills, and stays pressable.

        ComfyUI works through a queue, so a press while a run is in flight asks
        for another job rather than relaunching over the first — the button must
        not grey out under a "Generating…" label the way it did when a folder
        could only hold one run.
        """
        self._guard_timer.stop()
        self._fraction = 0.0
        self.update()

    def set_progress(self, value: int, maximum: int):
        self._fraction = (value / maximum) if maximum else 0.0
        self.update()

    def finish(self, enabled: bool):
        """Back to the unfilled Generate button; ``enabled`` stays False in a
        read-only gallery with no client to run against."""
        self._fraction = None
        self.setText("Generate")
        self.setEnabled(enabled)
        self.update()

    def flash_guard(self, message: str):
        """Show a form guard on the button for a moment, then revert to Generate."""
        self.setText(message)
        self._guard_timer.start(_GUARD_MS)

    def _clear_guard(self):
        if self._fraction is None:  # a run may have started meanwhile — leave it be
            self.setText("Generate")

    def paintEvent(self, event):
        super().paintEvent(event)  # the normal button face and text
        if self._fraction is None:
            return
        painter = QPainter(self)
        filled = round(self.width() * max(0.0, min(1.0, self._fraction)))
        colour = QColor(BLUE)
        colour.setAlpha(120)  # a translucent wash so the caption stays readable
        painter.fillRect(0, 0, filled, self.height(), colour)
        painter.end()
