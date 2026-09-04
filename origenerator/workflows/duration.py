"""A video's length in seconds, on the frame grid its model can render."""

from origenerator.workflows.base import ParamDef


def _nearest_on_grid(value: float, pd: ParamDef) -> int:
    """Nearest step of the grid ``pd`` spells out: the WAN models take 4k+1
    frames, so min 5 / step 4."""
    minimum = int(pd.min_val or 0)
    step = int(pd.step or 1)
    return minimum + max(0, round((value - minimum) / step)) * step


def _last_on_grid(pd: ParamDef) -> int | None:
    if pd.max_val is None:
        return None
    minimum = int(pd.min_val or 0)
    step = int(pd.step or 1)
    return minimum + (int(pd.max_val) - minimum) // step * step


def frames_for_seconds(seconds: float, frame_rate: float, pd: ParamDef) -> int:
    frames = _nearest_on_grid(seconds * frame_rate, pd)
    last = _last_on_grid(pd)
    return frames if last is None else min(frames, last)


def seconds_for_frames(frames: int, frame_rate: float, pd: ParamDef) -> float:
    exact = frames / frame_rate
    for places in range(3):
        candidate = round(exact, places)
        if _nearest_on_grid(candidate * frame_rate, pd) == frames:
            return candidate
    return exact
