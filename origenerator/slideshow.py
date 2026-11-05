from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import NamedTuple

LIVE = "live"


class Slide(NamedTuple):
    path: object
    media_type: str
    prompt_id: str | None = None
    still: object | None = None

    @classmethod
    def of(cls, item) -> Slide:
        return item if isinstance(item, cls) else cls(*item)

    @property
    def is_live(self) -> bool:
        return self.media_type == LIVE

    def upgraded(self, path, media_type=None, still=None) -> Slide:
        return self._replace(
            path=path,
            media_type=self.media_type if media_type is None else media_type,
            still=self.still if still is None else still,
        )


def same_slide(kept: Slide, item: Slide) -> bool:
    return kept is item or (kept.prompt_id is not None and kept.prompt_id == item.prompt_id)


_SAVED_FILTER_NAMES = {"action": "act"}


@dataclass(frozen=True)
class SlideshowFilters:
    favorites: bool = False
    enhanced: bool = False
    action: str = ""

    def saved(self) -> dict:
        return {_SAVED_FILTER_NAMES.get(name, name): value for name, value in asdict(self).items()}

    @classmethod
    def restored(cls, saved) -> SlideshowFilters:
        if not isinstance(saved, dict):
            return cls()
        action = saved.get(_SAVED_FILTER_NAMES["action"])
        return cls(favorites=saved.get("favorites") is True,
                   enhanced=saved.get("enhanced") is True,
                   action=action if isinstance(action, str) else "")


@dataclass(frozen=True)
class SlideshowState:
    order: tuple = ()
    current: str | None = None
    locked: bool = False
    version_index: int = 0
    loop: str = ""
    loop_pool: tuple = ()
    location: str | None = None

    def saved(self) -> dict:
        return asdict(self)

    @classmethod
    def restored(cls, saved) -> SlideshowState:
        if not isinstance(saved, dict):
            return cls()
        version, loop = saved.get("version_index"), saved.get("loop")
        return cls(
            order=_ids_in(saved.get("order")),
            current=_text_in(saved.get("current")),
            locked=saved.get("locked") is True,
            version_index=version if type(version) is int and version > 0 else 0,
            loop=loop if isinstance(loop, str) else "",
            loop_pool=_ids_in(saved.get("loop_pool")),
            location=_text_in(saved.get("location")),
        )


def _text_in(saved) -> str | None:
    return saved if isinstance(saved, str) else None


def _ids_in(saved) -> tuple:
    return (tuple(pid for pid in saved if isinstance(pid, str))
            if isinstance(saved, (list, tuple)) else ())


def _without(indices: list, removed: int) -> list:
    return [i - 1 if i > removed else i for i in indices if i != removed]


def in_order(order: list) -> None: ...


class SlideshowPlaylist:
    def __init__(self, items, *, shuffle=random.shuffle, start=None, order=None):
        self._items = [Slide.of(item) for item in items]
        self._shuffle = shuffle
        self._order = list(range(len(self._items))) if order is None else list(order)
        if order is None:
            self._shuffle(self._order)
        self._pos = (self._order.index(start)
                     if start is not None and 0 <= start < len(self._items) else 0)
        self._waiting: list[int] = []

    def is_empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)

    def current(self):
        return self._items[self._order[self._pos]] if self._items else None

    @property
    def index(self) -> int:
        return self._pos

    @property
    def order(self) -> list:
        return list(self._order)

    @property
    def items(self) -> list:
        return list(self._items)

    def restart(self) -> None:
        self._pos = 0

    def jump_to(self, item_index: int) -> bool:
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
        return [self._items[index] for index in self._order]

    def order_ids(self) -> list:
        return [self._items[index].prompt_id for index in self._order]

    def resume(self, order_ids, current_id) -> bool:
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
        if prompt_id is None:
            return []
        return [index for index, slide in enumerate(self._items)
                if slide.prompt_id == prompt_id]

    def advance(self):
        if self._items:
            self._pos += 1
            if self._pos >= len(self._items):
                self._shuffle(self._order)
                self._pos = 0
            self._seen_on_screen()
        return self.current()

    def back(self):
        if self._items:
            self._pos = (self._pos - 1) % len(self._items)
        return self.current()

    def add(self, item) -> bool:
        slide = Slide.of(item)
        if self.holds(slide.prompt_id):
            return False
        self._items.append(slide)
        self._order.append(len(self._items) - 1)
        self._line_up(len(self._items) - 1)
        return True

    def holds(self, prompt_id) -> bool:
        return bool(self._made_by(prompt_id))

    def live_ids(self) -> list:
        return [slide.prompt_id for slide in self._items
                if slide.is_live and slide.prompt_id is not None]

    def current_is_live(self) -> bool:
        slide = self.current()
        return slide is not None and slide.is_live

    def update_live(self, prompt_id, frame) -> bool:
        live = [index for index in self._made_by(prompt_id)
                if self._items[index].is_live]
        for index in live:
            self._items[index] = self._items[index].upgraded(frame)
        return bool(live)

    def replace_live(self, prompt_id, path, media_type, still=None) -> bool:
        live = [index for index in self._made_by(prompt_id) if self._items[index].is_live]
        if not live:
            return False
        self.replace_item(prompt_id, path, media_type, still)
        for index in live:
            self._line_up(index)
        return True

    def remove_current(self):
        if self._items:
            self._remove(self._order[self._pos])

    def drop(self, prompt_id) -> bool:
        for index in self._made_by(prompt_id):
            self._remove(index)
            return True
        return False

    def _remove(self, index: int) -> None:
        at = self._order.index(index)
        del self._items[index]
        self._order = _without(self._order, index)
        self._waiting = _without(self._waiting, index)
        if at < self._pos:
            self._pos -= 1
        if not self._order or self._pos >= len(self._order):
            self._pos = 0

    def replace_item(self, prompt_id, path, media_type=None, still=None) -> bool:
        found = self._made_by(prompt_id)
        for index in found:
            self._items[index] = self._items[index].upgraded(path, media_type, still)
        return bool(found)

