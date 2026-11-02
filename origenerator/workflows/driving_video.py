from __future__ import annotations

from origenerator.workflows.frame_rate import NATIVE_FPS


def start_frame(start_seconds: float) -> int:
    return max(0, round(start_seconds * NATIVE_FPS))

SHORTEST_VIDEO_FRAMES = 5


def frames_within(frame_count: int, *, video_seconds: float | None, start: int) -> int:
    if video_seconds is None:
        return frame_count
    available = int(video_seconds * NATIVE_FPS) - start
    if available >= frame_count:
        return frame_count
    # ComfyUI's WAN nodes take frame counts of the form 4k+1.
    return max(SHORTEST_VIDEO_FRAMES, (available - 1) // 4 * 4 + 1)


def driven_actions(actions: list[dict], *, start_ms: int, length_ms: int) -> list[dict]:
    if not actions:
        return []
    end_ms = start_ms + length_ms
    inside = [{"at": action["at"] - start_ms, "pos": action["pos"]}
              for action in actions if start_ms < action["at"] < end_ms]
    return [{"at": 0, "pos": _position_at(actions, start_ms)},
            *inside,
            {"at": length_ms, "pos": _position_at(actions, end_ms)}]


def _position_at(actions: list[dict], at_ms: int) -> int:
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
