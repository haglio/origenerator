from __future__ import annotations

from dataclasses import dataclass

from funestra.hud_kinds import HudFacts, HudKind, slideshow_title
from funestra.hud_title import LATEST_LABEL
from funestra.inclusion_pair import media_pair
from funestra.loop_cycle import SEED
from funestra.satellite_hud import HudCell, HudModel

from origenerator.gui.slideshow_set import thumb_of

THE_SLIDESHOWS_OWN = frozenset({
    *(verb.removeprefix("_") for verb in media_pair("").asked),
    "favorites", "enhanced", "reset", "shuffle", "latest", "no_loop", "seed_loop",
    "action_loop", "loop", "more_seeds", "play_video", "lock_video", "filter",
    "no_filter", "nav_left", "nav_right", "nav_up", "nav_down", "cycle_seed",
    "cycle_action", "cycle_version", "cycle_version_back", "clip_seconds_up",
    "clip_seconds_down", "next_fix", "prev_fix",
})

COLLAPSES = {"hud_minimize": True, "hud_restore": False}
OPENS_IN = "hud_restore_at"


def _cell(slide, label: str = "") -> HudCell:
    return HudCell(path="" if slide.is_live else str(slide.path), thumb=thumb_of(slide),
                   label=label)


@dataclass(frozen=True)
class HudPlacement:
    hosted: bool = True
    drives_the_osr2: bool = False


USUAL_PLACEMENT = HudPlacement()


def slideshow_hud_model(shape: str, slideshow, placement: HudPlacement = USUAL_PLACEMENT, *,
                        foot=None) -> HudModel | None:
    shown = slideshow.hud_map()
    if shown is None:
        return None
    action_filter = slideshow.hud_action_filter
    facts = HudFacts(
        funestra=shape, locked=slideshow.locked, favorite=slideshow.hud_is_favorite,
        favorites=slideshow.hud_favorites_filter, enhanced=slideshow.hud_enhanced_filter,
        latest=slideshow.hud_order_label == LATEST_LABEL, media=slideshow.hud_media,
        hosted=placement.hosted,
        has_other_versions=slideshow.has_other_versions, clip_seconds=slideshow.dwell_s,
        has_osr2=placement.drives_the_osr2 or slideshow.transport.has_osr2,
        **slideshow.transport.row_facts())
    return HudModel(
        funestra=shape,
        locked=facts.locked,
        kind=HudKind.SLIDESHOW,
        facts=facts,
        title=slideshow_title(facts, loop=shown.loop, action_filter=action_filter),
        is_favorite=facts.favorite,
        item_name=slideshow.hud_item_name,
        item_note=slideshow.hud_item_note,
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
