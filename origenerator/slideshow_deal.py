from __future__ import annotations

import random
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from app_support.watch_weights import (
    NEUTRAL_WEIGHT,
    Staying,
    dealt_by_weight,
    newest_of_each_group,
)

from origenerator.slideshow import Slide, SlideshowFilters, SlideshowPlaylist, in_order, same_slide

_DEALER = random.Random()


def _never(*_args) -> bool:
    return False


def as_its_loop(order: list) -> None: ...


@dataclass(frozen=True)
class Dealing:
    weight_of: Callable[[object], float] | None = None
    group_of: Callable[[Slide, bool], Hashable | None] | None = None
    filters_of: Callable[[], SlideshowFilters] = SlideshowFilters
    stays: Callable[[Slide], bool] = _never

    def weight(self, slide: Slide) -> float:
        return self.weight_of(slide.path) if self.weight_of is not None else NEUTRAL_WEIGHT

    def group(self, slide: Slide) -> Hashable | None:
        if self.group_of is None:
            return None
        return self.group_of(slide, bool(self.filters_of().action))


def dealt(items, *, order, start, dealing: Dealing) -> SlideshowPlaylist:
    if order is None:
        return shuffled_by_weight(items, start=start, dealing=dealing)
    if order is in_order:
        return newest_first(items, start=start, dealing=dealing)
    return SlideshowPlaylist(items, shuffle=order, start=start)


def taken_up(order_ids, current_id, *, passing, dealt_pass: SlideshowPlaylist,
             dealing: Dealing) -> SlideshowPlaylist:
    by_id = {slide.prompt_id: slide for slide in passing}
    if current_id not in by_id:
        return dealt_pass
    remembered = newest_of_each_group(
        [by_id[pid] for pid in order_ids if pid in by_id], dealing.group,
        kept=lambda slide: slide.prompt_id == current_id)
    taken = {dealing.group(slide) for slide in remembered} - {None}
    fresh = [slide for slide in dealt_pass.in_play_order()
             if slide not in remembered and dealing.group(slide) not in taken]
    return _played_in([*remembered, *fresh], passing)


def followed_to(playlist: SlideshowPlaylist, item_index: int, *,
                passing: Callable[[], list[Slide]],
                dealing: Dealing | None) -> SlideshowPlaylist:
    playlist.jump_to(item_index)
    if dealing is None or len(playlist) <= 1 or playlist.index != len(playlist) - 1:
        return playlist
    current = playlist.current()
    passes = passing()
    following = [slide for slide in dealt(passes, order=None, start=None,
                                           dealing=dealing).in_play_order()
                 if not same_slide(slide, current)]
    return _played_in([current, *following], passes)


def shuffled_by_weight(items, *, start, dealing: Dealing) -> SlideshowPlaylist:
    slides = [Slide.of(item) for item in items]
    on_screen = _on_screen(slides, start)
    picks = dealt_by_weight(slides, weight_of=dealing.weight, group_of=dealing.group,
                            rng=_DEALER, staying=Staying(
                                kept=lambda slide: slide == on_screen or dealing.stays(slide),
                                never_empty=True))
    playlist = _played_in(picks, slides)
    if on_screen in picks:
        playlist.lead_with(playlist.items.index(on_screen))
    return playlist


def _played_in(play_order: list[Slide], set_order: list[Slide]) -> SlideshowPlaylist:
    place = {id(slide): at for at, slide in enumerate(set_order)}
    items = sorted(play_order, key=lambda slide: place.get(id(slide), len(place)))
    rank = {id(slide): at for at, slide in enumerate(items)}
    return SlideshowPlaylist(items, shuffle=in_order,
                             order=[rank[id(slide)] for slide in play_order])


def newest_first(items, *, start, dealing: Dealing) -> SlideshowPlaylist:
    slides = [Slide.of(item) for item in items]
    on_screen = _on_screen(slides, start)
    kept = newest_of_each_group(slides, dealing.group,
                                kept=lambda slide: slide == on_screen or dealing.stays(slide))
    return SlideshowPlaylist(kept, shuffle=in_order,
                             start=kept.index(on_screen) if on_screen in kept else None)


def _on_screen(slides: list[Slide], start: int | None) -> Slide | None:
    return slides[start] if start is not None and 0 <= start < len(slides) else None
