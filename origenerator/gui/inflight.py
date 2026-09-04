"""What every surface knows about a generation that is still in flight.

Three widgets show queued and running work — the Recents shelf's cards
(:mod:`origenerator.gui.inflight_card`), the bottom strip's queue
(:mod:`origenerator.gui.generation_queue`), and the config pane's live preview
note — and none of them should know where a job came from or how to reach it.
They are handed :class:`InFlightItem` instead: a plain view-model the gallery
builds per job, carrying what to draw, how to stop it, and how to go to it.

:class:`EnhancingRun` is the same idea for the one run that has no card of its
own: an enhancement is shown on the tile of the image it improves
(:mod:`origenerator.gui.thumbnail_widget`), which already has a picture, a name
and a click of its own — so all it needs handed to it is how the run is going.

:func:`queue_wait_text` is here for the same reason: what a wait on another app
reads like is one wording, shared by every surface that has to say it — as is
:func:`discard_run_text`, the label on the button that throws the run in flight
away, which three panes each draw, and :func:`stop_loop_text`, the menu entry
beside it that ends the loop as well as the run.
"""

from collections.abc import Callable
from dataclasses import dataclass

from origenerator.timing import queue_estimate_label


@dataclass
class InFlightItem:
    """One currently queued or running generation, as the gallery's surfaces see it."""

    key: str                     # stable id: the job's prompt id
    caption: str                 # what a surface labels the job (workflow › prompt)
    status: str                  # "running" or "queued"
    frame: bytes | None          # latest live preview frame, if one has arrived
    reveal: Callable[[], None]   # show the job's gallery folder and its live tile
    media_type: str | None = None  # "image"/"video" for the corner badge, if known
    # Which side of the tree the job belongs to, by the shape it was asked to
    # come out: a running generation has no picture to measure, and its card has
    # to sit on the shelf its picture will land on rather than move there later.
    orientation: str = "landscape"
    progress: tuple[int, int] | None = None  # (cumulative, total) sampler steps, for a progress bar
    # The one sampler pass running right now, on its own count — the band along
    # the foot of that bar. ``None`` for a job of a single pass, which has
    # nothing to say the whole-run reading doesn't.
    pass_progress: tuple[int, int] | None = None
    cancel: Callable[[], None] | None = None  # stop the job, when it can be cancelled from here
    auto_generating: bool = False  # its folder is auto-looping, so :attr:`cancel` means "next seed"
    # End the loop its folder is on. What a menu's real stop calls before
    # :attr:`cancel`, since discarding the run under a live loop only starts the
    # next one. ``None`` alongside a ``None`` cancel — a run this session holds no
    # job for is not one this session can stop either.
    stop_auto: Callable[[], None] | None = None
    foreign_ahead: int | None = None  # jobs another app has in front of it in ComfyUI
    held: bool = False           # the queue is holding it back (a video, during a slideshow)
    # The two halves of the countdown on the job being rendered: when ComfyUI
    # began executing it (None while it's still queued), and what this workflow's
    # recent runs say a whole one takes.
    started_at: float | None = None
    typical_seconds: float | None = None
    # What kind of work this is in one word — "Image", "T2V", "I2V", "Enhance"
    # (:func:`gallery.job_kind_label`), or "" for a workflow this build has no
    # template for. The workflow's display name is in :attr:`caption` and answers
    # a different question: which recipe, not what it costs to ask for.
    job_kind: str = ""
    # A spoken "Request … over" queued this one, rather than a press of Generate
    # or an auto-generate loop. Worth its own mark: it is the one kind of job the
    # user launched without looking at a form, and so the one they are most
    # likely to find in the line without recognizing it.
    requested: bool = False
    # The start frame this run is built from, as its ``LoadImage`` reference —
    # what an i2v (and an enhance) is *of*. Its picture is the fastest way to
    # tell two queued videos apart, their captions being their shared recipe.
    source_image: str | None = None
    # A file on disk showing what this run came from — the start frame above,
    # or the image a request was made of. A queued run has no picture of its
    # own, so surfaces that would otherwise show a blank plate stand this
    # behind the wait, blurred (:mod:`origenerator.gui.blurred`). ``None``
    # where the run came from nothing, which is most images.
    source_picture: str | None = None
    # The act picked in the Combine panel's dropdown, for a run launched from
    # there — "" for every other run, and for a combine that was given a dropped
    # video instead of a picked act. It is the one word saying what this video
    # will *do*, and nothing else on the row carries it.
    recipe_category: str = ""
    # The thumbnail of the video whose settings this run re-uses, for a combine
    # given a dropped video — the only thing naming which recipe that was. Drawn
    # gray beside the start frame: it is the recipe, not the result, and a row
    # showing it alone reads as a job that is that video. Empty where an act was
    # picked instead: :attr:`recipe_category` already says what was chosen, and
    # the clip its recipe was mined out of was never the user's pick.
    recipe_thumbnail: str | None = None
    # Up to four thumbnail files from the folder this job will land in — what a
    # run with no picture of its own can be recognized by, its own output being
    # the thing that doesn't exist yet.
    folder_thumbnails: tuple = ()
    # This one is not a job yet: it stands in for a press of Generate whose work
    # to become one — resolving a recipe, building the params, the submit itself
    # — has not finished. It has no row, no id on the server, and nothing to
    # cancel; it exists so the press has a visible answer.
    starting: bool = False


