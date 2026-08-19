"""The line of work in flight, floated in the fullscreen show's bottom-left corner.

A show covers the window, and with it the bottom strip that says what is being
made (:mod:`origenerator.gui.generation_queue`) — which is a worse loss here than
anywhere else, for two reasons at once. A show is the one stretch where the queue
deliberately stops moving: every video in it is held until the show closes
(:mod:`origenerator.queue_line`), so a line that isn't moving is the app's own
doing and needs saying. And a show is when the user keeps *adding* to it, since
holding a slide stars it and asks for the better version of that picture — work
launched without a form, at a moment when nothing on screen would otherwise
report it.

So the line rides along, in the one corner this view leaves empty: the console is
top-left (:mod:`origenerator.gui.stroke_panel`), the position counter
bottom-center, the neighbor stills up the two side edges.

One line per job, the one being rendered first, in the readings and the words the
strip already uses (:mod:`origenerator.gui.inflight`) — the same run watched from
a different surface is still the same run. What it leaves behind is the strip's
machinery: no Cancel, no pictures, no drag to reorder. This is a keyboard view
over a picture, and a plate with something to click on it would be a plate that
had to be aimed at; it takes no mouse events at all.

With nothing in flight it takes itself off the screen. Over a full-screen picture
an empty plate is not information, it is furniture.
"""

import time

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt, QTimer

from origenerator.gui.inflight import queue_lead_text, queue_wait_text
from origenerator.timing import progress_status_label

# Where the plate sits: the bottom margin is the position counter's, so the two
# read as one row of chrome across the foot of the screen rather than two plates
# that happen to be near each other.
LEFT_MARGIN = 24
BOTTOM_MARGIN = 24
# How many jobs get a line of their own before the rest become a count. A show is
# for looking at pictures; a folder auto-generating can have a dozen jobs queued,
# and a plate that tall would be a second thing on screen rather than a note in
# the corner.
MAX_LINES = 4
# How often the running job's clock is re-read. Its own timer rather than the
# gallery's 1.5s poll, for the reason the strip's running half keeps one: a
# seconds count driven off that poll skips every other tick.
_TICK_MS = 1000
# What a row waiting on the show itself says, in the width a line here has. The
# strip's :func:`inflight.held_row_text` spells out that the show is what ends it,
# which is worth a row's width in the main window and is not worth one here — the
# show is what the reader is looking at.
_HELD = "held"


def job_line(item, *, now: float | None = None) -> str:
    """The one line this plate gives ``item``.

    A job ComfyUI is rendering says how far along it is; one still waiting says
    what it will cost and what it is, which is what the wait is measured in. A
    job that has been handed over but not started has no reading to give — the
    line falls back to what it would have said while queued, rather than sitting
    blank in the corner — and where another app is what it is waiting on, that is
    the more useful thing to say and it says that instead.
    """
    if item.status == "running":
        started = item.started_at
        clock = time.time() if now is None else now
        elapsed = None if started is None else max(0.0, clock - started)
        reading = progress_status_label(elapsed, item.progress, item.typical_seconds)
        if reading:
            return reading
        return queue_wait_text(item.foreign_ahead) or queue_lead_text(item)
    line = queue_lead_text(item)
    return f"{line} · {_HELD}" if item.held else line


def queue_lines(items, *, now: float | None = None,
                limit: int = MAX_LINES) -> list[str]:
    """Every line the plate shows for ``items``, the job being rendered first.

    Past ``limit`` the rest become one count. A queue too long to list is still
    worth a number: "four more waiting" is the answer to how long this goes on
    for, where four more lines of it would be the corner taking over the screen.
    """
    lines = [job_line(item, now=now) for item in items[:limit]]
    remaining = len(items) - len(lines)
    if remaining > 0:
        lines.append(f"+{remaining} more")
    return lines


class SlideshowQueue(QLabel):
    """The in-flight line as one translucent plate in the show's bottom-left."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        # The plate the position counter and the neighbor stills wear, so
        # everything floated over a show looks like one set of things.
        self.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 140);"
            " padding: 6px 12px; border-radius: 4px;"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Native, because a video surface is a native window on Windows and a
        # plain sibling widget cannot paint over one however it is stacked —
        # which is what made the position counter vanish over a clip until it
        # was made native too.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._items: list = []
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._render)
        self.hide()  # nothing in flight yet, and an empty plate would claim there was

    def set_items(self, items) -> None:
        """Take the queue as the gallery has it — every in-flight job, the one
        being rendered first, which is the order the strip lists them in too."""
        self._items = list(items)
        self._render()

    def lines(self) -> list[str]:
        """What the plate is saying, line by line."""
        return self.text().split("\n") if self.text() else []

    def _render(self) -> None:
        lines = queue_lines(self._items)
        if not lines:
            self.clear()
            self.hide()
            self._tick.stop()
            return
        self.setText("\n".join(lines))
        self.show()
        self.reposition()
        # Only a job ComfyUI is rendering has a reading that moves on its own; a
        # line of waiting work says the same thing until the queue itself
        # changes, and a clock over it would be a timer running for nothing.
        if any(item.status == "running" for item in self._items):
            self._tick.start()
        else:
            self._tick.stop()

    def reposition(self) -> None:
        """The host's bottom-left corner. Grows upward as the line does, so its
        first line — the job with the GPU — stays where the eye last found it."""
        host = self.parentWidget()
        if host is None:
            return
        self.adjustSize()
        self.move(LEFT_MARGIN, max(0, host.height() - self.height() - BOTTOM_MARGIN))
        self.raise_()  # over the media, video surface included

    def hideEvent(self, event):
        """Stop counting when the plate leaves the screen — including when the
        show around it closes, which hides its children without draining the
        queue they were listing."""
        super().hideEvent(event)
        self._tick.stop()
