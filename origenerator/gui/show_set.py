"""The set a show plays, what its two switches keep of it, and the map around
the slide on screen.

A show is handed a set of generations and deals a pass from it — shuffled, or
in the browser's own order — narrows it to the favorites or to the pictures it
has enhanced, and grows it as generations land in the folder it is playing.
None of that is about a window: a show drawn full screen by this app and a show
handed to one of a Fun Time session's players keep exactly this set and differ
only in what puts the slide on screen.  So it lives here, Qt-free, and each
surface holds one.

The pass itself is :class:`~origenerator.slideshow.SlideshowPlaylist`; this is
the set around it.  Re-dealing the pass — a switch coming on, a reset, a fresh
set, a loop starting or ending — is what a surface has to answer for (a window
re-renders; a player is handed a new playlist), so it arrives as
``on_pass_change(kept)``: whether the slide that was on screen survived into
the new pass.

The map is the players' own (:mod:`origenerator.gui.show_map`): what shares
the slide's configuration runs right, what shares its seed runs down, and a
loop along either axis deals THAT row or column as the pass, the way a
satellite loops a seed family, until it is stepped off or ended.  The set it
was browsing waits underneath and comes back when the loop ends.
"""
from __future__ import annotations

from collections.abc import Callable

from player_core.hud_status import LATEST_LABEL, SHUFFLE_LABEL

from origenerator.gui.neighbor_previews import still_for
from origenerator.gui.show_map import (
    CONFIG_AXIS,
    LOOP_CYCLE,
    NO_NEIGHBORS,
    SEED_AXIS,
    Loop,
    MapNeighbors,
    ShowMap,
    build_map,
    label_query,
    step_in_ring,
)
from origenerator.gui.show_wiring import HudFacts
from origenerator.slideshow import Slide, SlideshowPlaylist, in_order

# What the loop key answers: the axis it started looping, that it ended the
# loop, or — with nothing on either axis to loop — that the press is the hold
# instead, which the surface owns.
LOOP_OFF = "off"
LOOP_IS_A_HOLD = "hold"


