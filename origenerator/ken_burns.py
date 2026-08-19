"""The slow push into a still while it holds the screen.

A slideshow of stills is a wall of stills: each one arrives, sits perfectly
motionless, and is replaced. The same set with the camera creeping into every
picture reads as footage instead, which is the whole of the Ken Burns move —
here without the pan, so a picture only ever ends :data:`ZOOM_SPAN` deeper
inside itself than it started.

How FAR the move goes is fixed; how FAST it goes is the pace's. A slide left up
for twelve seconds creeps at a third of the speed of one up for four, rather
than travelling three times as far — travelling further would end on a crop of
the picture rather than on the picture. So the move is taken a tick at a time
against the dwell as it stands right now (:func:`progress_step`), which is also
what lets the app-wide pace be turned up under a running show and be obeyed
from that moment rather than at the next slide.

**Nothing here rounds.** A move this slow advances well under a pixel per tick,
so a window rounded to whole pixels does not creep — it sits still and then
jumps, several times a second, in whichever direction rounding happened to
break. On a picture that is otherwise perfectly still that reads as the frame
twitching rather than as a camera moving, which is worse than no move at all.
:func:`crop_box` therefore hands back a real-valued window for the painter to
sample between pixels, and the pane draws every frame of one slide at ONE fixed
size so the picture cannot re-center itself under the same rounding.

Kept Qt-free, like :mod:`origenerator.slideshow`, so the arithmetic tests
without a window or a clock.
"""

# How much closer the picture is by the time its dwell runs out. Small on
# purpose — the move has to be something you notice having happened rather than
# something you watch happening, and at the standard four-second dwell this is
# already a tenth of the frame in four seconds.
ZOOM_SPAN = 1.10

# How often the push is stepped. Thirty a second: each frame is one near-1:1
# blit of a picture prepared once for the slide, so the cost of a smooth
# cadence is small, and the eye reads anything slower as steps.
TICK_MS = 33


def progress_step(tick_ms: int, dwell_ms: int) -> float:
    """How much of the move one *tick_ms* tick makes on a *dwell_ms* slide.

    Nought for a slide with no dwell at all — a pace of nought holds one picture
    until an arrow moves it, and a picture being held is not a shot being made.
    """
    if dwell_ms <= 0:
        return 0.0
    return tick_ms / dwell_ms


def zoom_at(progress: float, span: float = ZOOM_SPAN) -> float:
    """The zoom factor *progress* of the way through the move.

    Clamped at both ends: a slide that outlives its dwell — one locked part-way
    through, or a tick that lands late — stops at the end of the move rather
    than carrying on into the picture forever.
    """
    return 1.0 + (span - 1.0) * max(0.0, min(1.0, progress))


def crop_box(width: float, height: float,
             zoom: float) -> tuple[float, float, float, float]:
    """The centered ``(x, y, w, h)`` of a *width* x *height* picture that fills
    the frame at *zoom*, in real numbers rather than whole pixels.

    Real numbers because the alternative is visibly worse: a tenth of the frame
    spread over four seconds moves each edge by a fraction of a pixel per tick,
    so a window snapped to integers holds still for several ticks and then steps
    a whole pixel — and the two axes step at different moments, which is what
    turns a creep into a twitch. Handed to a painter as-is, the sampling grid
    slides smoothly between source pixels and the motion is continuous.

    The window is what moves, not the frame the picture is drawn in: 1/*zoom* of
    each side of the same picture. The frame stays the size the whole picture
    was drawn at, so the media keeps exactly the rect the neighbor stills and
    the HUD map were placed against — and, just as importantly, cannot be
    re-centered by a frame that grew or shrank by a pixel.
    """
    if zoom <= 1.0:
        return (0.0, 0.0, float(width), float(height))
    kept_w = width / zoom
    kept_h = height / zoom
    return ((width - kept_w) / 2, (height - kept_h) / 2, kept_w, kept_h)
