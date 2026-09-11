"""Generation-time tracking: read execution times, estimate future ones, and
count a running one down.

Pure functions with no Qt or DB dependency so the timing logic can be unit
tested directly. ComfyUI stamps every prompt's history with ``execution_start``
and ``execution_success`` events carrying millisecond timestamps; the gap
between them is the real generation time, free of queue-wait noise. Those
measured times are both what a resting estimate is drawn from and what tells a
job in flight how much of its run is left (:class:`RunTiming`).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import NamedTuple


def execution_duration_seconds(history_data: dict) -> float | None:
    """Seconds ComfyUI spent executing a prompt, from its ``/history`` entry.

    Returns ``None`` when the history lacks the start/success pair (e.g. an
    errored or still-running prompt, or an older server that omits them).
    """
    messages = history_data.get("status", {}).get("messages", [])
    start = end = None
    for event, data in messages:
        timestamp = data.get("timestamp")
        if event == "execution_start":
            start = timestamp
        elif event == "execution_success":
            end = timestamp
    if start is None or end is None:
        return None
    return (end - start) / 1000.0


def estimate_seconds(durations: list[float]) -> float | None:
    """Best single estimate of how long the next run will take.

    The median shrugs off the occasional outlier (a run that fought another
    process for the GPU) that a mean would let skew the figure. ``None`` when
    there's no history to estimate from.
    """
    if not durations:
        return None
    return statistics.median(durations)


def average_seconds(durations: list[float]) -> float | None:
    """The mean generation time, or ``None`` when there's nothing to average."""
    if not durations:
        return None
    return statistics.fmean(durations)


def clock_duration(seconds: float) -> str:
    """A ``m:ss`` (or ``h:mm:ss``) reading of a count the user is watching move.

    The opposite call from :func:`_coarse_duration`, and for the opposite job: a
    resting estimate rounds to one unit so it claims no precision it hasn't got,
    while a live count has to visibly advance, so the seconds stay on screen.
    """
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# How much of a run's sampling has to be done before its own pace is worth
# extrapolating from. The opening steps carry the model load — a 14B checkpoint
# coming off disk — so a rate measured across one or two of them predicts a run
# several times longer than the real one.
_PACE_MIN_FRACTION = 0.25
_PACE_MIN_STEPS = 2


class RunProgress(NamedTuple):
    """How far through its sampling a run has got.

    A pair that says which half is which. Built the other way round, a bare
    ``(total, done)`` gave a plausible wrong percentage rather than an error,
    and the shape was taken apart by index in four separate places.
    """

    done: int
    total: int

    @classmethod
    def of(cls, progress):
        """*progress* as a reading, or ``None`` for a run reporting none — an
        ordinary case: a job ComfyUI has not started, or a workflow whose nodes
        report no step counts."""
        if not progress:
            return None
        return progress if isinstance(progress, cls) else cls(*progress)

    @property
    def percent_label(self) -> str:
        """How far through, as a whole percent — empty for a run whose step
        count is nought, so the caller joins what it has rather than showing a
        0% that never moved."""
        if self.total <= 0:
            return ""
        return f"{int(self.done * 100 / self.total)}%"


