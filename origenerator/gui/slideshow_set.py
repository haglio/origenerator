from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace

from funestra.hud_title import LATEST_LABEL, SHUFFLE_LABEL, looping_label
from funestra.loop_cycle import ACTION, LOCK, OFF, SEED, next_stop, standing_at
from funestra.satellite_hud import label_is_filtered

from origenerator.gui.hud_nav_map import (
    NO_NEIGHBORS,
    Loop,
    NavMap,
    NavMapNeighbors,
    actions_posted,
    build_nav_map,
    step_in_ring,
)
from origenerator.gui.slideshow_pass import rotated_onto
from origenerator.gui.slideshow_wiring import NO_DEAL, HudFacts, SetDeal, SlideshowActions
from origenerator.media import MediaType
from origenerator.slideshow import (
    LIVE,
    Slide,
    SlideshowFilters,
    SlideshowState,
    in_order,
    same_slide,
)
from origenerator.slideshow_deal import Dealing, as_its_loop, dealt, followed_to, taken_up

NO_ACTION_ON_SCREEN = "No action for this one"
ENHANCEMENT_RUNNING = "running"
ENHANCEMENT_QUEUED = "queued"
_ENHANCEMENT_WORDS = {ENHANCEMENT_RUNNING: "Enhancing…",
                      ENHANCEMENT_QUEUED: "Enhancement queued"}
GENERATING = "Generating…"


