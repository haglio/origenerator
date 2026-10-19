"""The ordering under the fullscreen slideshow.

Pure, Qt-free playlist state: what's on screen and how to step through it.
:class:`SlideshowPlaylist` plays a set of :class:`Slide` in a random order,
reshuffled each pass, with the shuffle injectable so the order is deterministic
under test; a lock holds one item against the advance, answering Fun Time's
padlock. The set grows as generations land in what the slideshow is playing
(:meth:`SlideshowPlaylist.add`) — a folder that is auto-generating is the case
that asks for it — and it grows earlier still for one that is only being made:
a :data:`LIVE` slide is the frames ComfyUI is streaming of a run, standing in for
the file until :meth:`SlideshowPlaylist.replace_live` swaps it for one.

A third stop — :attr:`SlideshowPlaylist.paused` — is the slideshow's own rather than
the user's: speaking a request keeps the slide for as long as the sentence takes,
and "pause slideshow" until "start slideshow", each released without disturbing
the other or the lock.

Closing a slideshow is rarely being done with it, so where one was is kept:
:class:`SlideshowState` says it and :meth:`SlideshowPlaylist.resume` lays a fresh
pass back out that way. It is said in generation ids rather than in places,
because the set the next slideshow plays is not the one this one held — items landed
while it was away, and anything it culled is gone.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import NamedTuple

# The media type of a slide that is a generation still being made. Its "path" is
# the newest frame ComfyUI has streamed of it, held as encoded bytes, because
# there is no file to point at yet. A run with no frame yet is no slide at all:
# a black screen reading "Generating…" is nothing to watch, but the first
# iterations coming in are the most exciting thing in a folder that is filling.
LIVE = "live"

PAUSED_FOR_A_REQUEST = "request"
PAUSED_BY_VOICE = "pause slideshow"


class Slide(NamedTuple):
    """One thing a slideshow plays: a file (or the frames of a run still making one),
    what kind of media it is, the generation it came from, and the still it is
    drawn as while it is a neighbor rather than the one on screen.

    The last two are absent from a set assembled without them — a lone file, a
    test's — which is what the defaults say, so every slide has four fields and
    nothing has to ask how long one is.
    """

    path: object
    media_type: str
    prompt_id: str | None = None
    still: object | None = None

    @classmethod
    def of(cls, item) -> Slide:
        """*item* as a slide, whether it arrives as one or as the bare tuple the
        assembling caller built."""
        return item if isinstance(item, cls) else cls(*item)

    @property
    def is_live(self) -> bool:
        """Whether this is a run still being made, shown as its newest frame."""
        return self.media_type == LIVE

    def upgraded(self, path, media_type=None, still=None) -> Slide:
        """This slide pointing at a better version of itself.

        The new file, its media type (kept as it was when the caller names
        none), the same id — an enhancement is the same item, not a new one —
        and the new thumbnail when one came with it: the still it arrived with
        is of the version this swap just retired.
        """
        return self._replace(
            path=path,
            media_type=self.media_type if media_type is None else media_type,
            still=self.still if still is None else still,
        )


@dataclass(frozen=True)
class SlideshowFilters:
    favorites: bool = False
    enhanced: bool = False
    act: str = ""

    @classmethod
    def restored(cls, saved) -> SlideshowFilters:
        if not isinstance(saved, dict):
            return cls()
        act = saved.get("act")
        return cls(favorites=saved.get("favorites") is True,
                   enhanced=saved.get("enhanced") is True,
                   act=act if isinstance(act, str) else "")


@dataclass(frozen=True)
class SlideshowState:
    """Where a slideshow was when it closed, for whichever one opens next.

    ``order`` is the pass it was playing and ``current`` the slide it stood on,
    both as generation ids. The rest is what that slide was doing — locked against
    the advance, showing which of its versions.
    """

    order: tuple = ()
    current: str | None = None
    locked: bool = False
    level_index: int = 0
    loop: str = ""

    def saved(self) -> dict:
        return asdict(self)

    @classmethod
    def restored(cls, saved) -> SlideshowState:
        if not isinstance(saved, dict):
            return cls()
        order, current = saved.get("order"), saved.get("current")
        level, loop = saved.get("level_index"), saved.get("loop")
        return cls(
            order=(tuple(pid for pid in order if isinstance(pid, str))
                   if isinstance(order, (list, tuple)) else ()),
            current=current if isinstance(current, str) else None,
            locked=saved.get("locked") is True,
            level_index=level if type(level) is int and level > 0 else 0,
            loop=loop if isinstance(loop, str) else "",
        )


def _without(indices: list, removed: int) -> list:
    return [i - 1 if i > removed else i for i in indices if i != removed]


def in_order(order: list) -> None:
    """A shuffle that doesn't: play the set in the order it was handed over.

    What a double-clicked picture opens in — its folder as the browser lists it,
    starting where the double-click landed — against the random pass a folder
    played from the toolbar gets.
    """


class SlideshowPlaylist:
    def __init__(self, items, *, shuffle=random.shuffle, start=None):
        self._items = [Slide.of(item) for item in items]
        self._shuffle = shuffle
        self._order = list(range(len(self._items)))
        self._shuffle(self._order)  # play in a random order
        # The pass begins at its own front unless a particular item was asked for:
        # a double-clicked picture opens on *that* picture, which sits wherever
        # this pass's order happens to have put it.
        self._pos = (self._order.index(start)
                     if start is not None and 0 <= start < len(self._items) else 0)
        self._locked = False
        self._pauses: set[str] = set()
        self._waiting: list[int] = []

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
        """The pass's item indices — how a slide's place in the set is named.

        Read for the position readout ("picture 3 of 40") and for the hosting
        session's HUD map, both of which have to say where in the *set* the
        slide on screen is, not where in the shuffled pass.
        """
        return list(self._order)

    @property
    def items(self) -> list:
        """The set in its stable order — what a hosting session's HUD maps as
        the seed row, whatever order this pass happens to play them in."""
        return list(self._items)

    def restart(self) -> None:
        """Back to the top of the pass — the reset gesture's "start it again".

        The top of the PASS, not of the set: a shuffled slideshow's first slide is
        wherever its shuffle put it, and coming back to that is what starting
        over looks like from the outside.  The order itself is left as it is,
        so a reset pressed twice does not keep dealing a different slideshow.
        """
        self._pos = 0

    def jump_to(self, item_index: int) -> bool:
        """Move the pass onto the item at stable position *item_index* — a
        thumbnail click on the hosting session's HUD map, the same jump a
        satellite's map makes.  Returns whether the index named an item."""
        if not 0 <= item_index < len(self._items):
            return False
        self._pos = self._order.index(item_index)
        self._seen_on_screen()
        return True

    def lead_with(self, item_index: int) -> None:
        self._take_out_of_the_pass(item_index)
        self._order.insert(self._pos, item_index)
        self._seen_on_screen()

    def _line_up(self, item_index: int) -> None:
        if self._order[self._pos] == item_index or item_index in self._waiting_ahead():
            return
        self._take_out_of_the_pass(item_index)
        places = map(self._order.index, self._waiting_ahead())
        self._order.insert(max(places, default=self._pos) + 1, item_index)
        self._waiting.append(item_index)

    def _waiting_ahead(self) -> list[int]:
        self._waiting = [i for i in self._waiting if self._order.index(i) > self._pos]
        return self._waiting

    def _seen_on_screen(self) -> None:
        if self._order[self._pos] in self._waiting:
            self._waiting.remove(self._order[self._pos])

    def _take_out_of_the_pass(self, item_index: int) -> None:
        at = self._order.index(item_index)
        del self._order[at]
        if at < self._pos:
            self._pos -= 1

    def in_play_order(self) -> list:
        """The items in the order this pass is playing them, rather than the order
        the set was handed over in — so a playlist built from these, in order,
        takes up where this one stopped."""
        return [self._items[index] for index in self._order]

    def order_ids(self) -> list:
        """The pass in ids rather than in places — how a closing slideshow hands its
        order to the next one, over a set that will have moved on."""
        return [self._items[index].prompt_id for index in self._order]

    def resume(self, order_ids, current_id) -> bool:
        """Lay the pass back out the way a closed slideshow left it, standing on the
        slide it was showing. Returns whether that slide is still here to stand on.

        It may not be — culled while the slideshow was away, or this is another
        folder's set entirely — and then nothing is disturbed: a pass laid out
        around an item that isn't in it would open the slideshow on an arbitrary
        stranger, which is worse than the shuffle it already has.

        Items the remembered order doesn't name follow the ones it does, keeping
        the order the shuffle gave them. They were no part of the pass being
        picked back up, and the next pass reshuffles the lot anyway.
        """
        places = {slide.prompt_id: index
                  for index, slide in enumerate(self._items)
                  if slide.prompt_id is not None}
        if current_id not in places:
            return False
        remembered = [places[pid] for pid in order_ids if pid in places]
        placed = set(remembered)
        self._order = remembered + [i for i in self._order if i not in placed]
        self._pos = self._order.index(places[current_id])
        return True

    def _made_by(self, prompt_id) -> list:
        """Where in the set the slides of *prompt_id* sit.

        Nowhere at all when it is ``None``: a set assembled without ids names
        nothing, so an unnamed generation must not match the unnamed slides.
        """
        if prompt_id is None:
            return []
        return [index for index, slide in enumerate(self._items)
                if slide.prompt_id == prompt_id]

    def advance(self):
        """Step to the next item; at the end, reshuffle and start a fresh pass."""
        if self._items:
            self._pos += 1
            if self._pos >= len(self._items):
                self._shuffle(self._order)  # a new random order each pass
                self._pos = 0
            self._seen_on_screen()
        return self.current()

    def back(self):
        """Step to the previous item in the current pass, wrapping to its end."""
        if self._items:
            self._pos = (self._pos - 1) % len(self._items)
        return self.current()

    def add(self, item) -> bool:
        """Take in an item that has landed since the slideshow opened, and line it up
        after the other arrivals still waiting their turn. Returns whether it was
        new here.

        Watching a folder fill is watching for the new one — parked after a
        hundred others it would be an hour away.
        """
        slide = Slide.of(item)
        if self.holds(slide.prompt_id):
            return False
        self._items.append(slide)
        self._order.append(len(self._items) - 1)
        self._line_up(len(self._items) - 1)
        return True

    def holds(self, prompt_id) -> bool:
        """Whether this set already has a slide for that generation, whatever
        state it is in — frames still coming in, or the file it landed as."""
        return bool(self._made_by(prompt_id))

    def live_ids(self) -> list:
        """The generations this set is playing as frames rather than as files —
        who to ask about, when the question is which runs are still going."""
        return [slide.prompt_id for slide in self._items
                if slide.is_live and slide.prompt_id is not None]

    def current_is_live(self) -> bool:
        slide = self.current()
        return slide is not None and slide.is_live

    def update_live(self, prompt_id, frame) -> bool:
        """Point a slide that is still being made at the newest frame of it.
        Returns whether there was such a slide.

        Only a live one. A frame arriving after the run landed — a message from
        the tail of it, or a poll a beat late — must not take the finished
        picture back off the screen and put a half-rendered one there.
        """
        live = [index for index in self._made_by(prompt_id)
                if self._items[index].is_live]
        for index in live:
            self._items[index] = self._items[index].upgraded(frame)
        return bool(live)

    def replace_live(self, prompt_id, path, media_type, still=None) -> bool:
        """Swap the frames of a slide still being made for the file it landed as.
        Returns whether such a slide was here."""
        live = [index for index in self._made_by(prompt_id) if self._items[index].is_live]
        if not live:
            return False
        self.replace_item(prompt_id, path, media_type, still)
        for index in live:
            self._line_up(index)
        return True

    def remove_current(self):
        """Drop the current item; the item that followed it becomes current."""
        if self._items:
            self._remove(self._order[self._pos])

    def drop(self, prompt_id) -> bool:
        """Take a named item out of the set wherever it sits, rather than only
        while it is the one on screen. Returns whether it was here.

        What a run that stopped being made leaves: cancelled or failed, it
        has no file coming and its last frame would otherwise sit in the pass
        forever.
        """
        for index in self._made_by(prompt_id):
            self._remove(index)
            return True
        return False

    def _remove(self, index: int) -> None:
        """Take the item at ``index`` out of the set and out of the running pass,
        keeping the slideshow standing where it stands: on the item that followed one
        removed from under it, and on the same item otherwise."""
        at = self._order.index(index)
        del self._items[index]
        self._order = _without(self._order, index)
        self._waiting = _without(self._waiting, index)
        if at < self._pos:
            self._pos -= 1  # the pass got shorter in front of where we are
        if not self._order or self._pos >= len(self._order):
            self._pos = 0

    def replace_item(self, prompt_id, path, media_type=None, still=None) -> bool:
        """Point the item with this id at a better version of itself — an
        enhancement of it that has landed. Returns whether it was here at all.

        Matched by id wherever the item sits, not only while it is the one on
        screen. An enhancement asked for from a slideshow lands minutes later, by
        which time the slideshow has long paged on, so an arrival dropped for being
        late would leave the pre-enhance file playing every pass for the rest of
        the session.
        """
        found = self._made_by(prompt_id)
        for index in found:
            self._items[index] = self._items[index].upgraded(path, media_type, still)
        return bool(found)

    # --- lock: keep this one against the advance ---------------------------

    @property
    def locked(self) -> bool:
        """Whether the item on screen is locked against the advance.

        "Lock" is what it is called everywhere else — the auto-generate
        rotation, Fun Time's console — so it is what it is called here.
        """
        return self._locked

    def toggle_lock(self) -> bool:
        self._locked = not self._locked
        return self._locked

    def set_locked(self, locked: bool) -> None:
        """Put the lock back where a closed slideshow left it — a slide it was closed
        on locked is one it reopens locked."""
        self._locked = bool(locked)

    def unlock(self) -> None:
        self._locked = False

    # --- pause: a stop the slideshow puts on itself ------------------------

    @property
    def paused(self) -> bool:
        return bool(self._pauses)

    def set_paused(self, paused: bool, reason: str) -> None:
        if paused:
            self._pauses.add(reason)
        else:
            self._pauses.discard(reason)

    @property
    def pauses(self) -> frozenset[str]:
        return frozenset(self._pauses)

    @pauses.setter
    def pauses(self, reasons) -> None:
        self._pauses = set(reasons)

    def locked_or_paused(self) -> bool:
        """Whether anything at all is stopping this slide — locked or paused."""
        return self._locked or self.paused