@dataclass(frozen=True)
class RunTiming:
    """What is known about a generation while it runs: how long it has been
    going, how far through its sampling it is, and how long its workflow usually
    takes.

    One reading rather than three loose parameters. The three used to travel
    together in the same order through four functions, each handing them to the
    next, and every reader took the middle one apart by index.
    """

    elapsed: float | None
    progress: RunProgress | None
    typical: float | None

    def __post_init__(self):
        object.__setattr__(self, "progress", RunProgress.of(self.progress))

    def _pace_projection(self):
        """How long this run is on course to take, at the pace it has been going.

        The whole run rather than the part left, so it can be weighed against the
        workflow's typical time, which is also a whole run. ``None`` while it's too
        early for the pace to mean anything.
        """
        if self.progress is None or not self.elapsed or self.elapsed <= 0:
            return None
        done, total = self.progress
        if total <= 0 or done <= 0:
            return None
        if done < max(_PACE_MIN_STEPS, total * _PACE_MIN_FRACTION):
            return None
        return self.elapsed * total / done

    def remaining_seconds(self):
        """How much longer this run has to go, from the two readings.

        The workflow's typical time is a weak prior: it is the median of that
        workflow's last ten runs whatever length, resolution and step count each was
        asked for, and those differ by a factor of ten. So it opens the estimate,
        while the run is too new to have a pace worth reading, and then hands over to
        the run's own pace in proportion to how much of the run has actually gone by.
        A prior that never hands over is what left a five-and-a-half minute run
        claiming four minutes still to come as it finished.

        A run that has already outlasted the typical time takes it out of the blend
        altogether rather than blending against a number it has disproved: past there
        the prior can only drag the estimate below what the run says about itself,
        which is the one thing still worth believing.

        ``0.0`` once the run's own pace says there is nothing left — it is over its
        time, or into a tail too short to report steps for, which is worth saying.
        ``None`` where there is nothing to go on, and that includes a run that has
        outlived its prior without yet having a pace of its own: the prior is spent,
        so it can't say how much longer, and saying "finishing" on its behalf is a
        claim about the run that nothing has measured. A run several times its
        workflow's median spent the whole middle of itself claiming to be finishing
        that way. Nothing said is what the caller shows as nothing at all.
        """
        if self.elapsed is None:
            return None
        pace = self._pace_projection()
        if pace is None:
            if self.typical is None:
                return None
            remaining = self.typical - self.elapsed
            return remaining if remaining >= 1 else None
        if self.typical is None or self.elapsed >= self.typical:
            return max(pace - self.elapsed, 0.0)
        done, total = self.progress
        settled = min(1.0, done / total)
        projected = settled * pace + (1.0 - settled) * self.typical
        return max(projected - self.elapsed, 0.0)

    def remaining_label(self) -> str:
        """The countdown on its own: ``"~4:10 left"``, or ``"finishing"`` for a run
        with nothing left to count.

        Empty when there is nothing to count down from — a job that hasn't started,
        or a first run of a workflow too early to have a pace worth reading.
        """
        remaining = self.remaining_seconds()
        if remaining is None:
            return ""
        return "finishing" if remaining < 1 else f"~{clock_duration(remaining)} left"

    def time_label(self) -> str:
        """The running bar's live line: ``"1:23 elapsed · ~4:10 left"``.

        Empty for a job that hasn't started, so a queued one shows nothing
        rather than a zero that reads as stuck.
        """
        if self.elapsed is None:
            return ""
        label = f"{clock_duration(self.elapsed)} elapsed"
        remaining = self.remaining_label()
        return f"{label} · {remaining}" if remaining else label

    def status_label(self, *, step: str = "", compact: bool = False) -> str:
        """The one line every surface writes across a running job's bar:
        ``"High noise · 45% · 1:23 elapsed · ~4:10 left"``.

        One wording, shared by the lower strip's queue, the shelf's in-flight cards
        and a folder's re-roll tile, so the same run reads the same wherever it is
        being watched — three surfaces used to each say a different half of it in
        different words.

        ``step`` is what the app is doing right now
        (:func:`origenerator.progress.stage_names`), and it leads because it is the
        one part of the line that says what is *happening* rather than how far along
        or how long: models coming off disk, a prompt being read, which of a video's
        three sampler passes is running, the frames being written out. Before it, a
        run said nothing whatever for its first minute and more. It leads for a
        second reason too — a caption too wide for its bar scrolls from the right,
        so whatever matters most is what is on screen first. Empty until ComfyUI has
        named a node, which for a queued job is the whole of its wait.

        ``compact`` is that line in a gallery tile's width, which is a third of the
        strip's: it drops the elapsed count and keeps the readings that answer what
        and how much longer — ``"High noise · 45% · ~4:10 left"``. The full line is a
        good half wider than a 180px tile at the app's own font, so a tile carrying it
        would elide the countdown away on exactly the long runs worth counting down.

        Whichever readings are unknown drop out, down to nothing at all for a job
        that has neither started nor reported a step.
        """
        clock = self.remaining_label() if compact else self.time_label()
        percent = self.progress.percent_label if self.progress is not None else ""
        return " · ".join(part for part in (step, percent, clock) if part)


def _coarse_duration(seconds: float) -> str:
    """A single-unit rounding for estimates, so they don't imply false precision."""
    if seconds < 60:
        return f"{round(seconds)} sec"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    hours, remainder = divmod(round(seconds), 3600)
    minutes = round(remainder / 60)
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return f"{hours} hr {minutes} min" if minutes else f"{hours} hr"


def queue_estimate_label(seconds: float | None) -> str:
    """What a job still waiting in the line is expected to cost, in a row's width.

    Coarse on purpose, like every resting estimate here: the figure under it is
    the median of that workflow's recent runs whatever length and resolution each
    was asked for, so "~2 min" claims exactly as much as it can back up. ``"~?"``
    when the workflow has never been timed — a first run has to happen before
    anything can be said about the next one, and a made-up number in that slot is
    worse than an admitted blank.
    """
    if seconds is None:
        return "~?"
    return f"~{_coarse_duration(seconds)}"


def estimate_label(durations: list[float]) -> str:
    """One-line estimate for the UI: ``"~12 min (based on 3 runs)"``.

    Falls back to a plain "no data" message when there's nothing to go on, so
    the caller can show the result verbatim.
    """
    estimate = estimate_seconds(durations)
    if estimate is None:
        return "No timing data yet"
    return f"~{_coarse_duration(estimate)} (based on {_runs(len(durations))})"


def average_label(durations: list[float]) -> str:
    """Folder-wide average for the UI: ``"~12 min (across 3 runs)"``.

    Returns ``""`` when nothing in the folder is timed, so the caller can hide
    the line entirely rather than show a placeholder.
    """
    average = average_seconds(durations)
    if average is None:
        return ""
    return f"~{_coarse_duration(average)} (across {_runs(len(durations))})"


def _runs(count: int) -> str:
    return f"{count} run" if count == 1 else f"{count} runs"
