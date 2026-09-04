"""The Generate button: it submits a run to the queue, and nothing more.

Pressing it launches a job and it is done — the strip's queue and the browser
pane's in-flight cards are where a run in flight is watched, each showing the
same reading of it (:func:`origenerator.timing.progress_status_label`). The
button used to fill with that run's progress as well, which put a third,
differently-worded account of one run on screen and tied the control that starts
work to the state of work already going.

It stays pressable throughout, since another press queues another job rather
than relaunching over the one running. It also flashes a form guard — e.g.
"select an input image" — when a Generate is blocked, so the panel needs no
standing status line.

Its resting caption is the panel's to set: settings that would re-create a past
generation exactly make the press draw a fresh seed instead, and the button says
so ("Generate with Random seed") rather than a dialog asking after the click.
"""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QPushButton

_GUARD_MS = 2500  # how long a blocked-Generate guard message lingers on the button
DEFAULT_CAPTION = "Generate"  # the plain face; the panel sets the other (set_caption)


class GenerateButton(QPushButton):
    """A Generate button that wears its caption whatever else is in flight."""

    def __init__(self, parent=None):
        super().__init__(DEFAULT_CAPTION, parent)
        self.setObjectName("generateBtn")
        self._caption = DEFAULT_CAPTION      # the resting words (see set_caption)
        self._guard_timer = QTimer(self)
        self._guard_timer.setSingleShot(True)
        self._guard_timer.timeout.connect(self._clear_guard)

    def set_caption(self, text: str):
        """Set the words the button rests on — "Generate", or "Generate with Random
        seed" where the settings on the form would otherwise re-create a past
        generation and the press will draw a fresh seed instead.

        A guard message on the face keeps it until its own timer ends: the caption
        is recomputed on a form edit, which is exactly what the user is doing while
        a guard tells them what the form still needs.
        """
        self._caption = text
        if not self._guard_timer.isActive():
            self.setText(text)

    def flash_guard(self, message: str):
        """Show a form guard on the button for a moment, then revert to its caption."""
        self.setText(message)
        self._guard_timer.start(_GUARD_MS)

    def _clear_guard(self):
        self.setText(self._caption)
