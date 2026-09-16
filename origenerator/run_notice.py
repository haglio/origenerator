"""What Windows is told when a long run ends.

A run past a minute is a run the user left: they press Generate, the window
goes on drawing a bar, and they go and do something else. Every surface this
app reports a run on — the tile, the queue strip, the bar along its foot —
reaches exactly as far as the window it is drawn in, so a run that outlasts
their attention has no way of telling them it landed. A desktop notification
does, which is what this is the words for.

Two runs are never announced. A short one was over before anyone could leave,
so a notice for it interrupts someone about something they just watched. And
the app's own background work — the idle experiments, the base re-renders
repairing an enhance — was never waited on by anyone: those run by the dozen
while the machine is idle, and a night of them would be a night of toasts.

Qt-free on purpose, so what gets said can be read by a test with no desktop to
say it on; the saying is :mod:`origenerator.gui.desktop_notices`.
"""
from __future__ import annotations

from dataclasses import dataclass

from origenerator.generation_state import GenerationSource
from origenerator.timing import clock_duration

# The line between a run watched and a run walked away from, in seconds. It is
# where this app's own two kinds of work already part: an image is seconds and
# a video is minutes (:func:`origenerator.gallery.job_kind_label` weighs the
# same two), so it separates the runs nobody sits through from the rest.
LONG_RUN_SECONDS = 60


@dataclass(frozen=True)
class RunOutcome:
    """What a run came to, for whoever reports on it rather than redraws for it.

    ``kind`` and ``recipe`` are the two names a run already wears in the queue:
    what it is in a word ("Image", "Video", "Enhance") and which recipe made it.
    ``seconds`` is how long the run itself took, never counting the wait in the
    line — a quick image that waited its turn after a video is not a long run —
    and ``None`` from a run that died before ComfyUI ever started it.
    ``source`` is who asked for it, in the word its database row stores.
    """

    kind: str
    recipe: str
    seconds: float | None
    ok: bool
    source: str


@dataclass(frozen=True)
class Notice:
    """One thing to say, in the two lines a desktop notification gives it."""

    title: str
    body: str
    ok: bool


def notice_for(outcome: RunOutcome) -> Notice | None:
    """What to say about *outcome*, or ``None`` when it is not worth saying.

    A failed run is announced as well as a finished one: three minutes of GPU
    that produced nothing is exactly the news someone who walked away needs,
    and the dialog the window raises for it is only there when they come back.
    """
    if outcome.source != GenerationSource.GENERATED:
        return None
    if outcome.seconds is None or outcome.seconds < LONG_RUN_SECONDS:
        return None
    took = clock_duration(outcome.seconds)
    if outcome.ok:
        return Notice(f"{outcome.kind} ready", f"{outcome.recipe} · {took}", ok=True)
    return Notice(f"{outcome.kind} failed",
                  f"{outcome.recipe} · stopped after {took}", ok=False)
