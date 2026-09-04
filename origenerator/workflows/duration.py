"""A video's length in seconds, on the frame grid its model can render."""

from origenerator.workflows.base import ParamDef


def _origin(pd: ParamDef) -> tuple[float, float]:
    """Where ``pd``'s grid starts counting, and how far apart its steps are.

    Not the minimum: 4k+1 frames start at 1 even though 5 is the fewest the
    model renders, and whole multiples of the native frame rate start at 0 even
    though 16 is the slowest offered. Counting from the minimum instead would
    put a value exactly between two steps on the wrong one — 24 fps is 1.5
    native rates, and the answer has to be the same one
    :func:`~origenerator.workflows.frame_rate.playback_rate` gives the graph.
    """
    step = pd.step or 1
    return (pd.min_val or 0) % step, step


def _nearest_on_grid(value: float, pd: ParamDef) -> float:
    origin, step = _origin(pd)
    return origin + max(0, round((value - origin) / step)) * step


def _last_on_grid(pd: ParamDef) -> float | None:
    if pd.max_val is None:
        return None
    origin, step = _origin(pd)
    return origin + (pd.max_val - origin) // step * step


def on_grid(value: float, pd: ParamDef) -> float:
    """``value`` on the nearest step of the grid ``pd`` spells out, and never
    past its last step.

    Every grid here is something the model can actually take: the WAN models
    render 4k+1 frames (min 5, step 4) and, since the frames between their
    frames are synthesized a whole number at a time, play at whole multiples of
    their native rate (min 16, step 16). A value between two steps has to land
    on one of them — a field that passed it through would be showing a setting
    the graph then rounded out of sight — and one outside the range lands on the
    nearest step inside it.
    """
    snapped = _nearest_on_grid(value, pd)
    last = _last_on_grid(pd)
    if last is not None:
        snapped = min(snapped, last)
    return max(snapped, pd.min_val) if pd.min_val is not None else snapped


def frames_for_seconds(seconds: float, rate: float, pd: ParamDef) -> int:
    return int(on_grid(seconds * rate, pd))


def seconds_for_frames(frames: int, rate: float, pd: ParamDef) -> float:
    """The roundest number of seconds that asks for exactly ``frames``.

    Measured against the grid UNCAPPED on purpose: a clip cut short by the
    model's own limit reads back at the length it really runs, not at the longer
    one that only lands on it by being trimmed.
    """
    exact = frames / rate
    for places in range(3):
        candidate = round(exact, places)
        if _nearest_on_grid(candidate * rate, pd) == frames:
            return candidate
    return exact
