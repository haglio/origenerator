from __future__ import annotations

from dataclasses import dataclass

from origenerator.gallery import JobKind
from origenerator.generation_state import GenerationSource
from origenerator.timing import clock_duration

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
    ``generation`` is the item the run is about, which a notice of it is a way
    back to: the run's own id, except for an enhance, whose own row is folded
    into the picture it improved the moment it lands.
    """

    kind: str
    recipe: str
    seconds: float | None
    ok: bool
    source: str
    generation: str


@dataclass(frozen=True)
class Notice:
    """One thing to say, in the two lines a desktop notification gives it, and
    the item it takes the user to when they answer it."""

    title: str
    body: str
    ok: bool
    generation: str


def notice_for(outcome: RunOutcome) -> Notice | None:
    if outcome.kind != JobKind.VIDEO:
        return None
    if outcome.source != GenerationSource.GENERATED:
        return None
    if outcome.seconds is None or outcome.seconds < LONG_RUN_SECONDS:
        return None
    took = clock_duration(outcome.seconds)
    if outcome.ok:
        return Notice(f"{outcome.kind} ready", f"{outcome.recipe} · {took}", ok=True,
                      generation=outcome.generation)
    return Notice(f"{outcome.kind} failed",
                  f"{outcome.recipe} · stopped after {took}", ok=False,
                  generation=outcome.generation)
