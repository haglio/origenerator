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

A dwell of zero means never: the show holds whatever is on screen until an arrow
moves it. That is the shape a double-clicked picture opens in — one show, opened
at a pace of nought, rather than a second full-screen viewer with its own keys.

A third hold — :attr:`SlideshowPlaylist.paused` — is the show's own rather than
the user's or the pace's: speaking a request stops the advance for as long as
the sentence takes, and releases it without disturbing either of the others.

Closing a show is rarely being done with it, so where one was is kept:
:class:`ShowState` says it and :meth:`SlideshowPlaylist.resume` lays a fresh
pass back out that way. It is said in generation ids rather than in places,
because the set the next show plays is not the one this one held — items landed
while it was away, and anything it culled is gone.
"""

import random
from dataclasses import dataclass

# How long an image holds the screen unless something says otherwise.
# Genau's console shows this as its clip-seconds pace and sets it from
# there, so the number it opens at has to be the one the slideshow uses.
DEFAULT_IMAGE_DWELL_MS = 4000


@dataclass(frozen=True)
class ShowState:
    """Where a show was when it closed, for whichever one opens next.

    ``order`` is the pass it was playing and ``current`` the slide it stood on,
    both as generation ids. The rest is what that slide was doing — held against
    the advance, showing which of its versions — and ``enhance_on_hold`` the
    switch the show was set to.
    """

    order: tuple = ()
    current: str | None = None
    locked: bool = False
    level_index: int = 0
    enhance_on_hold: bool = True


def in_order(order: list) -> None:
    """A shuffle that doesn't: play the set in the order it was handed over.

    What a double-clicked picture opens in — its folder as the browser lists it,
    starting where the double-click landed — against the random pass a folder
    played from the toolbar gets.
    """


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
                 shuffle=random.shuffle, start=None):
        self._items = list(items)  # each an (path, media_type) pair
        self._shuffle = shuffle
        self._order = list(range(len(self._items)))
        self._shuffle(self._order)  # play in a random order
        # The pass begins at its own front unless a particular item was asked for:
        # a double-clicked picture opens on *that* picture, which sits wherever
        # this pass's order happens to have put it.
        self._pos = (self._order.index(start)
                     if start is not None and 0 <= start < len(self._items) else 0)
        self._locked = False
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

    def in_play_order(self) -> list:
        """The items in the order this pass is playing them, rather than the order
        the set was handed over in — so a playlist built from these, in order,
        takes up where this one stopped."""
        return [self._items[index] for index in self._order]

    def order_ids(self) -> list:
        """The pass in ids rather than in places — how a closing show hands its
        order to the next one, over a set that will have moved on."""
        return [self._id_of(index) for index in self._order]

    def resume(self, order_ids, current_id) -> bool:
        """Lay the pass back out the way a closed show left it, standing on the
        slide it was showing. Returns whether that slide is still here to stand on.

        It may not be — culled while the show was away, or this is another
        folder's set entirely — and then nothing is disturbed: a pass laid out
        around an item that isn't in it would open the show on an arbitrary
        stranger, which is worse than the shuffle it already has.

        Items the remembered order doesn't name follow the ones it does, keeping
        the order the shuffle gave them. They were no part of the pass being
        picked back up, and the next pass reshuffles the lot anyway.
        """
        places = {pid: index for index, pid in
                  ((i, self._id_of(i)) for i in range(len(self._items)))
                  if pid is not None}
        if current_id not in places:
            return False
        remembered = [places[pid] for pid in order_ids if pid in places]
        held = set(remembered)
        self._order = remembered + [i for i in self._order if i not in held]
        self._pos = self._order.index(places[current_id])
        return True

    def _id_of(self, index: int):
        """The id the item at ``index`` was generated under, or ``None`` — a set
        assembled without ids (a test's) names nothing."""
        item = self._items[index]
        return item[2] if len(item) > 2 else None

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
        """How long an image holds the screen, zero meaning never move on.
        Settable, because Genau's console carries the pair that sets it — the same
        clip-seconds pace Genau leaves its own clips up for, so turning a
        double-clicked picture's nought up is what sets it going."""
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

    def set_locked(self, locked: bool) -> None:
        """Put the lock back where a closed show left it — a slide it was closed
        holding is one it reopens holding."""
        self._locked = bool(locked)

    def unlock(self) -> None:
        self._locked = False

    # --- pause: a hold the show puts on itself -----------------------------

    @property
    def paused(self) -> bool:
        """Whether something other than the user's lock is holding the slide.

        Speaking a request pauses the show: the request is *about* what is on
        screen, and a set that pages on every few seconds would hand the words
        to whatever came up next. Kept apart from the lock so releasing one
        never releases the other — a paused slide the user had locked stays
        locked when the request ends, and stepping off a slide (which drops its
        lock) doesn't quietly resume a show that is still listening.
        """
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    def holding(self) -> bool:
        """Whether anything at all is holding this slide — locked or paused."""
        return self._locked or self._paused

    def current_is_video(self) -> bool:
        item = self.current()
        return item is not None and item[1] == "video"

    def dwell_ms(self):
        """Milliseconds to wait before auto-advancing the current item, or ``None``
        when it shouldn't be timer-advanced: an empty, locked or paused playlist, a
        pace of nought (hold this one until an arrow moves it), or a video — which
        advances when it ends, not on a clock."""
        if self.holding() or self.current() is None or self.current_is_video():
            return None
        return self._image_dwell_ms or None

