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

The map is the players' own (:mod:`origenerator.gui.show_map`): the slide's
act under other seeds runs right, what else was made of its picture runs
down, and a
loop along either axis deals THAT row or column as the pass, the way a
satellite loops a seed family, until it is stepped off or ended.  The set it
was browsing waits underneath and comes back when the loop ends.
"""
from __future__ import annotations

from collections.abc import Callable

from player_core.hud_status import LATEST_LABEL, SHUFFLE_LABEL
from player_core.satellite_hud import label_is_filtered

from origenerator.gui.neighbor_previews import still_for
from origenerator.gui.show_map import (
    ACTION_AXIS,
    LOOP_CYCLE,
    NO_NEIGHBORS,
    SEED_AXIS,
    Loop,
    MapNeighbors,
    ShowMap,
    acts_posted,
    build_map,
    step_in_ring,
)
from origenerator.gui.show_wiring import HudFacts
from origenerator.slideshow import Slide, SlideshowPlaylist, in_order

# What the loop key answers: the axis it started looping, that it ended the
# loop, or — with nothing on either axis to loop — that the press is the lock
# instead, which the surface owns.
LOOP_OFF = "off"
LOOP_IS_A_LOCK = "lock"

NO_ACT_ON_SCREEN = "No act for this one"
ENHANCEMENT_RUNNING = "running"
ENHANCEMENT_QUEUED = "queued"
_ENHANCEMENT_WORDS = {ENHANCEMENT_RUNNING: "Enhancing…",
                      ENHANCEMENT_QUEUED: "Enhancement queued"}
GENERATING = "Generating…"


class ShowSet:
    """Everything a show has been handed, the pass dealt from what the
    switches keep of it, and the map around the slide on screen."""

    def __init__(self, items, *, image_dwell_ms: int, shuffle=None, start=None,
                 hud: HudFacts | None = None,
                 on_pass_change: Callable[[bool], None] | None = None,
                 neighbors: Callable[[str], MapNeighbors] | None = None,
                 widen: Callable[[str], tuple[Slide, ...]] | None = None,
                 acts: Callable[[list], dict] | None = None) -> None:
        # Kept so a re-dealt pass is laid out the way this show's was: a
        # double-clicked picture's show reads its folder in order, and a filter
        # applied over one must not quietly shuffle it.  None means the
        # playlist's own random shuffle, here and on the way back in.
        self._shuffle = shuffle
        self._on_pass_change = on_pass_change
        # What the library says about an item — its seed row and its action
        # column — and what lies beyond the exact row.  None for a show with
        # no library under it (a test's, a lone file's), whose map is the
        # slide alone.
        self._neighbors_of = neighbors
        self._widen = widen
        self._known: dict[str, MapNeighbors] = {}
        # What each generation's map row is named for, by id -- the acts an
        # act filter matches it on.  None for a show with no library under it.
        self._acts_of = acts
        self._named: dict[str, str] = {}
        self.loop: Loop | None = None
        self.favorites_filter = False
        self.enhanced_mode = False
        self.act_filter = ""
        self._enhancements_asked: set[str] = set()
        self._enhance_frames: dict[str, bytes] = {}
        # Everything this show has been handed, whatever the switches keep of
        # it; the pass is dealt from what survives them (:meth:`set_modes`).
        self.all_items = [Slide.of(item) for item in items]
        self.wear(hud if hud is not None else HudFacts())
        self.playlist = self._deal(items, image_dwell_ms=image_dwell_ms, start=start)
        if start is None:
            self.lead_with_what_is_being_made()
        self._a_row_played_whole_is_its_loop()

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
        self._library_moved()
        self.playlist = self._deal(items, image_dwell_ms=self.playlist.image_dwell_ms,
                                   start=start, shuffle=shuffle)
        self._a_row_played_whole_is_its_loop()

    def _a_row_played_whole_is_its_loop(self) -> None:
        current = self.playlist.current()
        if current is None or current.prompt_id is None or len(self.playlist) < 2:
            return
        row = {current.prompt_id,
               *(seed.prompt_id for seed in self.neighbors(current.prompt_id).seeds)}
        played = self.playlist.in_play_order()
        if all(slide.prompt_id in row for slide in played):
            at = self.playlist.index
            self.loop = Loop(SEED_AXIS, (*played[at:], *played[:at]))

    def replace_items(self, items, *, keep_slide: bool, shuffle=None,
                      new_set: bool = False) -> bool:
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
        keep_id = current.prompt_id if keep_slide and current is not None else None
        start = next((index for index, item in enumerate(items)
                      if keep_id is not None and item.prompt_id == keep_id), None)
        paused = self.playlist.paused
        self.playlist = self._deal(items, image_dwell_ms=self.playlist.image_dwell_ms,
                                   start=start, shuffle=shuffle)
        self.playlist.set_paused(paused)
        if new_set:
            self.lead_with_what_is_being_made()
            self._a_row_played_whole_is_its_loop()
        kept = start is not None
        if self._on_pass_change is not None:
            self._on_pass_change(kept)
        return kept

    def _browse(self) -> list[Slide]:
        """What the show plays when nothing is looping: the whole set, past
        the switches."""
        return [item for item in self.all_items if self.passes(item)]

    # --- the two switches --------------------------------------------------

    def set_modes(self, *, favorites_filter: bool, enhanced: bool,
                  act_filter: str | None = None) -> bool:
        """Deal the pass from what answers the switches as asked — all on
        meaning what answers all of them, the way every set of filters in this
        family stacks — and say whether anything moved.  *act_filter* left
        unsaid stays as it is.

        A switch that would leave nothing is refused rather than obeyed: an
        empty show is not a mode, and the HUD's button staying dark is the
        answer.  Widening can never empty a set, so the way back is always open.
        A loop ends with it: the switch is a narrowing of the browse, and the
        pass it deals is the browse.
        """
        act_filter = self.act_filter if act_filter is None else act_filter
        if (favorites_filter, enhanced, act_filter) == (
                self.favorites_filter, self.enhanced_mode, self.act_filter):
            return False
        narrowed = [item for item in self.all_items
                    if self.passes(item, favorites_filter=favorites_filter,
                                   enhanced=enhanced, act_filter=act_filter)]
        if not narrowed:
            return False
        self.favorites_filter, self.enhanced_mode, self.act_filter = (
            favorites_filter, enhanced, act_filter)
        self.loop = None
        self.replace_items(narrowed, keep_slide=True)
        return True

    def set_act_filter(self, query: str) -> bool:
        """Narrow the pass to what is named for the act(s) *query* names — the
        third switch, stacked on the other two — or lift it for ""."""
        return self.set_modes(favorites_filter=self.favorites_filter,
                              enhanced=self.enhanced_mode, act_filter=query)

    def drop_the_switches(self) -> bool:
        """Every switch off, the pass re-dealt over the whole set — a reset.

        ``False`` when none was on: there is nothing to widen back to, and
        the pass is left exactly as it is for the surface to start over in.
        """
        if not self._narrowed():
            return False
        self._widen_back()
        self.loop = None
        self.replace_items(self.all_items, keep_slide=False)
        return True

    def _narrowed(self) -> bool:
        return bool(self.favorites_filter or self.enhanced_mode or self.act_filter)

    def _widen_back(self) -> None:
        self.favorites_filter = self.enhanced_mode = False
        self.act_filter = ""

    def retune(self, items, *, enhanced_ids=()) -> None:
        """Point the set at the side's base set: a hosted reset."""
        self._widen_back()
        self.reorder(items, latest=False, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=()) -> None:
        self._shuffle = in_order if latest else None
        self.loop = None
        self._library_moved()
        self.all_items = [Slide.of(item) for item in items]
        self.wear(HudFacts(order_label=LATEST_LABEL if latest else SHUFFLE_LABEL,
                           favorite_ids=self.favorite_ids, enhanced_ids=enhanced_ids,
                           enhancing=self.enhance_status))
        kept = [item for item in self.all_items if self.passes(item)]
        if not kept:
            self._widen_back()
            kept = self.all_items
        self.replace_items(kept, keep_slide=False, new_set=True)

    def passes(self, item, *, favorites_filter=None, enhanced=None, act_filter=None) -> bool:
        """Whether *item* survives the switches — the ones on, unless asked
        about a setting the show is not in yet.  An item with no id (a test's,
        or a run's frames) is neither favorited nor enhanced, so any switch that
        is on leaves it out."""
        favorites_filter = self.favorites_filter if favorites_filter is None else favorites_filter
        enhanced = self.enhanced_mode if enhanced is None else enhanced
        act_filter = self.act_filter if act_filter is None else act_filter
        prompt_id = item.prompt_id
        if favorites_filter and prompt_id not in self.favorite_ids:
            return False
        if enhanced and prompt_id not in self.enhanced_ids:
            return False
        return not act_filter or label_is_filtered(self._named_for(prompt_id), act_filter,
                                                   camera_words=())

    def _named_for(self, prompt_id) -> str:
        """The act(s) *prompt_id*'s map row is named for.  The whole set is
        asked about at once, the first time anything is: the answer costs a
        walk of the library, and a filter asks it of every item."""
        if prompt_id is None or self._acts_of is None:
            return ""
        if prompt_id not in self._named:
            asked = [prompt_id, *(item.prompt_id for item in self.all_items
                                  if item.prompt_id is not None)]
            self._named = {**dict.fromkeys(asked, ""), **self._acts_of(asked)}
        return self._named[prompt_id]

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
        self._library_moved()
        self._take_into_a_looping_row(item)
        for index, kept in enumerate(self.all_items):
            if self._same(kept, item):
                self.all_items[index] = item
                return
        self.all_items.append(item)

    def _take_into_a_looping_row(self, item: Slide) -> None:
        loop = self.loop
        if (loop is None or loop.axis != SEED_AXIS or item.prompt_id is None
                or loop.position_of(item) is not None):
            return
        row = self.neighbors(loop.pool[0].prompt_id).seeds
        if any(self._same(seed, item) for seed in row):
            self.loop = Loop(loop.axis, (*loop.pool, item))

    def forget(self, item) -> None:
        self._forget(lambda kept: self._same(kept, item))

    def forget_id(self, prompt_id) -> None:
        self._forget(lambda kept: kept.prompt_id == prompt_id)

    def _forget(self, is_gone) -> None:
        """Take slides out of the whole set — and out of a running loop's pool,
        which the map is drawn from rather than from the library, so a picture
        left in it goes on being drawn after it has gone."""
        self._library_moved()
        self.all_items = [kept for kept in self.all_items if not is_gone(kept)]
        if self.loop is not None:
            kept = tuple(slide for slide in self.loop.pool if not is_gone(slide))
            self.loop = Loop(self.loop.axis, kept) if kept else None

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

    def _library_moved(self) -> None:
        self._known.clear()
        self._named.clear()

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
        return [current, *(around.seeds if axis == SEED_AXIS else around.group)]

    def end_a_loop_of_one(self) -> bool:
        """End a loop left holding only the slide on screen: round a pass that
        size is that same slide again, which is the lock rather than a loop,
        and the forward step is what leaves a lock.  ``True`` when one ended."""
        if self.loop is None or len(self.playlist) > 1:
            return False
        return self.end_loop()

    def step(self, delta: int) -> None:
        """Walk the pass one either way — the browse, or the loop's own row —
        except forward out of a loop of one, which ends it first
        (:meth:`end_a_loop_of_one`) and steps into the browse instead."""
        if delta < 0:
            self.playlist.back()
            return
        self.end_a_loop_of_one()
        self.playlist.advance()

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
        """One press of the loop key: the seed row, then the action column, then
        off — each axis stepped over when it holds only the slide on screen, and
        with neither able to loop the press is the lock instead
        (:data:`LOOP_IS_A_LOCK`), so the key never lands on nothing."""
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
        return LOOP_IS_A_LOCK

    def more_seeds(self) -> bool:
        """Widen the row past what exactly matches and loop what it becomes —
        the map's expand mark.  ``False`` when nothing lies beyond the row."""
        current = self.playlist.current()
        if current is None or self._widen is None:
            return False
        additions = tuple(self._widen(current.prompt_id))
        if not additions:
            return False
        return self.start_loop(SEED_AXIS, [*self.loop_pool(SEED_AXIS), *additions])

    def configuration_row(self, query: str) -> Slide | None:
        """The slide of the column row *query* names, where that row is a
        configuration rather than an act — the half of the column whose button
        jumps to it and loops its seed row.  ``None`` for an act's row, which
        narrows the show instead, and for a row the map does not draw."""
        shown = self.map()
        if shown is None:
            return None
        return next((row.slide for row in shown.column
                     if row.configuration and acts_posted(row.label) == acts_posted(query)),
                    None)

    def slide_for_path(self, path) -> Slide | None:
        """The slide playing *path* — in the pass, or drawn on the map — or ``None``."""
        shown = self.map()
        cells = (*self.playlist.items, *(shown.cells() if shown is not None else ()))
        return next((slide for slide in cells if str(slide.path) == str(path)), None)

    def jump_to(self, slide: Slide) -> bool:
        """Stand the pass on *slide*, splicing it in after the slide on screen
        when the pass has never held it — a map cell can name a generation the
        set does not: a video of a picture it holds, a widened seed.  A jump off a
        running loop's axis ends the loop first.  ``False`` when it is the slide
        already on screen."""
        current = self.playlist.current()
        if current is not None and self._same(current, slide):
            return False
        index = next((index for index, item in enumerate(self.playlist.items)
                      if self._same(item, slide)), None)
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
        axis = SEED_AXIS if along_the_row else ACTION_AXIS
        if bucket in ("corner", axis):
            cells = (shown.corner, *(shown.seeds if along_the_row else shown.actions))
            at = 0 if bucket == "corner" else index + 1
        else:
            # Off the lit cell's own axis — down from a seed, sideways from a
            # act — into that cell's other axis, as if it were the corner.
            current = self.playlist.current()
            around = self.neighbors(current.prompt_id)
            cells = (current, *(around.seeds if along_the_row
                                else (row.slide for row in around.column)))
            at = 0
        return step_in_ring(cells, at, 1 if direction in ("right", "down") else -1)

    # --- what the HUD reads off the set ------------------------------------

    def wear(self, hud: HudFacts) -> None:
        """Take on what the HUD says about the set: how it is ordered, and
        which of its items are favorites, carry an enhancement, or have one
        being made."""
        self.order_label = hud.order_label
        self.favorite_ids = set(hud.favorite_ids or ())
        self.enhanced_ids = set(hud.enhanced_ids or ())
        self.enhance_status = dict(hud.enhancing or {})

    def note_enhancing(self, statuses, frames=None) -> None:
        self.enhance_status = dict(statuses)
        self._enhance_frames = dict(frames or {})

    def frame_being_made_of(self, slide):
        if slide.is_live:
            return slide.path
        if self.enhancement_of(slide.prompt_id) != ENHANCEMENT_RUNNING:
            return None
        return self._enhance_frames.get(slide.prompt_id)

    def note_enhancement_asked(self, prompt_id: str) -> None:
        self._enhancements_asked.add(prompt_id)

    def note_enhancement_landed(self, prompt_id: str) -> None:
        self._enhancements_asked.discard(prompt_id)
        self.enhance_status.pop(prompt_id, None)
        self._enhance_frames.pop(prompt_id, None)
        self.enhanced_ids.add(prompt_id)

    def enhancement_of(self, prompt_id) -> str:
        if prompt_id in self.enhance_status:
            return self.enhance_status[prompt_id]
        return ENHANCEMENT_QUEUED if prompt_id in self._enhancements_asked else ""

    def being_made(self, slide) -> bool:
        return slide.is_live or self.enhancement_of(slide.prompt_id) == ENHANCEMENT_RUNNING

    def pace_for(self, slide, seconds: float) -> float:
        return seconds / 2 if self.being_made(slide) else seconds

    def lead_with_what_is_being_made(self) -> bool:
        playlist = self.playlist
        index = next((index for index, item in enumerate(playlist.items)
                      if self.being_made(item)), None)
        if index is None or playlist.locked or playlist.order[playlist.index] == index:
            return False
        playlist.lead_with(index)
        return True

    def current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a set assembled without
        ids (a test's) names nothing."""
        item = self.playlist.current()
        return item.prompt_id if item is not None else None

    def act_on_screen(self) -> str:
        return self._named_for(self.current_prompt_id())

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


def narrow_to_acts(show_set: ShowSet, posted: str) -> tuple[str, bool]:
    """Narrow *show_set* to the act(s) a row's button or a spoken act *posted*
    — or lift the filter, for nothing posted — and answer with what a show
    says about it, the way a satellite says it, and whether that is a dead
    end: an act nothing here is named for leaves the pass alone."""
    acts = acts_posted(posted)
    if not (show_set.set_act_filter(acts) or acts == show_set.act_filter):
        return f"Filter: no matches for '{acts}'", False
    summary = f"'{acts}'" if acts else "cleared"
    return f"Filter: {summary} ({len(show_set.playlist)})", True


def narrow_to_the_act_on_screen(show_set: ShowSet) -> tuple[str, bool]:
    act = show_set.act_on_screen()
    if not act:
        return NO_ACT_ON_SCREEN, False
    return narrow_to_acts(show_set, act)
def item_note(show_set: ShowSet, *, levels, level_index: int) -> str:
    if show_set.playlist.current_is_live():
        return GENERATING
    parts = []
    if len(levels) > 1:
        label = levels[level_index][2]
        parts.append(f"{label} — {level_index + 1} of {len(levels)}")
    enhancement = show_set.enhancement_of(show_set.current_prompt_id())
    if enhancement:
        parts.append(_ENHANCEMENT_WORDS[enhancement])
    return " · ".join(parts)


def looping_note(show_set: ShowSet) -> str:
    """What a show says as a loop starts, the way a satellite says it:
    which axis, and how many are in it."""
    loop = show_set.loop
    return f"Looping {loop.axis}s: {len(loop.pool)}"


def thumb_of(slide: Slide) -> str:
    """The still a map cell draws for *slide*, as the path the panel takes."""
    still = still_for(slide)
    return str(still) if still else ""
