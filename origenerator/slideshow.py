"""The ordering and pacing behind the gallery's fullscreen slideshow.

Pure, Qt-free playlist state: which of a folder's media is on screen, how to
step through them (with wrap), whether it's paused, and how long to dwell on an
image before advancing. Videos aren't dwell-timed — they play once and the view
advances when they end — so :meth:`dwell_ms` returns ``None`` for them. Keeping
this a plain object (like ``job_queue.pending_etas``) lets the advance policy be
unit-tested without a window or a clock.
"""


class SlideshowPlaylist:
    MIN_DWELL_MS = 1000
    MAX_DWELL_MS = 20000

    def __init__(self, items, *, image_dwell_ms=4000):
        self._items = list(items)  # each an (path, media_type) pair
        self._i = 0
        self._paused = False
        self._image_dwell_ms = image_dwell_ms

    def is_empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)

    def current(self):
        return self._items[self._i] if self._items else None

    @property
    def index(self) -> int:
        """The current item's 0-based position (0 for an empty playlist)."""
        return self._i

    def advance(self):
        """Step to the next item, wrapping past the end. Returns the new current."""
        if self._items:
            self._i = (self._i + 1) % len(self._items)
        return self.current()

    def back(self):
        """Step to the previous item, wrapping before the start."""
        if self._items:
            self._i = (self._i - 1) % len(self._items)
        return self.current()

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    def current_is_video(self) -> bool:
        item = self.current()
        return item is not None and item[1] == "video"

    def dwell_ms(self):
        """Milliseconds to wait before auto-advancing the current item, or ``None``
        when it shouldn't be timer-advanced: an empty or paused playlist, or a
        video — which advances when it ends, not on a clock."""
        if self._paused or self.current() is None or self.current_is_video():
            return None
        return self._image_dwell_ms

    @property
    def image_dwell_ms(self) -> int:
        return self._image_dwell_ms

    def adjust_dwell(self, delta_ms: int) -> int:
        """Nudge the image dwell time by ``delta_ms``, clamped to the bounds."""
        self._image_dwell_ms = max(
            self.MIN_DWELL_MS, min(self.MAX_DWELL_MS, self._image_dwell_ms + delta_ms)
        )
        return self._image_dwell_ms