def queue_lead_text(item: InFlightItem) -> str:
    """The head of a queue row: what the job costs, what it is, and who asked.

    ``"~2 min · I2V · dancing · Auto · Request"``. Everything here is a fact about
    the job that is true before it starts, which is what a line of waiting work is
    read for — the price first, because that is what "how long until my turn" is
    added up out of, and because it is the one figure that makes a queue of four
    videos read differently from a queue of four pictures.

    The act follows the kind, for a run the Combine panel launched from its
    dropdown: "I2V" says a video is being made from a frame, and the act says
    which video — the whole of what the user chose, and the one thing separating
    two runs on the same picture. It rides through "Edit…" too, so a
    combination edited before launching still says what it was asked for.

    The two marks at the end are only ever *added*: a job nobody typed a prompt
    for is the kind that piles up unnoticed (an auto-generate loop makes one
    every few seconds, a folder-wide request a run per image at once), and a
    request is the kind that is easy not to recognize later. A hand-launched job
    says neither, and needs to say neither.
    """
    parts = [queue_estimate_label(item.typical_seconds)]
    if item.job_kind:
        parts.append(item.job_kind)
    if item.recipe_category:
        parts.append(item.recipe_category)
    if item.auto_generating:
        parts.append("Auto")
    if item.requested:
        parts.append("Request")
    return " · ".join(parts)


def queue_lead_tooltip(item: InFlightItem) -> str:
    """The hover line spelling out :func:`queue_lead_text`, which is abbreviated.

    "I2V" and a bare "~?" are shorthand a row has the width for and a first-time
    reader has no way to expand, so the long form lives one hover away.
    """
    if item.starting:
        lines = ["Not sent to ComfyUI yet — this row stands in until it is"]
    elif item.typical_seconds is None:
        lines = ["No timing data for this workflow yet"]
    else:
        lines = [f"About {queue_estimate_label(item.typical_seconds).lstrip('~')}"
                 " on this workflow's recent runs"]
    lines.extend(part for part in (_KIND_TOOLTIPS.get(item.job_kind),) if part)
    if item.recipe_category:
        lines.append(f"The “{item.recipe_category}” act, picked in Combine")
    if item.auto_generating:
        lines.append("Queued by its folder's auto-generate loop")
    if item.requested:
        lines.append("Queued by a request — spoken, or one image of a "
                     "request made of a whole folder")
    return "\n".join(lines)


