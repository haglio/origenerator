"""The Generate button, doubling as the run's progress bar.

Clicking it launches a re-roll; while that job is in flight the button itself
fills left-to-right with ComfyUI's real per-step progress (no separate status
bar) — and stays pressable, since another press queues another job rather than
relaunching over the one running. It also flashes a form guard — e.g. "select an
input image" — when a Generate is blocked, so the panel needs no standing status
line.

Its resting caption is the panel's to set: settings that would re-create a past
generation exactly make the press draw a fresh seed instead, and the button says
so ("Generate with Random seed") rather than a dialog asking after the click.
"""

from PyQt6.QtWidgets import QPushButton
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import QTimer

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BLUE

_GUARD_MS = 2500  # how long a blocked-Generate guard message lingers on the button
DEFAULT_CAPTION = "Generate"  # the plain face; the panel sets the other (set_caption)


class GenerateButton(QPushButton):
    """A Generate button whose face is also the progress bar.

    ``start`` puts it in progress mode (still pressable, still wearing its
    caption, filling from 0); ``set_progress`` advances the fill; ``finish``
    restores the idle button. ``flash_guard`` briefly shows a guard message while
    idle, and ``set_caption`` sets the words everything else comes back to.
    """

    def __init__(self, parent=None):
        super().__init__(DEFAULT_CAPTION, parent)
        self.setObjectName("generateBtn")
        self._caption = DEFAULT_CAPTION      # the resting words (see set_caption)
        self._fraction: float | None = None   # None while idle; 0..1 while running
        self._show_progress_face(False)
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
        self._show_progress_face(True)
        self.update()

    def set_progress(self, value: int, maximum: int):
        self._fraction = (value / maximum) if maximum else 0.0
        self.update()

    def finish(self, enabled: bool):
        """Back to the unfilled button wearing its caption; ``enabled`` stays False
        in a read-only gallery with no client to run against."""
        self._fraction = None
        self.setText(self._caption)
        self._show_progress_face(False)
        self.setEnabled(enabled)
        self.update()

    def _show_progress_face(self, generating: bool):
        """Swap the resting face between the primary blue and a neutral one.

        The fill is a translucent blue wash, which needs a non-blue face under it to
        read as progress at all — over the primary blue it was a blue edge crossing
        an already-blue button. The sheet owns both looks (``[generating="true"]`` in
        :mod:`stylesheet`) rather than an inline stylesheet set here, which would
        drop everything else it says about this button; a property swap only takes
        effect after a repolish.
        """
        self.setProperty("generating", generating)
        self.style().unpolish(self)
        self.style().polish(self)

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
        if self._fraction is None:  # a run may have started meanwhile — leave it be
            self.setText(self._caption)

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
