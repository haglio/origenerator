"""What every surface knows about a generation that is still in flight.

Three widgets show queued and running work — the Recents shelf's cards
(:mod:`origenerator.gui.inflight_card`), the bottom strip's queue
(:mod:`origenerator.gui.generation_queue`), and the config pane's live preview
note — and none of them should know where a job came from or how to reach it.
They are handed :class:`InFlightItem` instead: a plain view-model the gallery
builds per job, carrying what to draw, how to stop it, and how to go to it.

:func:`queue_wait_text` is here for the same reason: what a wait on another app
reads like is one wording, shared by every surface that has to say it.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class InFlightItem:
    """One currently queued or running generation, as the gallery's surfaces see it."""

    key: str                     # stable id: the job's prompt id
    caption: str                 # what a surface labels the job (workflow › prompt)
    status: str                  # "running" or "queued"
    frame: bytes | None          # latest live preview frame, if one has arrived
    reveal: Callable[[], None]   # show the job's gallery folder and its live tile
    media_type: str | None = None  # "image"/"video" for the corner badge, if known
    progress: tuple[int, int] | None = None  # (cumulative, total) sampler steps, for a progress bar
    cancel: Callable[[], None] | None = None  # stop the job, when it can be cancelled from here
    foreign_ahead: int | None = None  # jobs another app has in front of it in ComfyUI
    # The two halves of the countdown on the job being rendered: when ComfyUI
    # began executing it (None while it's still queued), and what this workflow's
    # recent runs say a whole one takes.
    started_at: float | None = None
    typical_seconds: float | None = None


def queue_wait_text(foreign_ahead: int | None) -> str | None:
    """How a job's wait reads while another app is holding ComfyUI in front of it.

    Only another app's work earns this line. A wait behind the user's own jobs is
    no mystery — ComfyUI is working through exactly what they asked for, and they
    can read the rest of the queue in the bottom strip — so saying "waiting in
    ComfyUI" there sends them hunting for phantom jobs that are their own.

    ``None`` when nothing foreign is ahead: every surface's cue to say what it
    always said.
    """
    if not foreign_ahead:
        return None
    return f"Waiting behind {foreign_ahead} job{'' if foreign_ahead == 1 else 's'} from another app"


def foreign_queue_text(total: int | None) -> str | None:
    """What ComfyUI is holding for someone else while nothing of ours is in flight.

    The line to read *before* pressing Generate. The server is shared and
    outlives whatever queues on it, so its queue can hold a pile of work this
    session never launched — and with nothing on screen to say so, the first
    sign of it used to be a fresh submit reporting six jobs ahead of it out of
    nowhere. ``None`` when the queue holds nothing foreign.
    """
    if not total:
        return None
    return (f"{total} job{'' if total == 1 else 's'} from another app "
            f"{'is' if total == 1 else 'are'} queued on ComfyUI")
