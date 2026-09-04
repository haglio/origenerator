"""The rate the video models pace motion at, and the rate a clip is played at.

The WAN models author motion frame by frame at 16 fps: 81 frames is five
seconds of action, and asking for more frames buys *more action*, not smoother
action. So a clip's length is always generated at :data:`NATIVE_FPS` — Duration
is seconds of motion whatever rate is chosen — and the frames between those
frames are synthesized after decode (RIFE, in
:meth:`~origenerator.workflows.base.WorkflowTemplate.interpolation_nodes`).
Frame Rate then means one thing only: how smooth those seconds look.

The interpolator takes a whole-number multiplier, so the rates whose frames can
actually exist are the whole multiples of the native rate. A rate between two of
them would need a resample the graph has no node for, and encoding at it anyway
is exactly the tempo error this replaced — 121 frames of 16 fps motion written
at 24 fps plays 1.5x fast. So every rate offered is a multiple, and a typed one
lands on the nearest (:func:`playback_rate`).
"""

#: Frames per second the models pace their motion at. Both WAN 2.1 and 2.2 were
#: trained at this rate, and it is the rate every clip is generated at.
NATIVE_FPS = 16.0


def rate_multiplier(frame_rate: float) -> int:
    """How many frames the interpolator makes out of each generated one to reach
    ``frame_rate``.

    1 when the clip is played at the rate it was generated at, which is the
    graph's bypass: no interpolation node, the decoded frames saved untouched.
    """
    return max(1, round(frame_rate / NATIVE_FPS))


def playback_rate(frame_rate: float) -> float:
    """The rate the file is really written at: the whole multiple of
    :data:`NATIVE_FPS` nearest ``frame_rate``.

    The video writer reads this rather than the requested rate, so the file's
    rate and its frames always come from one number. Nothing typed into the form
    can produce a clip that plays at the wrong speed — it can only produce one
    at a nearby rate.
    """
    return NATIVE_FPS * rate_multiplier(frame_rate)