class SlideshowSet:
    def __init__(self, items, *, actions: SlideshowActions, deal: SetDeal = NO_DEAL,
                 hud: HudFacts | None = None,
                 on_pass_change: Callable[[bool], None] | None = None) -> None:
        self._shuffle = deal.shuffle
        self._dealing = Dealing(weight_of=actions.weight_of, group_of=actions.group_of,
                                filters_of=lambda: self.filters, stays=self.being_made)
        self._on_pass_change = on_pass_change or (lambda _kept: None)
        self._neighbors_of = actions.neighbors
        self._widen = actions.widen
        self._known: dict[str, NavMapNeighbors] = deal.neighbors_known()
        self._actions_of = actions.actions_of
        self._named: dict[str, str] = {}
        self._slides_of = actions.slides
        self._on_filters_change = actions.filters_changed
        self.loop: Loop | None = None
        self.filters = SlideshowFilters()
        self._enhancements_asked: set[str] = set()
        self._enhance_frames: dict[str, bytes] = {}
        self._runs_offered: set[str] = set()
        self.all_items = [Slide.of(item) for item in items]
        self.wear(hud if hud is not None else HudFacts())
        self.playlist = dealt(items, order=self._shuffle, start=deal.led_at,
                              dealing=self._dealing)
        if deal.start is None:
            self.lead_with_what_is_being_made()
        self._a_row_played_whole_is_its_loop()

    def _a_row_played_whole_is_its_loop(self) -> None:
        current = self.playlist.current()
        whole = self._browse()
        if current is None or current.prompt_id is None or len(whole) <= 1:
            return
        if self._is_one_row([current, *whole]):
            played = self.playlist.in_play_order()
            sat_out = [slide for slide in whole if slide not in played]
            for slide in sat_out:
                self.playlist.add(slide)
            self.loop = Loop(SEED, tuple(rotated_onto([*played, *sat_out], current)))

    def _is_one_row(self, slides) -> bool:
        if not slides:
            return False
        first = slides[0].prompt_id
        row = {first, *(seed.prompt_id for seed in self.neighbors(first).seeds)}
        return all(slide.prompt_id in row for slide in slides)

    def replace_items(self, items, *, keep_slide: bool, shuffle=None,
                      new_set: bool = False) -> bool:
        current = self.playlist.current()
        keep_id = current.prompt_id if keep_slide and current is not None else None
        start = next((index for index, item in enumerate(items)
                      if keep_id is not None and item.prompt_id == keep_id), None)
        self.playlist = dealt(items, order=self._shuffle if shuffle is None else shuffle,
                              start=start, dealing=self._dealing)
        if new_set:
            self.lead_with_what_is_being_made()
            self._a_row_played_whole_is_its_loop()
        kept = start is not None
        self._on_pass_change(kept)
        return kept

    def _browse(self) -> list[Slide]:
        return [item for item in self.all_items if self.passes(item)]

    def set_filters(self, filters: SlideshowFilters) -> bool:
        if filters == self.filters or not self._leaves_something(filters):
            return False
        self._narrow_to(filters)
        self._tell_of_the_filters()
        return True

    def take_up(self, filters: SlideshowFilters, *, keep_the_slide: bool = False) -> None:
        kept = SlideshowFilters()
        for field in fields(SlideshowFilters):
            trial = replace(kept, **{field.name: getattr(filters, field.name)})
            if trial != kept and self._leaves_something(trial):
                kept = trial
        if kept != self.filters:
            self._narrow_to(kept, keep_the_slide=keep_the_slide)

    def _leaves_something(self, filters: SlideshowFilters) -> bool:
        return any(self.passes(item, filters) for item in self.all_items)

    def _narrow_to(self, filters: SlideshowFilters, *, keep_the_slide: bool = False) -> None:
        self.filters = filters
        self.loop = None
        narrowed = [item for item in self.all_items if self.passes(item)]
        current = self.playlist.current()
        if keep_the_slide and current is not None and not self.passes(current):
            narrowed = [current, *narrowed]
        self.replace_items(narrowed, keep_slide=True)

    def _tell_of_the_filters(self) -> None:
        if self._on_filters_change is not None:
            self._on_filters_change(self.filters)

    def set_action_filter(self, query: str) -> bool:
        return self.set_filters(replace(self.filters, action=query))

    def drop_the_filters(self) -> bool:
        if self.filters == SlideshowFilters():
            return False
        self.filters = SlideshowFilters()
        self.loop = None
        self.replace_items(self.all_items, keep_slide=False)
        self._tell_of_the_filters()
        return True

    def retune(self, items, *, enhanced_ids=()) -> None:
        dropped = self.filters != SlideshowFilters()
        self.filters = SlideshowFilters()
        self.reorder(items, latest=False, enhanced_ids=enhanced_ids)
        if dropped:
            self._tell_of_the_filters()

    def reorder(self, items, *, latest: bool, enhanced_ids=(),
                keep_slide: bool = False) -> None:
        self._shuffle = in_order if latest else None
        self.loop = None
        self.library_moved()
        self.all_items = [Slide.of(item) for item in items]
        self.wear(HudFacts(order_label=LATEST_LABEL if latest else SHUFFLE_LABEL,
                           favorite_ids=self.favorite_ids, enhanced_ids=enhanced_ids,
                           enhancing=self.enhance_status))
        kept = [item for item in self.all_items if self.passes(item)]
        if not kept:
            self.filters = SlideshowFilters()
            kept = self.all_items
        self.replace_items(kept, keep_slide=keep_slide, new_set=not keep_slide)

    def passes(self, item, filters: SlideshowFilters | None = None) -> bool:
        filters = self.filters if filters is None else filters
        prompt_id = item.prompt_id
        if filters.favorites and prompt_id not in self.favorite_ids:
            return False
        if filters.enhanced and prompt_id not in self.enhanced_ids:
            return False
        return not filters.action or label_is_filtered(self._named_for(prompt_id), filters.action)

    def _named_for(self, prompt_id) -> str:
        if prompt_id is None or self._actions_of is None:
            return ""
        if prompt_id not in self._named:
            asked = [prompt_id, *(item.prompt_id for item in self.all_items
                                  if item.prompt_id is not None)]
            self._named = {**dict.fromkeys(asked, ""), **self._actions_of(asked)}
        return self._named[prompt_id]

    def remember(self, item) -> None:
        self.library_moved()
        self._take_into_a_looping_row(item)
        for index, kept in enumerate(self.all_items):
            if same_slide(kept, item):
                self.all_items[index] = item
                return
        self.all_items.append(item)

    def _take_into_a_looping_row(self, item: Slide) -> None:
        loop = self.loop
        if (loop is None or loop.axis != SEED or item.prompt_id is None
                or loop.position_of(item) is not None):
            return
        row = self.neighbors(loop.pool[0].prompt_id).seeds
        if any(same_slide(seed, item) for seed in row):
            self.loop = Loop(loop.axis, (*loop.pool, item))

    def forget(self, item) -> None:
        self._forget(lambda kept: same_slide(kept, item))

    def forget_id(self, prompt_id) -> None:
        self._forget(lambda kept: kept.prompt_id == prompt_id)

    def _forget(self, is_gone) -> None:
        self.library_moved()
        self.all_items = [kept for kept in self.all_items if not is_gone(kept)]
        if self.loop is not None:
            kept = tuple(slide for slide in self.loop.pool if not is_gone(slide))
            self.loop = Loop(self.loop.axis, kept) if kept else None

    def whole_set(self) -> list[Slide]:
        return [kept for kept in self.all_items if not kept.is_live]

    def live_ids(self) -> list:
        return [kept.prompt_id for kept in self.all_items if kept.is_live]

    def first_offer_of(self, prompt_id: str) -> bool:
        first = prompt_id not in self._runs_offered
        self._runs_offered.add(prompt_id)
        return first

    def join_live(self, prompt_id: str, frame: bytes) -> bool:
        live = Slide(frame, LIVE, prompt_id)
        self.remember(live)
        return self.passes(live) and self.playlist.add(live)

    def upgrade(self, prompt_id, path, media_type, still):
        for index, kept in enumerate(self.all_items):
            if kept.prompt_id == prompt_id:
                self.all_items[index] = kept.upgraded(path, media_type, still)
                return self.all_items[index]
        return None

    def library_moved(self) -> None:
        self._known.clear()
        self._named.clear()

    def neighbors(self, prompt_id) -> NavMapNeighbors:
        if prompt_id is None or self._neighbors_of is None:
            return NO_NEIGHBORS
        found = self._known.get(prompt_id)
        if found is None:
            found = self._known[prompt_id] = self._neighbors_of(prompt_id)
        return found

    def map(self) -> NavMap | None:
        current = self.playlist.current()
        if current is None:
            return None
        return build_nav_map(current, self.loop, self.neighbors)

    def loop_pool(self, axis: str) -> list[Slide]:
        current = self.playlist.current()
        if current is None:
            return []
        around = self.neighbors(current.prompt_id)
        return [current, *(around.seeds if axis == SEED else around.group)]

    def end_a_loop_of_one(self) -> bool:
        if self.loop is None or len(self.playlist) > 1:
            return False
        return self.end_loop()

    def start_loop(self, axis: str, pool=None) -> bool:
        pool = list(self.loop_pool(axis) if pool is None else pool)
        if len(pool) <= 1:
            return False
        self.loop = Loop(axis, tuple(pool))
        self.replace_items(pool, keep_slide=True, shuffle=as_its_loop)
        return True

    def end_loop(self, fall_back: Callable[[], bool] | None = None) -> bool:
        if self.loop is None:
            return False
        nowhere_to_browse = self._is_one_row(self._browse())
        self.loop = None
        if nowhere_to_browse and fall_back is not None and fall_back():
            return True
        browse = self._browse()
        current = self.playlist.current()
        if current is not None and not any(same_slide(item, current) for item in browse):
            browse = [current, *browse]
        self.replace_items(browse, keep_slide=True)
        return True

    def come_to(self, item_index: int) -> None:
        if (followed := followed_to(
                self.playlist, item_index, passing=self._browse,
                dealing=None if self.loop or self._shuffle else self._dealing)) is not self.playlist:
            self.playlist = followed
            self._on_pass_change(True)

    def step_loop(self, locked: bool, fall_back: Callable[[], bool] | None = None) -> str:
        running = self.loop.axis if self.loop is not None else OFF
        stop = next_stop(standing_at(loop=running, locked=locked),
                         lambda axis: len(self.loop_pool(axis)) > 1)
        if stop == OFF:
            self.end_loop(fall_back)
        elif stop != LOCK:
            self.start_loop(stop)
        return stop

    def more_seeds(self) -> bool:
        current = self.playlist.current()
        if current is None or self._widen is None:
            return False
        additions = tuple(self._widen(current.prompt_id))
        if not additions:
            return False
        return self.start_loop(SEED, [*self.loop_pool(SEED), *additions])

    def state(self, *, locked: bool, version_index: int) -> SlideshowState:
        loop = self.loop or Loop("", ())
        return SlideshowState(order=tuple(self.playlist.order_ids()),
                              current=self.current_prompt_id(), locked=locked,
                              version_index=version_index, loop=loop.axis,
                              loop_pool=tuple(slide.prompt_id for slide in loop.pool))

    def resume(self, state: SlideshowState, *, lead: bool = True) -> bool:
        if pool := self._pool_left_looping(state):
            self.start_loop(state.loop, pool)
        else:
            self.playlist = taken_up(state.order, state.current, passing=self._browse(),
                                     dealt_pass=self.playlist, dealing=self._dealing)
        if not self.playlist.resume(state.order, state.current):
            return False
        if lead and not state.locked:
            self.lead_with_what_is_being_made()
        return True

    def _pool_left_looping(self, state: SlideshowState) -> tuple[Slide, ...]:
        if not state.loop or self._slides_of is None:
            return ()
        pool = tuple(self._slides_of(state.loop_pool))
        return pool if any(slide.prompt_id == state.current for slide in pool) else ()

    def configuration_row(self, query: str) -> Slide | None:
        shown = self.map()
        if shown is None:
            return None
        return next((row.slide for row in shown.column
                     if row.configuration and actions_posted(row.label) == actions_posted(query)),
                    None)

    def slide_for_path(self, path) -> Slide | None:
        shown = self.map()
        cells = (*self.playlist.items, *(shown.cells() if shown is not None else ()),
                 *self.all_items)
        return next((slide for slide in cells if str(slide.path) == str(path)), None)

    def jump_to(self, slide: Slide) -> bool:
        current = self.playlist.current()
        if current is not None and same_slide(current, slide):
            return False
        index = next((index for index, item in enumerate(self.playlist.items)
                      if same_slide(item, slide)), None)
        if index is not None:
            self.playlist.jump_to(index)
            return True
        if self.loop is not None:
            self.end_loop()
        self.playlist.add(slide)
        self.playlist.advance()
        return True

    def nav_target(self, direction: str) -> Slide | None:
        shown = self.map()
        if shown is None:
            return None
        bucket, index = shown.playing
        along_the_row = direction in ("right", "left")
        axis = SEED if along_the_row else ACTION
        if bucket in ("corner", axis):
            cells = (shown.corner, *(shown.seeds if along_the_row else shown.actions))
            at = 0 if bucket == "corner" else index + 1
        else:
            current = self.playlist.current()
            around = self.neighbors(current.prompt_id)
            cells = (current, *(around.seeds if along_the_row
                                else (row.slide for row in around.column)))
            at = 0
        return step_in_ring(cells, at, 1 if direction in ("right", "down") else -1)

    def wear(self, hud: HudFacts) -> None:
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
        if index is None or playlist.order[playlist.index] == index:
            return False
        playlist.lead_with(index)
        return True

    def current_prompt_id(self):
        item = self.playlist.current()
        return item.prompt_id if item is not None else None

    def action_on_screen(self) -> str:
        return self._named_for(self.current_prompt_id())

    @property
    def is_favorite(self) -> bool:
        return self.current_prompt_id() in self.favorite_ids

    def unfavorite_current(self, unfavorite) -> bool:
        prompt_id = self.current_prompt_id()
        if unfavorite is None or prompt_id is None or prompt_id not in self.favorite_ids:
            return False
        unfavorite(prompt_id)
        self.favorite_ids.discard(prompt_id)
        return True


