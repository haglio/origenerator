"""Generation-time tracking: read execution times, estimate future ones, and
count a running one down.

Pure functions with no Qt or DB dependency so the timing logic can be unit
tested directly. ComfyUI stamps every prompt's history with ``execution_start``
and ``execution_success`` events carrying millisecond timestamps; the gap
between them is the real generation time, free of queue-wait noise. Those
measured times are both what a resting estimate is drawn from and what tells a
job in flight how much of its run is left (:func:`progress_time_label`).
"""

import statistics


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


# How much of a run's sampling has to be behind it before its own pace is worth
# extrapolating from. The opening steps carry the model load — a 14B checkpoint
# coming off disk — so a rate measured across one or two of them predicts a run
# several times longer than the real one.
_PACE_MIN_FRACTION = 0.25
_PACE_MIN_STEPS = 2


def _pace_remaining(elapsed: float, progress: tuple[int, int] | None) -> float | None:
    """Seconds left at the pace this run has been sampling at.

    ``None`` while it's too early for that pace to mean anything, and once the
    last step is done — past there the step count has nothing left to say.
    """
    if not progress or elapsed <= 0:
        return None
    done, total = progress
    if total <= 0 or done <= 0 or done >= total:
        return None
    if done < max(_PACE_MIN_STEPS, total * _PACE_MIN_FRACTION):
        return None
    return elapsed * (total - done) / done


def remaining_seconds(elapsed: float, progress: tuple[int, int] | None,
                      typical: float | None) -> float | None:
    """How much longer a running generation has to go, from two readings.

    Whichever says more is left wins. The run's own sampling pace is what catches
    a run going slower than usual, but it only measures sampling — a video job
    still has a VAE decode and an audio pass after its last step, and the step
    count knows nothing about those. The workflow's typical time covers that
    tail, so taking the larger keeps the number from sitting at zero through it.

    ``0.0`` once both readings are spent — the run is over its time, which is
    worth saying — against ``None`` when there was never anything to go on.
    """
    readings = [r for r in (
        None if typical is None else typical - elapsed,
        _pace_remaining(elapsed, progress),
    ) if r is not None]
    if not readings:
        return None
    return max(max(readings), 0.0)


def progress_time_label(elapsed: float | None, progress: tuple[int, int] | None,
                        typical: float | None) -> str:
    """The running bar's live line: ``"1:23 elapsed · ~4:10 left"``.

    ``""`` for a job that hasn't started (``elapsed`` of ``None``), so a queued
    one shows nothing rather than a zero that reads as stuck.
    """
    if elapsed is None:
        return ""
    label = f"{clock_duration(elapsed)} elapsed"
    remaining = remaining_seconds(elapsed, progress, typical)
    if remaining is None:
        return label
    if remaining < 1:
        return f"{label} · finishing"
    return f"{label} · ~{clock_duration(remaining)} left"


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