# What each of :func:`gallery.job_kind_label`'s four words means, spelled out for
# the hover. An unregistered workflow's "" has no entry and contributes no line.
_KIND_TOOLTIPS = {
    "Image": "An image",
    "T2V": "A video from the prompt alone",
    "I2V": "A video from a start frame",
    "Enhance": "An enhancement of an image already made",
}


@dataclass
class EnhancingRun:
    """An enhancement in flight, as the tile of the image it improves sees it.

    The tile shows it the way every other in-flight surface shows its work: the
    stage on a dimming scrim over the picture, and how far along it is on a bar
    along the picture's foot. So it is handed the same readings an
    :class:`InFlightItem` carries, minus the ones the tile already has — the
    picture is the image being enhanced, and the name and the click are the
    tile's own.
    """

    status: str                              # "running" or "queued"
    frame: bytes | None                      # latest live frame, if one has arrived
    progress: tuple[int, int] | None = None  # (cumulative, total) sampler steps
    # The pass running right now, on its own count, for the band along the foot
    # of the bar. An enhancement is the run that most needs it: the upscale and
    # each detail fix is a pass of its own, and one bar between them can only
    # restart per fix.
    pass_progress: tuple[int, int] | None = None
    # When ComfyUI began executing it (None while it's still queued), and what
    # this workflow's recent runs say a whole one takes — the two halves of the
    # countdown on the bar.
    started_at: float | None = None
    typical_seconds: float | None = None


def discard_run_text(auto_generating: bool) -> str:
    """The label on the button that throws away the run being made — one wording
    for the folder's live tile, the bottom strip's rows, and the config pane.

    While the folder is auto-generating, that press ends nothing: the loop takes
    it as a discarded seed and launches another at once (see
    :meth:`AutoGenerateController.note_canceled`). "Cancel" would be a promise of
    a stop that doesn't come — only the Auto toggle stops — so there it reads
    "Next seed", which is what the press actually gets you.
    """
    return "Next seed" if auto_generating else "Cancel"


def discard_run_tooltip(auto_generating: bool) -> str:
    """The hover line for :func:`discard_run_text`'s button."""
    return ("Throw away this seed and start the next" if auto_generating
            else "Cancel this generation")


def stop_loop_text() -> str:
    """The menu entry that ends an auto-generate loop and the run inside it.

    A button carries one act, so while the loop is on it carries the one the
    press performs — "Next seed" — and there is nowhere left on that surface to
    ask for a stop: the only one was the Auto switch, which is in the header
    rather than on the card you are looking at. A menu has room for both, and
    this is the other one.

    It says the loop goes off rather than reading "Cancel", because switching a
    standing instruction off is a bigger act than throwing one seed away, and it
    is not something to discover afterwards.
    """
    return "Cancel and stop auto-generating"


def stop_loop_tooltip() -> str:
    """The hover line for :func:`stop_loop_text`'s entry."""
    return "Throw this run away and switch the loop off"


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


def queue_held_text(held: int | None) -> str | None:
    """What a queue holding videos back for a slideshow reads like.

    A line that stops moving with the GPU idle is the same mystery as a wait
    behind another app's work, and worse for being this app's own doing — so the
    strip says it outright, and says what ends it. ``None`` when the gate is
    holding nothing, which is every moment no slideshow is playing.
    """
    if not held:
        return None
    return (f"{held} video{'' if held == 1 else 's'} held until the slideshow closes")


def starting_row_text(starting: bool) -> str | None:
    """What a row that is not a job yet says in place of a wait.

    Pressing Generate in the Combine panel is not the same as queueing something:
    an act has to be answered by a recipe first — a question put to a local model,
    several seconds of it — and then the params built and the prompt submitted.
    With nothing on screen for that stretch, the press reads as a press that did
    nothing, which is indistinguishable from a wedged app. This row is the answer,
    and it says outright that it is not in the line yet.

    ``None`` once it is, which is every row that came off the database.
    """
    return "Starting…" if starting else None


def held_row_text(held: bool) -> str | None:
    """The same thing said in one queue row's width, or ``None`` if it can start."""
    return "Held until the slideshow closes" if held else None


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
