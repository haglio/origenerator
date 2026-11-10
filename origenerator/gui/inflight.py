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
    key: str
    caption: str
    reading: RunReading
    reveal: Callable[[], None]
    media_type: str | None = None
    cancel: Callable[[], None] | None = None
    shield: Callable[[bool], None] | None = None
    shielded: bool = False
    populating: bool = False
    stop_populate: Callable[[], None] | None = None
    foreign_ahead: int | None = None
    starts_at: float | None = None
    job_kind: str = ""
    requested: bool = False
    batch_modified: bool = False
    source_image: str | None = None
    source_file: str | None = None
    action: str = ""
    source_video_thumbnail: str | None = None
    prompt_edited: bool = False
    folder_thumbnails: tuple = ()
    starting: bool = False
    move_up: Callable[[], None] | None = None
    move_down: Callable[[], None] | None = None


def queue_lead_text(item: InFlightItem) -> str:
    parts = [queue_estimate_label(item.reading.typical_seconds)]
    if item.job_kind:
        parts.append(item.job_kind)
    if item.action:
        parts.append(item.action)
    if item.populating:
        parts.append("Populate")
    if item.requested:
        parts.append("Request")
    if item.batch_modified:
        parts.append("Modify batch")
    return " · ".join(parts)


def queue_lead_tooltip(item: InFlightItem) -> str:
    if item.starting:
        lines = ["Not sent to ComfyUI yet — this row stands in until it is"]
    elif item.reading.typical_seconds is None:
        lines = ["No timing data for this workflow yet"]
    else:
        lines = [(f"About {queue_estimate_label(item.reading.typical_seconds).lstrip('~')}"
                 " on this workflow's recent runs")]
    lines.extend(part for part in (_KIND_TOOLTIPS.get(item.job_kind),) if part)
    if item.action:
        lines.append(f"The “{item.action}” action, picked in Combine")
    if item.populating:
        lines.append("Queued by its folder's Populate")
    if item.requested:
        lines.append("Queued by a request")
    if item.batch_modified:
        lines.append("Queued by its folder's Modify batch (all seeds)")
    return "\n".join(lines)


_KIND_TOOLTIPS = {
    JobKind.IMAGE: "An image",
    JobKind.VIDEO: "A video made from a start image",
    JobKind.ENHANCE: "An enhancement of an image already made",
    JobKind.TRAINING: "A fix's LoRA being trained: nothing is sent to ComfyUI until it ends",
}


TICK_MS = 1000

@dataclass
class RunReading:
    status: str
    frame: bytes | None = None
    progress: tuple[int, int] | None = None
    pass_progress: tuple[int, int] | None = None
    stage: str = ""
    started_at: float | None = None
    typical_seconds: float | None = None

    @property
    def rendering(self) -> bool:
        return self.status == JobState.RUNNING

    def caption(self, *, compact: bool = False) -> str:
        return RunTiming(elapsed_since(self.started_at), self.progress,
                         self.typical_seconds).status_label(step=self.stage,
                                                            compact=compact)

    def bars(self) -> tuple:
        return (self.progress, self.pass_progress) if self.rendering else (None, None)


def first_movable(items) -> int:
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
SHIELD_ALL_TEXT = "All"
SHIELD_ALL_TIP = "Shield every job in the Job Queue"
CANCEL_ALL_TEXT = "Cancel All"
CANCEL_ALL_TIP = "Cancel every job in the Job Queue"


def cancel_all_question(total: int) -> str:
    return ("Cancel the job in the Job Queue?" if total == 1
            else f"Cancel all {total} jobs in the Job Queue?")


CANCEL_TEXT = "Cancel"


def cancel_tooltip(populating: bool) -> str:
    return ("Throw away this seed and start the next" if populating
            else "Cancel this generation")


EMPTY_QUEUE_TEXT = "(queued jobs show up here)"
START_NOW_TEXT = "Start now"
START_NOW_TOOLTIP = "Start the video now instead of a minute after your last image"
CLEAR_TEXT = "Clear"


def clear_queue_tooltip(foreign: int) -> str:
    return (f"Drop the {foreign} job{'' if foreign == 1 else 's'} another app has"
            " queued on ComfyUI")


def stop_populate_text() -> str:
    return "Cancel and stop populating"


def stop_populate_tooltip() -> str:
    return "Throw this run away and switch Populate off"


def queue_wait_text(foreign_ahead: int | None, starts_at: float | None = None, *,
                    now=time.monotonic) -> str | None:
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
    return "Starting…" if starting else None


def foreign_queue_text(total: int | None) -> str | None:
    if not total:
        return None
    return (f"{total} job{'' if total == 1 else 's'} from another app "
            f"{'is' if total == 1 else 'are'} queued on ComfyUI")
