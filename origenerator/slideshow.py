"""The ordering and pacing behind the fullscreen slideshow.

Pure, Qt-free playlist state: what's on screen, how to step through it, and how
long to dwell on an image before advancing. :class:`SlideshowPlaylist` plays a
set in a random order, reshuffled each pass, with the shuffle injectable so the
order is deterministic under test; a lock holds one item against the advance,
answering Fun Time's padlock. The set grows as generations land in what the show
is playing (:meth:`SlideshowPlaylist.add`) — a folder that is auto-generating is
the case that asks for it. Videos aren't dwell-timed: they play once and the
view advances when they end, so ``dwell_ms`` returns ``None`` for them. Keeping
this a plain, Qt-free object lets the policy be unit-tested without a window or
a clock.
"""

import random

# How long an image holds the screen unless something says otherwise.
# Genau's console shows this as its clip-seconds pace and sets it from
# there, so the number it opens at has to be the one the slideshow uses.
DEFAULT_IMAGE_DWELL_MS = 4000


def _upgraded(item: tuple, path, media_type=None, still=None) -> tuple:
    """``item`` pointing at a better version of itself.

    The new file, its media type (kept as it was when the caller names none),
    the same id — an enhancement is the same item, not a new one — and the new
    thumbnail when one came with it: the still is what the item is drawn as
    while it's a neighbor, and the one it arrived with is of the version this
    swap just retired.
    """
    fields = list(item)
    fields[0] = path
    if media_type is not None:
        fields[1] = media_type
    if still is not None:
        fields += [None] * (4 - len(fields))
        fields[3] = still
    return tuple(fields)


class SlideshowPlaylist:
    def __init__(self, items, *, image_dwell_ms=DEFAULT_IMAGE_DWELL_MS,
                 shuffle=random.shuffle):
        self._items = list(items)  # each an (path, media_type) pair
        self._shuffle = shuffle
        self._order = list(range(len(self._items)))
        self._shuffle(self._order)  # play in a random order
        self._pos = 0
        self._locked = False
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

    def add(self, item) -> bool:
        """Take in an item that has landed since the show opened, and queue it to
        come up next. Returns whether it was new here.

        Next rather than at the end of the pass: this is how a generation made
        while the show runs reaches the screen, and watching a folder fill is
        watching for the new one — parked behind a hundred others it would be an
        hour away. The rest of the pass then carries on where it left off.
        """
        prompt_id = item[2] if len(item) > 2 else None
        if prompt_id is not None and any(len(held) > 2 and held[2] == prompt_id
                                         for held in self._items):
            return False
        self._items.append(item)
        self._order.insert(self._pos + 1, len(self._items) - 1)
        return True

    def remove_current(self):
        """Drop the current item; the item that followed it becomes current."""
        if not self._items:
            return
        removed = self._order[self._pos]
        del self._items[removed]
        self._order = [i - 1 if i > removed else i for i in self._order if i != removed]
        if not self._order or self._pos >= len(self._order):
            self._pos = 0

    def replace_item(self, prompt_id, path, media_type=None, still=None) -> bool:
        """Point the item with this id at a better version of itself — an
        enhancement of it that has landed. Returns whether it was here at all.

        Matched by id wherever the item sits, not only while it is the one on
        screen. An enhancement asked for from a slideshow lands minutes later, by
        which time the show has long paged on, so an arrival dropped for being
        late would leave the pre-enhance file playing every pass for the rest of
        the session.
        """
        replaced = False
        for index, item in enumerate(self._items):
            if len(item) > 2 and item[2] == prompt_id:
                self._items[index] = _upgraded(item, path, media_type, still)
                replaced = True
        return replaced

    @property
    def image_dwell_ms(self) -> int:
        """How long an image holds the screen. Settable, because Genau's console
        carries the pair that sets it — the same clip-seconds pace Genau leaves
        its own clips up for."""
        return self._image_dwell_ms

    @image_dwell_ms.setter
    def image_dwell_ms(self, value: int) -> None:
        self._image_dwell_ms = max(0, int(value))

    # --- lock: hold this one against the advance ---------------------------

    @property
    def locked(self) -> bool:
        """Whether the item on screen is being held against the advance.

        "Lock" is what this hold is called everywhere else — the auto-generate
        rotation, Fun Time's console — so it is what it is called here.
        """
        return self._locked

    def toggle_lock(self) -> bool:
        self._locked = not self._locked
        return self._locked

    def unlock(self) -> None:
        self._locked = False

    def current_is_video(self) -> bool:
        item = self.current()
        return item is not None and item[1] == "video"

    def dwell_ms(self):
        """Milliseconds to wait before auto-advancing the current item, or ``None``
        when it shouldn't be timer-advanced: an empty or locked playlist, or a
        video — which advances when it ends, not on a clock."""
        if self._locked or self.current() is None or self.current_is_video():
            return None
        return self._image_dwell_ms

