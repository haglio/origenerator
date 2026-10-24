"""The stretch of a library video a run performs, and its script cut to it."""
from __future__ import annotations

from origenerator.workflows.frame_rate import NATIVE_FPS


def start_frame(start_seconds: float) -> int:
    """The video's frames, at the models' rate, that the run skips."""
    return max(0, round(start_seconds * NATIVE_FPS))

SHORTEST_CLIP_FRAMES = 5


def frames_within(frame_count: int, *, video_seconds: float | None, start: int) -> int:
    """As much of ``frame_count`` as the video has past ``start``, on the 4k+1 grid."""
    if video_seconds is None:
        return frame_count
    available = int(video_seconds * NATIVE_FPS) - start
    if available >= frame_count:
        return frame_count
    return max(SHORTEST_CLIP_FRAMES, (available - 1) // 4 * 4 + 1)


def driven_actions(actions: list[dict], *, start_ms: int, length_ms: int) -> list[dict]:
    """The script over the stretch performed, counted from its start, with the
    device's position at either end."""
    if not actions:
        return []
    end_ms = start_ms + length_ms
    inside = [{"at": action["at"] - start_ms, "pos": action["pos"]}
              for action in actions if start_ms < action["at"] < end_ms]
    return [{"at": 0, "pos": _position_at(actions, start_ms)},
            *inside,
            {"at": length_ms, "pos": _position_at(actions, end_ms)}]


def _position_at(actions: list[dict], at_ms: int) -> int:
    """Between the actions either side of ``at_ms``, or held at the script's end."""
    before = [action for action in actions if action["at"] <= at_ms]
    after = [action for action in actions if action["at"] >= at_ms]
    if not before:
        return after[0]["pos"]
    if not after:
        return before[-1]["pos"]
    earlier, later = before[-1], after[0]
    if later["at"] == earlier["at"]:
        return earlier["pos"]
    along = (at_ms - earlier["at"]) / (later["at"] - earlier["at"])
    return round(earlier["pos"] + (later["pos"] - earlier["pos"]) * along)
