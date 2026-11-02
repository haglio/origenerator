from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from funestra.hud_title import SHUFFLE_LABEL
from funestra.volume import VolumeHud

from origenerator.slideshow import SlideshowFilters


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
    slides: Callable[[tuple], tuple] | None = None
    filters_changed: Callable[[SlideshowFilters], None] | None = None
    volume_moved: Callable[[VolumeHud], None] | None = None


@dataclass(frozen=True)
class HudFacts:
    order_label: str = SHUFFLE_LABEL
    favorite_ids: Collection[str] = field(default_factory=frozenset)
    enhanced_ids: Collection[str] = field(default_factory=frozenset)
    enhancing: Mapping[str, str] = field(default_factory=dict)
