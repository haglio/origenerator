from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from funestra.hud_title import SHUFFLE_LABEL
from funestra.volume import VolumeHud

from origenerator.slideshow import Slide, SlideshowFilters


@dataclass(frozen=True)
class SlideshowActions:
    delete: Callable[[str], None] | None = None
    enhance: Callable[[str], bool] | None = None
    favorite: Callable[[str], None] | None = None
    unfavorite: Callable[[str], None] | None = None
    lock: Callable[[str], None] | None = None
    reset: Callable[[object], None] | None = None
    at_base: Callable[[object], bool] | None = None
    reorder: Callable[[object, bool], bool] | None = None
    browse_all: Callable[[object], bool] | None = None
    queue_now: Callable[[], tuple[list, int]] | None = None
    move: Callable[[str, str | None], None] | None = None
    clear_queue: Callable[[], None] | None = None
    start_now: Callable[[], None] | None = None
    cancel_all: Callable[[], None] | None = None
    core_window: Callable[[], object] | None = None
    drive_toggle: Callable[[], None] | None = None
    osr2_control: object | None = None
    omnipause: Callable[[], None] | None = None
    move_hud: Callable[[str], None] | None = None
    neighbors: Callable[[str], object] | None = None
    widen: Callable[[str], tuple] | None = None
    actions_of: Callable[[list], dict] | None = None
    strike_action: Callable[[Slide], str] | None = None
    slides: Callable[[tuple], tuple] | None = None
    filters_changed: Callable[[SlideshowFilters], None] | None = None
    volume_moved: Callable[[VolumeHud], None] | None = None


@dataclass(frozen=True)
class HudFacts:
    order_label: str = SHUFFLE_LABEL
    favorite_ids: Collection[str] = field(default_factory=frozenset)
    enhanced_ids: Collection[str] = field(default_factory=frozenset)
    enhancing: Mapping[str, str] = field(default_factory=dict)


def _led_at(opening, start: int | None) -> int | None:
    return opening.lead if opening is not None else start


def _neighbors_known(opening) -> dict:
    if opening is None or opening.lead_neighbors is None:
        return {}
    return {opening.items[opening.lead][2]: opening.lead_neighbors}


@dataclass(frozen=True)
class SetDeal:
    shuffle: object = None
    start: int | None = None
    opening: object = None

    @property
    def led_at(self) -> int | None:
        return _led_at(self.opening, self.start)

    def neighbors_known(self) -> dict:
        return _neighbors_known(self.opening)


NO_DEAL = SetDeal()


@dataclass(frozen=True)
class Listing:
    location: str | None = None
    rows: tuple = ()
    shown: tuple[str, ...] = ()
    picked: tuple[str, ...] = ()
    subject: str = "this folder"
    shape: str = ""
    latest: bool = False


@dataclass(frozen=True)
class DirectorSources:
    db: object
    jobs: object
    names: object
    library: Callable[[], object]
    listing: Callable[[], Listing]


@dataclass(frozen=True)
class DirectorSurroundings:
    pace: object
    motion: object
    fun_time: object
    radio: object = None
    buttons_of: Callable | None = None


@dataclass(frozen=True)
class Showing:
    actions: SlideshowActions
    hud: HudFacts
    versions: dict
    opening: object = None


@dataclass(frozen=True)
class Carrying:
    folder_items: list | None = None
    resume: object = None
    filters: SlideshowFilters | None = None
    versions: dict | None = None


NOTHING_CARRIED = Carrying()
