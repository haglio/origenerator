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
