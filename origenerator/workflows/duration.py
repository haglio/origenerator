from __future__ import annotations

from origenerator.workflows.base import ParamDef, chained_to


def _origin(pd: ParamDef) -> tuple[float, float]:
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
    snapped = _nearest_on_grid(value, pd)
    last = _last_on_grid(pd)
    if last is not None:
        snapped = min(snapped, last)
    return max(snapped, pd.min_val) if pd.min_val is not None else snapped


def frames_for_seconds(seconds: float, rate: float, pd: ParamDef) -> int:
    return int(on_grid(seconds * rate, pd))


def seconds_for_frames(frames: int, rate: float, pd: ParamDef) -> float:
    exact = frames / rate
    for places in range(3):
        candidate = round(exact, places)
        if _nearest_on_grid(candidate * rate, pd) == frames:
            return candidate
    return exact


def lasting(params: dict, workflow, seconds: float) -> dict:
    pd = next(pd for pd in workflow.param_definitions() if pd.key == "frame_count")
    frames = frames_for_seconds(seconds, pd.shown_in_seconds_at, pd)
    if "scene_frames" not in params:
        return {**params, "frame_count": frames}
    scenes = [int(count) for count in params["scene_frames"] or [frames]]
    return {**params, "frame_count": frames,
            "scene_frames": chained_to(frames, scenes, int(pd.min_val))}