def narrow_to_actions(slideshow_set: SlideshowSet, posted: str) -> tuple[str, bool]:
    actions = actions_posted(posted)
    if not (slideshow_set.set_action_filter(actions) or actions == slideshow_set.filters.action):
        return f"Filter: no matches for '{actions}'", False
    summary = f"'{actions}'" if actions else "cleared"
    return f"Filter: {summary} ({len(slideshow_set.playlist)})", True


def narrow_to_the_action_on_screen(slideshow_set: SlideshowSet) -> tuple[str, bool]:
    action = slideshow_set.action_on_screen()
    if not action:
        return NO_ACTION_ON_SCREEN, False
    return narrow_to_actions(slideshow_set, action)
def item_note(slideshow_set: SlideshowSet, *, versions, version_index: int) -> str:
    if slideshow_set.playlist.current_is_live():
        return GENERATING
    parts = []
    if len(versions) > 1:
        parts.append(versions[version_index][2])
    enhancement = slideshow_set.enhancement_of(slideshow_set.current_prompt_id())
    if enhancement:
        parts.append(_ENHANCEMENT_WORDS[enhancement])
    return " · ".join(parts)


def looping_note(slideshow_set: SlideshowSet) -> str:
    loop = slideshow_set.loop
    return f"{looping_label(loop.axis)}: {len(loop.pool)}"


def thumb_of(slide: Slide) -> str:
    if slide.is_live:
        return ""
    if slide.still:
        return str(slide.still)
    return str(slide.path) if slide.media_type == MediaType.IMAGE else ""
