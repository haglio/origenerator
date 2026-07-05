"""Generation-time tracking: read execution times and estimate future ones.

Pure functions with no Qt or DB dependency so the timing logic can be unit
tested directly. ComfyUI stamps every prompt's history with ``execution_start``
and ``execution_success`` events carrying millisecond timestamps; the gap
between them is the real generation time, free of queue-wait noise.
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