class ShowSet:
    """Everything a show has been handed, the pass dealt from what the
    switches keep of it, and the map around the slide on screen."""

    def __init__(self, items, *, image_dwell_ms: int, shuffle=None, start=None,
                 hud: HudFacts | None = None,
                 on_pass_change: Callable[[bool], None] | None = None,
                 neighbors: Callable[[str], MapNeighbors] | None = None,
                 widen: Callable[[str], tuple[Slide, ...]] | None = None) -> None:
        # Kept so a re-dealt pass is laid out the way this show's was: a
        # double-clicked picture's show reads its folder in order, and a filter
        # applied over one must not quietly shuffle it.  None means the
        # playlist's own random shuffle, here and on the way back in.
        self._shuffle = shuffle
        self._on_pass_change = on_pass_change
        # What the library says about an item — its seed row and its config
        # column — and what lies beyond the exact row.  None for a show with
        # no library under it (a test's, a lone file's), whose map is the
        # slide alone.
        self._neighbors_of = neighbors
        self._widen = widen
        self._known: dict[str, MapNeighbors] = {}
        self.loop: Loop | None = None
        self.favorites_filter = False
        self.enhanced_mode = False
        # Everything this show has been handed, whatever the switches keep of
        # it; the pass is dealt from what survives them (:meth:`set_modes`).
        self.all_items = [Slide.of(item) for item in items]
        self.wear(hud if hud is not None else HudFacts())
        self.playlist = self._deal(items, image_dwell_ms=image_dwell_ms, start=start)

    # --- the pass ----------------------------------------------------------

    def _deal(self, items, *, image_dwell_ms: int, start=None,
              shuffle=None) -> SlideshowPlaylist:
        kwargs = {"image_dwell_ms": image_dwell_ms, "start": start}
        shuffle = self._shuffle if shuffle is None else shuffle
        if shuffle is not None:  # else the playlist uses its own random shuffle
            kwargs["shuffle"] = shuffle
        return SlideshowPlaylist(items, **kwargs)

    def reseed(self, items, *, start=None, shuffle=None) -> None:
        """Play *items* instead, from the top or from *start*.

        The set itself is replaced, not narrowed: what a show armed with its
        folder once the gallery has worked out which folder that is takes, and
        what a show following one generation takes when the file lands.
        """
        self.all_items = [Slide.of(item) for item in items]
        self.loop = None
        self._known.clear()
        self.playlist = self._deal(items, image_dwell_ms=self.playlist.image_dwell_ms,
                                   start=start, shuffle=shuffle)

    def replace_items(self, items, *, keep_slide: bool, shuffle=None) -> bool:
        """Stand a fresh pass up over *items*, keeping the pace and the pause;
        say whether the slide on screen survived into it.

        *keep_slide* keeps the slide on screen when it is among them: a switch
        is a narrowing of what you are looking through, not a new show, and
        taking the picture away as well would make the switch impossible to
        try.  A reset says otherwise — it starts the set over from the top.
        *shuffle* lays the pass out some other way than this show's own — a
        loop plays its row in the row's order.
        """
        current = self.playlist.current()
        held = current.prompt_id if keep_slide and current is not None else None
        start = next((index for index, item in enumerate(items)
                      if held is not None and item.prompt_id == held), None)
        paused = self.playlist.paused
        self.playlist = self._deal(items, image_dwell_ms=self.playlist.image_dwell_ms,
                                   start=start, shuffle=shuffle)
        self.playlist.set_paused(paused)
        kept = start is not None
        if self._on_pass_change is not None:
            self._on_pass_change(kept)
        return kept

    def _browse(self) -> list[Slide]:
        """What the show plays when nothing is looping: the whole set, past
        the switches."""
        return [item for item in self.all_items if self.passes(item)]

    # --- the two switches --------------------------------------------------

    def set_modes(self, *, favorites_filter: bool, enhanced: bool) -> bool:
        """Deal the pass from what answers the switches as asked — both on
        meaning what answers both, the way every pair of filters in this family
        stacks — and say whether anything moved.

        A switch that would leave nothing is refused rather than obeyed: an
        empty show is not a mode, and the HUD's button staying dark is the
        answer.  Widening can never empty a set, so the way back is always open.
        A loop ends with it: the switch is a narrowing of the browse, and the
        pass it deals is the browse.
        """
        if (favorites_filter, enhanced) == (self.favorites_filter, self.enhanced_mode):
            return False
        narrowed = [item for item in self.all_items
                    if self.passes(item, favorites_filter=favorites_filter, enhanced=enhanced)]
        if not narrowed:
            return False
        self.favorites_filter, self.enhanced_mode = favorites_filter, enhanced
        self.loop = None
        self.replace_items(narrowed, keep_slide=True)
        return True

    def drop_the_switches(self) -> bool:
        """Both switches off, the pass re-dealt over the whole set — a reset.

        ``False`` when neither was on: there is nothing to widen back to, and
        the pass is left exactly as it is for the surface to start over in.
        """
        if not (self.favorites_filter or self.enhanced_mode):
            return False
        self.favorites_filter = self.enhanced_mode = False
        self.loop = None
        self.replace_items(self.all_items, keep_slide=False)
        return True

    def retune(self, items, *, enhanced_ids=()) -> None:
        """Point the set at the side's base set: a hosted reset."""
        self.favorites_filter = self.enhanced_mode = False
        self.reorder(items, latest=False, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=()) -> None:
        self._shuffle = in_order if latest else None
        self.loop = None
        self._known.clear()
        self.all_items = [Slide.of(item) for item in items]
        self.wear(HudFacts(order_label=LATEST_LABEL if latest else SHUFFLE_LABEL,
                           favorite_ids=self.favorite_ids, enhanced_ids=enhanced_ids))
        kept = [item for item in self.all_items if self.passes(item)]
        if not kept:
            self.favorites_filter = self.enhanced_mode = False
            kept = self.all_items
        self.replace_items(kept, keep_slide=False)

    def passes(self, item, *, favorites_filter=None, enhanced=None) -> bool:
        """Whether *item* survives the switches — the ones on, unless asked
        about a setting the show is not in yet.  An item with no id (a test's,
        or a run's frames) is neither favorited nor enhanced, so any switch that
        is on leaves it out."""
        favorites_filter = self.favorites_filter if favorites_filter is None else favorites_filter
        enhanced = self.enhanced_mode if enhanced is None else enhanced
        prompt_id = item.prompt_id
        if favorites_filter and prompt_id not in self.favorite_ids:
            return False
        if enhanced and prompt_id not in self.enhanced_ids:
            return False
        return True

    # --- keeping the whole set current -------------------------------------
    # Kept in step with the pass by id where an item has one, so an arrival,
    # a cull or an enhancement landing while a switch is on is still there —
    # or still gone — when the switch comes off.

    @staticmethod
    def _same(kept: Slide, item: Slide) -> bool:
        return kept is item or (kept.prompt_id is not None
                                and kept.prompt_id == item.prompt_id)

    def remember(self, item) -> None:
        """Take *item* into the whole set, in place of the entry with its id.
        The library moved, so what it says about every item is asked again."""
        self._known.clear()
        for index, kept in enumerate(self.all_items):
            if self._same(kept, item):
                self.all_items[index] = item
                return
        self.all_items.append(item)

    def forget(self, item) -> None:
        self._known.clear()
        self.all_items = [kept for kept in self.all_items if not self._same(kept, item)]

    def forget_id(self, prompt_id) -> None:
        self._known.clear()
        self.all_items = [kept for kept in self.all_items if kept.prompt_id != prompt_id]

    def live_ids(self) -> list:
        """Every run the whole set holds as frames rather than as a file — in
        the pass or kept out of it by a switch."""
        return [kept.prompt_id for kept in self.all_items if kept.is_live]

    def upgrade(self, prompt_id, path, media_type, still):
        """Point the whole set's entry for *prompt_id* at a better version of
        itself, and return it — or ``None`` when the set never held it."""
        for index, kept in enumerate(self.all_items):
            if kept.prompt_id == prompt_id:
                self.all_items[index] = kept.upgraded(path, media_type, still)
                return self.all_items[index]
        return None

    # --- the map, and the loops along it -----------------------------------

    def neighbors(self, prompt_id) -> MapNeighbors:
        """What the library says about *prompt_id*, asked once per item: the
        answer costs a walk of the library, and the map asks on every beat."""
        if prompt_id is None or self._neighbors_of is None:
            return NO_NEIGHBORS
        found = self._known.get(prompt_id)
        if found is None:
            found = self._known[prompt_id] = self._neighbors_of(prompt_id)
        return found

    def map(self) -> ShowMap | None:
        """The gamma around the slide on screen, or ``None`` with nothing on it."""
        current = self.playlist.current()
        if current is None:
            return None
        return build_map(current, self.loop, self.neighbors)

    def loop_pool(self, axis: str) -> list[Slide]:
        """The slides a loop along *axis* would play, the slide on screen first."""
        current = self.playlist.current()
        if current is None:
            return []
        around = self.neighbors(current.prompt_id)
        return [current, *(around.seeds if axis == SEED_AXIS else around.configs)]

    def start_loop(self, axis: str, pool=None) -> bool:
        """Play *pool* — *axis*'s row or column around the slide on screen, by
        default — round and round, in its own order, the slide on screen
        staying where it is.  ``False`` for a pool of one, which is nothing to
        loop."""
        pool = list(self.loop_pool(axis) if pool is None else pool)
        if len(pool) < 2:
            return False
        self.loop = Loop(axis, tuple(pool))
        self.replace_items(pool, keep_slide=True, shuffle=in_order)
        return True

    def end_loop(self) -> bool:
        """Back to browsing the set, the slide on screen kept: a loop that
        wandered onto a stranger to the set plays it out and the browse is what
        comes next, the way a satellite's browse resumes after its loop.
        ``False`` when nothing was looping."""
        if self.loop is None:
            return False
        self.loop = None
        browse = self._browse()
        current = self.playlist.current()
        if current is not None and not any(self._same(item, current) for item in browse):
            browse = [current, *browse]
        self.replace_items(browse, keep_slide=True)
        return True

    def step_loop(self) -> str:
        """One press of the loop key: the seed row, then the config column, then
        off — each axis stepped over when it holds only the slide on screen, and
        with neither able to loop the press is the hold instead
        (:data:`LOOP_IS_A_HOLD`), so the key never lands on nothing."""
        running = self.loop.axis if self.loop is not None else ""
        start = LOOP_CYCLE.index(running) + 1 if running in LOOP_CYCLE else 0
        for step in range(len(LOOP_CYCLE)):
            axis = LOOP_CYCLE[(start + step) % len(LOOP_CYCLE)]
            if not axis:
                if running:
                    self.end_loop()
                    return LOOP_OFF
                continue
            if self.start_loop(axis):
                return axis
        return LOOP_IS_A_HOLD

    def more_seeds(self) -> bool:
        """Widen the row past the exact configuration and loop what it becomes —
        the map's expand mark.  ``False`` when nothing lies beyond the row."""
        current = self.playlist.current()
        if current is None or self._widen is None:
            return False
        additions = tuple(self._widen(current.prompt_id))
        if not additions:
            return False
        return self.start_loop(SEED_AXIS, [*self.loop_pool(SEED_AXIS), *additions])

    def row_slide(self, query: str) -> Slide | None:
        shown = self.map()
        if shown is None:
            return None
        rows = ((shown.corner, shown.label), *zip(shown.configs, shown.config_labels))
        return next((slide for slide, label in rows
                     if label and label_query(label) == query), None)

    def slide_for_path(self, path) -> Slide | None:
        """The slide playing *path* — in the pass, or drawn on the map — or ``None``."""
        shown = self.map()
        cells = (*self.playlist.items, *(shown.cells() if shown is not None else ()))
        return next((slide for slide in cells if str(slide.path) == str(path)), None)

    def jump_to(self, slide: Slide) -> bool:
        """Stand the pass on *slide*, splicing it in after the slide on screen
        when the pass has never held it — a map cell can name a generation the
        set does not: a configuration sibling, a widened seed.  A jump off a
        running loop's axis ends the loop first.  ``False`` when it is the slide
        already on screen."""
        current = self.playlist.current()
        if current is not None and self._same(current, slide):
            return False
        index = next((index for index, held in enumerate(self.playlist.items)
                      if self._same(held, slide)), None)
        if index is not None:
            self.playlist.jump_to(index)
            return True
        if self.loop is not None:
            self.end_loop()
        self.playlist.add(slide)
        self.playlist.advance()
        return True

    def nav_target(self, direction: str) -> Slide | None:
        """The map cell one step *direction* from the lit one, or ``None`` when
        there is nothing that way: right and left walk the row's ring, down and
        up the column's, each with the corner at its head.  From a lit seed the
        column is that seed's own, since the map draws it there."""
        shown = self.map()
        if shown is None:
            return None
        bucket, index = shown.playing
        along_the_row = direction in ("right", "left")
        axis = SEED_AXIS if along_the_row else CONFIG_AXIS
        if bucket in ("corner", axis):
            cells = (shown.corner, *(shown.seeds if along_the_row else shown.configs))
            at = 0 if bucket == "corner" else index + 1
        else:
            # Off the lit cell's own axis — down from a seed, sideways from a
            # config — into that cell's other axis, as if it were the corner.
            current = self.playlist.current()
            around = self.neighbors(current.prompt_id)
            cells = (current, *(around.seeds if along_the_row else around.configs))
            at = 0
        return step_in_ring(cells, at, 1 if direction in ("right", "down") else -1)

    # --- what the HUD reads off the set ------------------------------------

    def wear(self, hud: HudFacts) -> None:
        """Take on what the HUD says about the set: how it is ordered, and
        which of its items are favorites or carry an enhancement."""
        self.order_label = hud.order_label
        self.favorite_ids = set(hud.favorite_ids or ())
        self.enhanced_ids = set(hud.enhanced_ids or ())

    def current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a set assembled without
        ids (a test's) names nothing."""
        item = self.playlist.current()
        return item.prompt_id if item is not None else None

    @property
    def is_favorite(self) -> bool:
        """Whether the item on screen is one of the favorites — the star the
        HUD marks at the head of the line naming that very item."""
        return self.current_prompt_id() in self.favorite_ids

    def unfavorite_current(self, unfavorite) -> bool:
        """Take the star off the item on screen, through *unfavorite* — the
        players' "weird" on a favorite, which demotes it rather than condemning
        it.  ``False`` when it wears no star, or nothing was wired to take one
        off: then the press means the other thing."""
        prompt_id = self.current_prompt_id()
        if unfavorite is None or prompt_id is None or prompt_id not in self.favorite_ids:
            return False
        unfavorite(prompt_id)
        self.favorite_ids.discard(prompt_id)  # the star readout and F-mode follow it
        return True


def looping_note(show_set: ShowSet) -> str:
    """What a show says as a loop starts, the way a satellite says it:
    which axis, and how many are in it."""
    loop = show_set.loop
    return f"Looping {loop.axis}s: {len(loop.pool)}"


def thumb_of(slide: Slide) -> str:
    """The still a map cell draws for *slide*, as the path the panel takes."""
    still = still_for(slide)
    return str(still) if still else ""
