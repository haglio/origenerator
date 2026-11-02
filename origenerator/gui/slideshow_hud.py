from __future__ import annotations

from dataclasses import dataclass

from funestra.hud_title import hud_title, looping_label
from funestra.loop_cycle import SEED
from funestra.satellite_hud import HudCell, HudModel

from origenerator.gui.slideshow_set import thumb_of
from origenerator.slideshow_buttons import SlideshowFacts, slideshow_rows

THE_SLIDESHOWS_OWN = frozenset({
    "fmode", "enhanced", "reset", "shuffle", "latest", "no_loop", "seed_loop",
    "action_loop", "loop", "more_seeds", "play_video", "lock_video", "filter",
    "no_filter", "nav_left", "nav_right", "nav_up", "nav_down", "cycle_seed",
    "cycle_action", "cycle_version", "cycle_version_back", "clip_seconds_up",
    "clip_seconds_down",
})

COLLAPSES = {"hud_minimize": True, "hud_restore": False}
OPENS_IN = "hud_restore_at"


def _cell(slide, label: str = "") -> HudCell:
    return HudCell(path="" if slide.is_live else str(slide.path), thumb=thumb_of(slide),
                   label=label)


@dataclass(frozen=True)
class HudPlacement:
    hosted: bool = True
    own_window: bool = True


USUAL_PLACEMENT = HudPlacement()


def slideshow_hud_model(shape: str, slideshow, placement: HudPlacement = USUAL_PLACEMENT, *,
                        device=None, foot=None) -> HudModel | None:
    shown = slideshow.hud_map()
    if shown is None:
        return None
    locked = slideshow.locked
    favorites_filter = slideshow.hud_favorites_filter
    enhanced = slideshow.hud_enhanced_mode
    order_label = slideshow.hud_order_label
    action_filter = slideshow.hud_action_filter
    return HudModel(
        funestra=shape,
        locked=locked,
        title=hud_title(playing_set=looping_label(shown.loop) if shown.loop else "",
                        locked=locked, order=order_label,
                        f_mode=favorites_filter, enhanced=enhanced,
                        filters=(action_filter,)),
        is_favorite=slideshow.hud_is_favorite,
        item_note=slideshow.hud_item_note,
        rows=slideshow_rows(shape, SlideshowFacts(
            locked=locked, favorites_filter=favorites_filter, enhanced=enhanced,
            order=order_label, hosted=placement.hosted, own_window=placement.own_window,
            has_other_versions=slideshow.has_other_versions, clip_seconds=slideshow.dwell_s,
            has_osr2=device is not None or slideshow.transport.has_osr2,
            **slideshow.transport.row_facts())),
        osr2_rows=device.osr2_rows if device is not None else (),
        osr2_controls=device.osr2_controls if device is not None else (),
        osr2=device.osr2 if device is not None else "",
        osr2_control=device.osr2_control if device is not None else "",
        paused=device.paused if device is not None else False,
        drive=device.drive if device is not None else None,
        max_intensity=device.max_intensity if device is not None else None,
        foot=foot,
        corner=_cell(shown.corner),
        seeds=tuple(_cell(slide) for slide in shown.seeds),
        actions=tuple(_cell(row.slide, row.label) for row in shown.column),
        current_action=shown.label,
        filter_query=action_filter or (shown.label if shown.loop == SEED else ""),
        seed_count=len(shown.seeds) + 1,
        action_count=len(shown.column) + 1,
        playing=shown.playing,
        active_loop=shown.loop,
    )
