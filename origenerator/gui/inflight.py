"""What every surface knows about a generation that is still in flight.

Three widgets show queued and running work — the Recents collection's cards
(:mod:`origenerator.gui.inflight_card`), the Job Queue
(:mod:`origenerator.gui.job_queue_view`), and the config pane's live preview
note — and none of them should know where a job came from or how to reach it.
They are handed :class:`InFlightItem` instead: a plain view-model the gallery
builds per job, carrying what to draw, how to stop it, and how to go to it.

How the run itself is going — what it is doing, its latest frame, how far along
it is, how long it has left — is :class:`RunReading`, which an item carries and
which is also all the tile of an image being enhanced is handed
(:mod:`origenerator.gui.thumbnail_widget`): that tile has a thumbnail, a name and
a click of its own already.

:func:`queue_wait_text` is here for the same reason: how a wait reads is one
wording, shared by every surface that has to say it — as is
:data:`CANCEL_TEXT`, the label on the button that throws the run in flight
away, which three panes each draw, and :func:`stop_auto_generate_text`, the menu entry
beside it that ends Auto-Generate as well as the run.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from origenerator.gallery import JobKind
from origenerator.gui.generation_job import JobState
from origenerator.timing import RunTiming, clock_duration, elapsed_since, queue_estimate_label


@dataclass
class InFlightItem:
    """One currently queued or running generation, as the gallery's surfaces see it."""

    key: str                     # stable id: the job's prompt id
    caption: str                 # what a surface labels the job (workflow › prompt)
    reading: RunReading          # how the run itself is going
    reveal: Callable[[], None]   # go to its folder and live tile, or to the image it enhances
    media_type: str | None = None  # "image"/"video" for the corner badge, if known
    cancel: Callable[[], None] | None = None  # stop the job, when it can be cancelled from here
    shield: Callable[[bool], None] | None = None  # put its shield on or off, where cancel can stop it
    shielded: bool = False
    auto_generating: bool = False  # its folder auto-generates, so a :attr:`cancel` starts its next seed
    # End Auto-Generate in its folder. What a menu's real stop calls before
    # :attr:`cancel`, since discarding the run while Auto-Generate is on only starts the
    # next one. ``None`` alongside a ``None`` cancel — a run this session holds no
    # job for is not one this session can stop either.
    stop_auto: Callable[[], None] | None = None
    foreign_ahead: int | None = None  # jobs another app has in front of it in ComfyUI
    starts_at: float | None = None  # when a video waiting out the minute after an image starts
    # What kind of work this is in one word — "Image", "Video", "Enhance"
    # (:func:`gallery.job_kind_label`), or "" for a workflow this build has no
    # template for. The workflow's display name is in :attr:`caption` and answers
    # a different question: which settings, not what it costs to ask for.
    job_kind: str = ""
    # A request queued this one, rather than a press of Generate or
    # Auto-Generate. Worth its own mark: it is the one kind of job the
    # user launched without looking at a form, and so the one they are most
    # likely to find in the line without recognizing it.
    requested: bool = False
    # Its folder's Modify (all seeds) queued this one, one run per image.
    modified: bool = False
    # The start frame this run is built from, as its ``LoadImage`` reference —
    # what an i2v (and an enhance) is *of*. Its thumbnail is the fastest way to
    # tell two queued videos apart, their captions being their shared workflow.
    source_image: str | None = None
    # A file on disk showing what this run came from — the start frame above,
    # or the image a request was made of. A queued run has no thumbnail of its
    # own, so surfaces that would otherwise show a blank plate stand this
    # under the wait, blurred (:mod:`origenerator.gui.blurred`). ``None``
    # where the run came from nothing, which is most images.
    source_file: str | None = None
    # The act picked in the Combine panel's dropdown, for a run launched from
    # there — "" for every other run, and for a combine that was given a dropped
    # video instead of a picked act. It is the one word saying what this video
    # will *do*, and nothing else on the row carries it.
    act: str = ""
    # The thumbnail of the video whose settings this run re-uses, for a combine
    # given a dropped video — the only thing naming which video that was. Drawn
    # gray beside the start frame: it lends the settings, not the result, and a row
    # showing it alone reads as a job that is that video. Empty where an act was
    # picked instead: :attr:`act` already says what was chosen, and
    # the clip its settings were mined out of was never the user's pick.
    source_video_thumbnail: str | None = None
    prompt_edited: bool = False
    # Up to four thumbnail files from the folder this job will land in — what a
    # run with no thumbnail of its own can be recognized by, its own output being
    # the thing that doesn't exist yet.
    folder_thumbnails: tuple = ()
    # Not a job yet (:mod:`origenerator.gui.starting_rows`).
    starting: bool = False
    # One place up or down the line, where the queue lets it go that way: never
    # past a shielded run being made or what a slideshow is locked on, and never
    # for a run this window holds no job for.
    move_up: Callable[[], None] | None = None
    move_down: Callable[[], None] | None = None


