from __future__ import annotations

# ComfyUI's WAN 2.1 and 2.2 were trained at 16 fps: 81 frames is five seconds of motion
NATIVE_FPS = 16.0

MAX_PLAYBACK_FPS = 112.0


def _most_multiples(native: float) -> int:
    return int(MAX_PLAYBACK_FPS // native)


def rate_options(native: float = NATIVE_FPS) -> list[int]:
    return [round(native * multiple) for multiple in range(1, _most_multiples(native) + 1)]


def rate_multiplier(frame_rate: float, native: float = NATIVE_FPS) -> int:
    return min(_most_multiples(native), max(1, round(frame_rate / native)))


def playback_rate(frame_rate: float, native: float = NATIVE_FPS) -> float:
    return native * rate_multiplier(frame_rate, native)


def frames_filled_in(frames_made: int, frame_rate: float, native: float = NATIVE_FPS) -> int:
    return (frames_made - 1) * rate_multiplier(frame_rate, native) + 1
