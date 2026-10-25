"""What a slideshow tells the Funestras' panel to draw, and which presses it answers itself.

Every slideshow wears the Funestras' own panel: the set and its map
(:mod:`origenerator.gui.slideshow_map`), the device where this app's window drives
one (:class:`~origenerator.gui.console.SlideshowDevice`), and at its foot the
generation queue (:mod:`origenerator.gui.hud_queue`).  A slideshow on a session's
Funestra publishes the model for the session to draw; a slideshow on this app's own
Funestra hands it over in process, and the Funestra draws it.
"""

from __future__ import annotations

from funestra.hud_title import hud_title, looping_label
from funestra.satellite_hud import HudCell, HudModel

from origenerator.gui.slideshow_map import SEED_AXIS
from origenerator.gui.slideshow_set import thumb_of
from origenerator.slideshow_buttons import slideshow_rows

# The presses a slideshow answers for itself wherever it is drawn: the two filters,
# reset, the order pair, the loops, the expand mark, the map's own clicks and
# its keys, and the versions of the image on screen.  The transport is the
# other half, which a hosted window hands to its session instead.
THE_SLIDESHOWS_OWN = frozenset({
    "fmode", "enhanced", "reset", "shuffle", "latest", "no_loop", "seed_loop",
    "action_loop", "loop", "more_seeds", "play_video", "lock_video", "filter",
    "no_filter", "nav_left", "nav_right", "nav_up", "nav_down", "cycle_seed",
    "cycle_action", "cycle_version", "cycle_version_back",
})

COLLAPSES = {"hud_minimize": True, "hud_restore": False}
OPENS_IN = "hud_restore_at"


def _cell(slide, label: str = "") -> HudCell:
    return HudCell(path="" if slide.is_live else str(slide.path), thumb=thumb_of(slide),
                   label=label)


def slideshow_hud_model(side: str, slideshow, *, hosted: bool = True,
                        own_window: bool = True, device=None, foot=None) -> HudModel | None:
    """The slideshow's state as the Funestras' HUD model, or ``None`` for a slideshow
    with nothing to map (``hud_map`` unanswered).

    *hosted* and *own_window* decide which buttons the panel declares
    (:func:`~origenerator.slideshow_buttons.slideshow_rows`) and what reset goes back to;
    both default to what a region slideshow wants.  *foot* is the generation queue
    (:mod:`origenerator.gui.hud_queue`) and *device* what this window is doing
    to the OSR2 (:class:`~origenerator.gui.console.SlideshowDevice`) -- each None
    where there is none, which is what a slideshow on a session's Funestra answers.
    """
    shown = slideshow.hud_map()
    if shown is None:
        return None  # no set under it, and so nothing to map
    locked = slideshow.locked
    favorites_filter = slideshow.hud_favorites_filter
    enhanced = slideshow.hud_enhanced_mode
    order_label = slideshow.hud_order_label
    act_filter = slideshow.hud_act_filter
    return HudModel(
        funestra=side,
        locked=locked,
        # The title says what the map's light says, in the words a satellite
        # says it in -- the two HUDs are one HUD in two places.  Nothing
        # playing_set when nothing is looping, so a slideshow browsing its set reads
        # "Unlocked · Shuffle" exactly as a satellite browsing its library does;
        # and it names both narrowings beside the rest — F-mode over the
        # favorites, and the enhanced-only switch a slideshow's HUD is the one
        # panel here to carry.
        title=hud_title(playing_set=looping_label(shown.loop) if shown.loop else "",
                        locked=locked, order=order_label,
                        f_mode=favorites_filter, enhanced=enhanced,
                        filters=(act_filter,)),
        # The Funestras' favorite star, over the same items the Favorites
        # collection lists: it lights when the item on screen is a favorite.
        is_favorite=slideshow.hud_is_favorite,
        item_note=slideshow.hud_item_note,
        # The buttons this slideshow answers, in the bands the panel draws them in —
        # which ones depends on what is drawing it.
        rows=(*slideshow_rows(side, locked=locked, favorites_filter=favorites_filter,
                              enhanced=enhanced, order=order_label, hosted=hosted,
                              own_window=own_window,
                              has_other_versions=slideshow.has_other_versions),
              *(device.rows if device is not None else ())),
        # The device's own line and readout, where this window is the one
        # driving: on the panel the set is on, so nothing is said twice.
        osr2_rows=device.osr2_rows if device is not None else (),
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
        # The act(s) the slideshow is narrowed to, so the rows the filter keeps
        # light their buttons and a second press on the row it already is
        # lifts it, exactly as on a satellite.  With no filter on, a seed
        # loop lights the row it is playing, which is what the button on
        # that row says about it.
        filter_query=act_filter or (shown.label if shown.loop == SEED_AXIS else ""),
        seed_count=len(shown.seeds) + 1,
        action_count=len(shown.column) + 1,
        playing=shown.playing,
        active_loop=shown.loop,
    )
