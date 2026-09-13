"""The set a show plays, and what its two switches keep of it.

A show is handed a set of generations and deals a pass from it — shuffled, or
in the browser's own order — narrows it to the favorites or to the pictures it
has enhanced, and grows it as generations land in the folder it is playing.
None of that is about a window: a show drawn full screen by this app and a show
handed to one of a Fun Time session's players keep exactly this set and differ
only in what puts the slide on screen.  So it lives here, Qt-free, and each
surface holds one.

The pass itself is :class:`~origenerator.slideshow.SlideshowPlaylist`; this is
the set around it.  Re-dealing the pass — a switch coming on, a reset, a fresh
set — is what a surface has to answer for (a window re-renders; a player is
handed a new playlist), so it arrives as ``on_pass_change(kept)``: whether the
slide that was on screen survived into the new pass.
"""
from __future__ import annotations

from collections.abc import Callable

from origenerator.gui.neighbor_previews import still_for
from origenerator.gui.show_wiring import HudFacts
from origenerator.slideshow import Slide, SlideshowPlaylist


class ShowSet:
    """Everything a show has been handed, and the pass dealt from what the
    switches keep of it."""

    def __init__(self, items, *, image_dwell_ms: int, shuffle=None, start=None,
                 hud: HudFacts | None = None,
                 on_pass_change: Callable[[bool], None] | None = None) -> None:
        # Kept so a re-dealt pass is laid out the way this show's was: a
        # double-clicked picture's show reads its folder in order, and a filter
        # applied over one must not quietly shuffle it.  None means the
        # playlist's own random shuffle, here and on the way back in.
        self._shuffle = shuffle
        self._on_pass_change = on_pass_change
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
        self.playlist = self._deal(items, image_dwell_ms=self.playlist.image_dwell_ms,
                                   start=start, shuffle=shuffle)

    def replace_items(self, items, *, keep_slide: bool) -> bool:
        """Stand a fresh pass up over *items*, keeping the pace and the pause;
        say whether the slide on screen survived into it.

        *keep_slide* keeps the slide on screen when it is among them: a switch
        is a narrowing of what you are looking through, not a new show, and
        taking the picture away as well would make the switch impossible to
        try.  A reset says otherwise — it starts the set over from the top.
        """
        current = self.playlist.current()
        held = current.prompt_id if keep_slide and current is not None else None
        start = next((index for index, item in enumerate(items)
                      if held is not None and item.prompt_id == held), None)
        paused = self.playlist.paused
        self.playlist = self._deal(items, image_dwell_ms=self.playlist.image_dwell_ms,
                                   start=start)
        self.playlist.set_paused(paused)
        kept = start is not None
        if self._on_pass_change is not None:
            self._on_pass_change(kept)
        return kept

    # --- the two switches --------------------------------------------------

    def set_modes(self, *, favorites_filter: bool, enhanced: bool) -> bool:
        """Deal the pass from what answers the switches as asked — both on
        meaning what answers both, the way every pair of filters in this family
        stacks — and say whether anything moved.

        A switch that would leave nothing is refused rather than obeyed: an
        empty show is not a mode, and the HUD's button staying dark is the
        answer.  Widening can never empty a set, so the way back is always open.
        """
        if (favorites_filter, enhanced) == (self.favorites_filter, self.enhanced_mode):
            return False
        narrowed = [item for item in self.all_items
                    if self.passes(item, favorites_filter=favorites_filter, enhanced=enhanced)]
        if not narrowed:
            return False
        self.favorites_filter, self.enhanced_mode = favorites_filter, enhanced
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
        self.replace_items(self.all_items, keep_slide=False)
        return True

    def retune(self, items, *, hud: HudFacts) -> None:
        """Point the set at another one entirely, described afresh.

        What a hosted reset does: the side goes back to its base state, which
        is a different set rather than a narrowing of this one — so both
        switches come off, the pass is a fresh deal, and what the HUD says
        about it is re-dressed.
        """
        self.favorites_filter = self.enhanced_mode = False
        self.all_items = [Slide.of(item) for item in items]
        self.wear(hud)
        self.replace_items(self.all_items, keep_slide=False)

    def passes(self, item, *, favorites_filter=None, enhanced=None) -> bool:
        """Whether *item* survives the switches — the ones on, unless asked
        about a setting the show is not in yet.  An item with no id (a test's,
        or a run's frames) is neither starred nor enhanced, so any switch that
        is on leaves it out."""
        favorites_filter = self.favorites_filter if favorites_filter is None else favorites_filter
        enhanced = self.enhanced_mode if enhanced is None else enhanced
        prompt_id = item.prompt_id
        if favorites_filter and prompt_id not in self.starred_ids:
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
        """Take *item* into the whole set, in place of the entry with its id."""
        for index, kept in enumerate(self.all_items):
            if self._same(kept, item):
                self.all_items[index] = item
                return
        self.all_items.append(item)

    def forget(self, item) -> None:
        self.all_items = [kept for kept in self.all_items if not self._same(kept, item)]

    def forget_id(self, prompt_id) -> None:
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

    # --- what the HUD reads off the set ------------------------------------

    def wear(self, hud: HudFacts) -> None:
        """Take on what the HUD says about the set: how it is ordered, whether
        it is a loop someone asked for, and which of its items are favorites or
        carry an enhancement."""
        self.order_label = hud.order_label
        self.looping = hud.looping
        self.starred_ids = set(hud.starred_ids or ())
        self.enhanced_ids = set(hud.enhanced_ids or ())

    def hud_items(self):
        """The set for a show's HUD: ``(path, still)`` per item in stable
        order, the current item's 1-based position in that order, and the
        lock."""
        items = self.playlist.items
        cells = [(item.path, still_for(item) or "") for item in items]
        position = (self.playlist.order[self.playlist.index] + 1) if items else 0
        return cells, position, self.playlist.locked

    def current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a set assembled without
        ids (a test's) names nothing."""
        item = self.playlist.current()
        return item.prompt_id if item is not None else None

    @property
    def is_favorite(self) -> bool:
        """Whether the item on screen is one of the favorites — the star the
        HUD marks at the head of the line naming that very item."""
        return self.current_prompt_id() in self.starred_ids
