"""Qt Quick draws the slideshow's push on a thread of its own only under the
threaded render loop, and reads which loop to use once, as it first starts."""
from __future__ import annotations


def request_threaded_render_loop(environ) -> None:
    environ.setdefault("QSG_RENDER_LOOP", "threaded")
