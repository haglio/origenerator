"""The ordering and pacing behind the fullscreen slideshows.

Pure, Qt-free playlist state: what's on screen, how to step through it, and how
long to dwell on an image before advancing. Two policies live here.
:class:`SlideshowPlaylist` backs the gallery slideshow: a fixed set played in a
random order, reshuffled each pass, with the shuffle injectable so the order is
deterministic under test. :class:`AutoGeneratePlaylist` backs the auto-generate
slideshow: a chronological rotation that grows as the loop lands each item, with
a trailing "live" slot for the generation in flight and a lock that holds one
item against the advance. In both, videos aren't dwell-timed: they play once and
the view advances when they end, so ``dwell_ms`` returns ``None`` for them.
Keeping these plain, Qt-free objects lets the policies be unit-tested without a
window or a clock.
"""

import random


class SlideshowPlaylist:
    def __init__(self, items, *, image_dwell_ms=4000, shuffle=random.shuffle):
        self._items = list(items)  # each an (path, media_type) pair
        self._shuffle = shuffle
        self._order = list(range(len(self._items)))
        self._shuffle(self._order)  # play in a random order
        self._pos = 0
        self._paused = False
        self._image_dwell_ms = image_dwell_ms

    def is_empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)

    def current(self):
        return self._items[self._order[self._pos]] if self._items else None

    @property
    def index(self) -> int:
        """The current item's position in the running pass (0 when empty)."""
        return self._pos

    @property
    def order(self) -> list:
        """The shuffled play order (item indices) — exposed for diagnostics."""
        return list(self._order)

    def peek(self, offset: int):
        """The item ``offset`` steps away in the running pass, wrapping — what the
        view draws either side of the one on screen. ``None`` when empty."""
        if not self._items:
            return None
        pos = (self._pos + offset) % len(self._items)
        return self._items[self._order[pos]]

    def advance(self):
        """Step to the next item; at the end, reshuffle and start a fresh pass."""
        if self._items:
            self._pos += 1
            if self._pos >= len(self._items):
                self._shuffle(self._order)  # a new random order each pass
                self._pos = 0
        return self.current()

    def back(self):
        """Step to the previous item in the current pass, wrapping to its end."""
        if self._items:
            self._pos = (self._pos - 1) % len(self._items)
        return self.current()

    def remove_current(self):
        """Drop the current item; the item that followed it becomes current."""
        if not self._items:
            return
        removed = self._order[self._pos]
        del self._items[removed]
        self._order = [i - 1 if i > removed else i for i in self._order if i != removed]
        if not self._order or self._pos >= len(self._order):
            self._pos = 0

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


# What :meth:`AutoGeneratePlaylist.current` returns while the rotation is on its
# live slot — the generation still streaming, which has no file behind it yet.
LIVE = object()


class AutoGeneratePlaylist:
    """The auto-generate slideshow's rotation.

    Every item the loop has finished so far, oldest first, plus one trailing
    "live" slot standing for the generation currently streaming — so the
    rotation reads as the folder's history ending at the thing being made.
    Finished items arrive over time via :meth:`add_finished`; the live slot
    appears while the loop runs (:meth:`set_live`). ``lock`` holds the current
    item against the auto-advance without stopping manual stepping.
    """

    def __init__(self, *, image_dwell_ms=4000):
        # (path, media_type, prompt_id, still), oldest first
        self._items: list[tuple] = []
        self._live = True  # the view opens on a running loop, so a slot exists
        self._pos = 0
        self._locked = False
        self._image_dwell_ms = image_dwell_ms

    # --- what's on screen --------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._items) + (1 if self._live else 0)

    @property
    def index(self) -> int:
        return self._pos

    @property
    def live(self) -> bool:
        return self._live

    def on_live(self) -> bool:
        """Whether the rotation is sitting on the live slot."""
        return self._live and self._pos == len(self._items)

    def current(self):
        """The finished item on screen, ``LIVE`` on the live slot, or ``None``
        when the rotation is empty (no items and no loop running)."""
        if self.count == 0:
            return None
        return LIVE if self.on_live() else self._items[self._pos]

    # --- how the rotation grows and shrinks --------------------------------

    def add_finished(self, path, media_type: str, prompt_id: str, *,
                     still=None, stay_live: bool = False) -> None:
        """Append a finished item just before the live slot.

        ``still`` is the item's stored thumbnail, carried so the view can draw it
        small as a neighbor without opening the file itself (a video has no other
        still to show).

        With ``stay_live`` (seeding an opening view), a rotation sitting on the
        live slot follows it — the view keeps showing the in-flight generation.
        Without it (the on-screen generation just completed), the cursor stays
        put and now names the freshly finished item, so the low-res live frame
        hands over to the finished file.
        """
        was_on_live = self.on_live()
        self._items.append((path, media_type, prompt_id, still))
        if was_on_live and stay_live:
            self._pos = len(self._items)

    def set_live(self, present: bool) -> None:
        """Add or drop the live slot (the loop started/ended). Dropping it while
        it's on screen falls back to the newest finished item."""
        if self._live == present:
            return
        self._live = present
        if not present and self._pos >= len(self._items):
            self._pos = max(0, len(self._items) - 1)

    def remove_current(self) -> None:
        """Drop the finished item on screen; the item after it becomes current
        (the live slot, past the end). A no-op on the live slot — the in-flight
        generation is cancelled, not removed."""
        if self.current() is None or self.on_live():
            return
        del self._items[self._pos]
        if self._pos >= self.count and self.count:
            self._pos = 0

    # --- stepping ----------------------------------------------------------

    def peek(self, offset: int):
        """The slot ``offset`` steps away, wrapping — what the view draws either
        side of the one on screen. ``LIVE`` for the live slot, ``None`` when the
        rotation is empty."""
        if self.count == 0:
            return None
        pos = (self._pos + offset) % self.count
        return LIVE if (self._live and pos == len(self._items)) else self._items[pos]

    def advance(self):
        if self.count:
            self._pos = (self._pos + 1) % self.count
        return self.current()

    def back(self):
        if self.count:
            self._pos = (self._pos - 1) % self.count
        return self.current()

    # --- lock: hold this one against the advance ---------------------------

    @property
    def locked(self) -> bool:
        return self._locked

    def toggle_lock(self) -> bool:
        self._locked = not self._locked
        return self._locked

    def unlock(self) -> None:
        self._locked = False

    # --- pacing ------------------------------------------------------------

    def dwell_ms(self):
        """Milliseconds before auto-advancing, or ``None`` when nothing should:
        an empty or locked rotation, or a finished video — which advances when
        it ends. The live slot dwells like an image (its frames are stills)."""
        current = self.current()
        if self._locked or current is None:
            return None
        if current is not LIVE and current[1] == "video":
            return None
        return self._image_dwell_ms
