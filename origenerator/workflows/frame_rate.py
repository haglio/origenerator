"""The rate a video model paces motion at, and the rate a clip is played at.

A model authors motion frame by frame at its native rate, so a clip's length
is always generated there and more frames buy more action, not smoother
action; the frames between them are synthesized after decode (RIFE, in
:meth:`~origenerator.workflows.base.WorkflowTemplate.interpolation_nodes`), a
whole number per gap, so the rates a file can have are the whole multiples of
the native one. Written at any other rate the clip plays at the wrong speed.
"""
from __future__ import annotations

#: Frames per second WAN 2.1 and 2.2 pace their motion at; a model paced
#: otherwise (MiniMax H3, at 24) says so on its workflow.
NATIVE_FPS = 16.0

MAX_PLAYBACK_FPS = 112.0


def rate_multiplier(frame_rate: float, native_fps: float = NATIVE_FPS) -> int:
    """How many frames the interpolator makes out of each generated one to reach
    ``frame_rate``; 1 is the graph's bypass, the decoded frames saved untouched."""
    return min(int(MAX_PLAYBACK_FPS / native_fps), max(1, round(frame_rate / native_fps)))


def playback_rate(frame_rate: float, native_fps: float = NATIVE_FPS) -> float:
    """The rate the file is really written at: the whole multiple of
    ``native_fps`` nearest ``frame_rate``, so its rate and its frames always
    come from one number and nothing typed can make a clip play at the wrong speed."""
    return native_fps * rate_multiplier(frame_rate, native_fps)

