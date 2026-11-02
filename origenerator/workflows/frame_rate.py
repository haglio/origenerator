from __future__ import annotations

# ComfyUI's WAN 2.1 and 2.2 were trained at 16 fps: 81 frames is five seconds of motion
NATIVE_FPS = 16.0

MAX_PLAYBACK_FPS = 112.0
_MAX_MULTIPLIER = int(MAX_PLAYBACK_FPS / NATIVE_FPS)


def rate_multiplier(frame_rate: float) -> int:
    return min(_MAX_MULTIPLIER, max(1, round(frame_rate / NATIVE_FPS)))


def playback_rate(frame_rate: float) -> float:
    return NATIVE_FPS * rate_multiplier(frame_rate)

