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

Kept Qt-free, like :mod:`origenerator.slideshow`, so the arithmetic tests
without a window or a clock. The widget that owns the pixels does the one Qt
thing there is to do: draw :func:`crop_box` of what it is holding.
"""

# How much closer the picture is by the time its dwell runs out. Small on
# purpose — the move has to be something you notice having happened rather than
# something you watch happening, and at the standard four-second dwell this is
# already a tenth of the frame in four seconds.
ZOOM_SPAN = 1.10

# How often the push is stepped. Twenty a second: the move covers a tenth of the
# frame across a whole dwell, so even the shortest pace advances it by a pixel
# or two per tick, and a rescale of the picture on screen is not free.
TICK_MS = 50


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


def crop_box(width: int, height: int, zoom: float) -> tuple[int, int, int, int]:
    """The centered ``(x, y, w, h)`` of a *width* x *height* picture that fills
    the frame at *zoom*.

    The crop is what moves, not the frame: 1/*zoom* of each side, scaled back up
    to the size the whole picture was drawn at. Growing the drawn picture
    instead would be the same move to look at and a different thing to build
    against — the neighbor stills and the HUD are placed against the rect the
    media occupies, and that rect has to stay where it is while the push runs.
    """
    if zoom <= 1.0:
        return (0, 0, width, height)
    kept_w = max(1, round(width / zoom))
    kept_h = max(1, round(height / zoom))
    return ((width - kept_w) // 2, (height - kept_h) // 2, kept_w, kept_h)