def queue_lead_text(item: InFlightItem) -> str:
    """The head of a queue row: what the job costs, what it is, and who asked.

    ``"~2 min · Video · dancing · Auto · Request"``. Everything here is a fact about
    the job that is true before it starts, which is what a line of waiting work is
    read for — the price first, because that is what "how long until my turn" is
    added up out of, and because it is the one figure that makes a queue of four
    videos read differently from a queue of four images.

    The act follows the kind, for a run the Combine panel launched from its
    dropdown: the kind says a video is being made, and the act says
    which video — the whole of what the user chose, and the one thing separating
    two runs on the same image. It rides through "Edit…" too, so a
    combination edited before launching still says what it was asked for.

    The two marks at the end are only ever *added*: a job nobody typed a prompt
    for is the kind that piles up unnoticed (Auto-Generate makes one
    every few seconds, a folder's Modify a run per image at once), and a
    request is the kind that is easy not to recognize later. A hand-launched job
    says neither, and needs to say neither.
    """
    parts = [queue_estimate_label(item.reading.typical_seconds)]
    if item.job_kind:
        parts.append(item.job_kind)
    if item.act:
        parts.append(item.act)
    if item.auto_generating:
        parts.append("Auto")
    if item.requested:
        parts.append("Request")
    if item.modified:
        parts.append("Modify")
    return " · ".join(parts)


def queue_lead_tooltip(item: InFlightItem) -> str:
    """The hover line spelling out :func:`queue_lead_text`, which is abbreviated.

    A bare "~?" is shorthand a row has the width for and a first-time reader has
    no way to expand, so the long form lives one hover away, beside what each
    kind of job is made from.
    """
    if item.starting:
        lines = ["Not sent to ComfyUI yet — this row stands in until it is"]
    elif item.reading.typical_seconds is None:
        lines = ["No timing data for this workflow yet"]
    else:
        lines = [f"About {queue_estimate_label(item.reading.typical_seconds).lstrip('~')}"
                 " on this workflow's recent runs"]
    lines.extend(part for part in (_KIND_TOOLTIPS.get(item.job_kind),) if part)
    if item.act:
        lines.append(f"The “{item.act}” act, picked in Combine")
    if item.auto_generating:
        lines.append("Queued by its folder's Auto-Generate")
    if item.requested:
        lines.append("Queued by a request")
    if item.modified:
        lines.append("Queued by its folder's Modify (all seeds)")
    return "\n".join(lines)


_KIND_TOOLTIPS = {
    JobKind.IMAGE: "An image",
    JobKind.VIDEO: "A video made from a start image",
    JobKind.ENHANCE: "An enhancement of an image already made",
    JobKind.TRAINING: "A fix's LoRA being trained: nothing is sent to ComfyUI until it ends",
}


# How often a surface showing a run in flight re-reads the clock. Its own timer
# rather than the gallery's poll, so the count advances a second at a time
# whether or not a refresh has landed.
TICK_MS = 1000

@dataclass
class RunReading:
    """How a run in flight is going, as every surface showing one reads it.

    A queued or running generation carries one inside its :class:`InFlightItem`;
    the tile of an image being enhanced is handed one on its own, since the
    thumbnail, the name and the click there are the tile's already.
    """

    status: str                              # JobState.RUNNING, QUEUED or SPEAKING
    frame: bytes | None = None               # latest live frame, if one has arrived
    progress: tuple[int, int] | None = None  # (cumulative, total) sampler steps
    # The pass running right now, on its own count, for the band along the foot
    # of the bar. An enhancement is the run that most needs it: the upscale and
    # each detail fix is a pass of its own, and one bar between them can only
    # restart per fix.
    pass_progress: tuple[int, int] | None = None
    stage: str = ""       # what the app is doing, for the caption over that bar
    # When ComfyUI began executing it (None while it's still queued), and what
    # this workflow's recent runs say a whole one takes — the two halves of the
    # countdown on the bar.
    started_at: float | None = None
    typical_seconds: float | None = None

    @property
    def rendering(self) -> bool:
        """Whether ComfyUI is working on it now, rather than holding it in line."""
        return self.status == JobState.RUNNING

    def caption(self, *, compact: bool = False) -> str:
        """The line over the bar: what is being done, and how much is left of it."""
        return RunTiming(elapsed_since(self.started_at), self.progress,
                         self.typical_seconds).status_label(step=self.stage,
                                                            compact=compact)

    def bars(self) -> tuple:
        """What the bar and its band show — nothing at all while the run is still
        waiting, which has no progress to report and no time to count down."""
        return (self.progress, self.pass_progress) if self.rendering else (None, None)


