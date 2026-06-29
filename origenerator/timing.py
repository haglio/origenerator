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


def format_duration(seconds: float) -> str:
    """Render a duration as a compact human string, e.g. ``"15 min 5 sec"``.

    Shows the two largest non-zero units (hr+min, or min+sec), dropping a
    trailing zero unit so whole values read cleanly (``"2 min"``, ``"1 hr"``).
    """
    total = round(seconds)
    if total < 60:
        return f"{total} sec"
    if total < 3600:
        minutes, secs = divmod(total, 60)
        return f"{minutes} min {secs} sec" if secs else f"{minutes} min"
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"{hours} hr {minutes} min" if minutes else f"{hours} hr"


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
    runs = "run" if len(durations) == 1 else "runs"
    return f"~{_coarse_duration(estimate)} (based on {len(durations)} {runs})"