def first_movable(items) -> int:
    """Where in a line of runs a move may begin or end: past every run that
    holds its place at the front, which nothing can be put in front of."""
    return next((index for index, item in enumerate(items) if movable(item)), len(items))


def movable(item) -> bool:
    return item.move_up is not None or item.move_down is not None


def jobs_to_shield(items) -> list:
    return [item for item in items if item.shield is not None and not item.shielded]


def jobs_to_cancel(items) -> list:
    return [item for item in items if item.cancel is not None]


def shield_every_job(items) -> None:
    for item in jobs_to_shield(items):
        item.shielded = True
        item.shield(True)


ALREADY_MAKING_ONE_TIP = "This folder is already making one"
SHIELD_TIP = ("Shield this generation: images you ask for while it is being made "
              "wait for it instead of stopping it")
MOVE_UP_TIP = "Move this job up the Job Queue"
MOVE_DOWN_TIP = "Move this job down the Job Queue"
SHIELD_ALL_TEXT = "All"  # beside the shield, so it reads "Shield All"
SHIELD_ALL_TIP = "Shield every job in the Job Queue"
CANCEL_ALL_TEXT = "Cancel All"
CANCEL_ALL_TIP = "Cancel every job in the Job Queue"


def cancel_all_question(total: int) -> str:
    return ("Cancel the job in the Job Queue?" if total == 1
            else f"Cancel all {total} jobs in the Job Queue?")


CANCEL_TEXT = "Cancel"


def cancel_tooltip(auto_generating: bool) -> str:
    """While the folder is auto-generating, a Cancel ends nothing: Auto-Generate
    takes it as a discarded seed and launches another at once
    (:meth:`AutoGenerateController.note_canceled`), and the hover says so."""
    return ("Throw away this seed and start the next" if auto_generating
            else "Cancel this generation")


EMPTY_QUEUE_TEXT = "(queued jobs show up here)"
START_NOW_TEXT = "Start now"
START_NOW_TOOLTIP = "Start the video now instead of a minute after your last image"
CLEAR_TEXT = "Clear"


def clear_queue_tooltip(foreign: int) -> str:
    return (f"Drop the {foreign} job{'' if foreign == 1 else 's'} another app has"
            " queued on ComfyUI")


def stop_auto_generate_text() -> str:
    """The menu entry that ends Auto-Generate and the run inside it.

    A button carries one act, so while Auto-Generate is on its Cancel only
    throws the seed away, and there is nowhere left on that surface to ask for
    a stop: the only one was the Auto switch, which is in the header rather
    than on the card you are looking at. A menu has room for both, and this is
    the other one.

    It says Auto-Generate goes off rather than reading "Cancel", because switching a
    standing instruction off is a bigger act than throwing one seed away, and it
    is not something to discover afterwards.
    """
    return "Cancel and stop auto-generating"


def stop_auto_generate_tooltip() -> str:
    """The hover line for :func:`stop_auto_generate_text`'s entry."""
    return "Throw this run away and switch Auto-Generate off"


def queue_wait_text(foreign_ahead: int | None, starts_at: float | None = None, *,
                    now=time.monotonic) -> str | None:
    """How a job's wait reads while another app's work is ahead of it on ComfyUI,
    or while it is a video waiting out the minute after an image
    (:meth:`JobQueue.starts_at`, on the queue's clock). A wait on the user's own
    jobs earns no line: "waiting in ComfyUI" would send them hunting for phantom
    jobs that are their own. ``None`` is every surface's cue to say what it always said.
    """
    if foreign_ahead:
        return (f"Waiting on {foreign_ahead} job{'' if foreign_ahead == 1 else 's'}"
                " from another app")
    if (left := seconds_until_start(starts_at, now=now)) is not None:
        return f"Starts in {clock_duration(math.ceil(left))}"
    return None


def seconds_until_start(starts_at: float | None, *, now=time.monotonic) -> float | None:
    if starts_at is None or (left := starts_at - now()) <= 0:
        return None
    return left


def starting_row_text(starting: bool) -> str | None:
    """What a row that is not a job yet says in place of a wait: ``None`` once it
    is, which is every row that came off the database."""
    return "Starting…" if starting else None


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
