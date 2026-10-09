"""What a show tells the players' panel to draw, and which of its presses the show answers itself.

Every show wears the players' own panel: the set and its map
(:mod:`origenerator.gui.show_map`), the device on a host driving one
(:attr:`~origenerator.gui.show_host.ShowHost.hud_device`), and at its foot the
generation queue (:mod:`origenerator.gui.hud_queue`).  A show on a session's
player publishes the model for the session to draw; a show on this app's own
Funestra hands it over in process, and the Funestra draws it.
"""

from __future__ import annotations

from player_core.hud_status import looping_label, status_line
from player_core.satellite_hud import HudCell, HudModel

from origenerator.gui.show_map import SEED_AXIS
from origenerator.gui.show_set import thumb_of
from origenerator.show_buttons import show_rows

# The presses a show answers for itself wherever it is drawn: the two filters,
# reset, the order pair, the loops, the expand mark, the map's own clicks and
# its keys.  The transport is the other half, which a hosted window hands to
# its session instead.
THE_SHOWS_OWN = frozenset({
    "fmode", "enhanced", "reset", "shuffle", "latest", "no_loop", "seed_loop",
    "action_loop", "loop", "more_seeds", "play_video", "lock_video", "filter",
    "no_filter", "nav_left", "nav_right", "nav_up", "nav_down", "cycle_seed",
    "cycle_action",
})

COLLAPSES = {"hud_minimize": True, "hud_restore": False}


def _cell(slide, label: str = "") -> HudCell:
    return HudCell(path="" if slide.is_live else str(slide.path), thumb=thumb_of(slide),
                   label=label)


def show_hud_model(side: str, host, *, hosted: bool = True,
                   own_window: bool = True, device=None, foot=None) -> HudModel | None:
    """The host show's state as the players' HUD model, or ``None`` for a show
    with nothing to map (``hud_map`` unanswered).

    *hosted* and *own_window* decide which buttons the panel declares
    (:func:`~origenerator.show_buttons.show_rows`) and what reset goes back to;
    both default to what a region show wants.  *foot* is the generation queue
    (:mod:`origenerator.gui.hud_queue`) and *device* what this window is doing
    to the OSR2 (:class:`~origenerator.gui.console.ShowDevice`) -- each None
    where there is none, which is what a show on a session's player answers.
    """
    shown = host.hud_map()
    if shown is None:
        return None  # a host with no set under it, and so nothing to map
    locked = host.locked
    favorites_filter = host.hud_favorites_filter
    enhanced = host.hud_enhanced_mode
    order_label = host.hud_order_label
    act_filter = host.hud_act_filter
    return HudModel(
        player=side,
        locked=locked,
        # The line says what the map's light says, in the words a satellite
        # says it in -- the two HUDs are one HUD in two places.  Nothing
        # playing_set when nothing is looping, so a show browsing its set reads
        # "Unlocked · Shuffle" exactly as a satellite browsing its library does;
        # and it names both narrowings beside the rest — F-mode over the
        # favorites, and the enhanced-only switch a show's HUD is the one
        # panel here to carry.
        lock_label=status_line(playing_set=looping_label(shown.loop) if shown.loop else "",
                               locked=locked, order=order_label,
                               f_mode=favorites_filter, enhanced=enhanced,
                               filter_label=act_filter),
        # The players' favorite star, over the same collection the Favorites
        # shelf lists: it lights when the item on screen is a favorite.
        is_favorite=host.hud_is_favorite,
        item_note=host.hud_item_note,
        # The buttons this show answers, in the bands the panel draws them in —
        # which ones depends on what is drawing it.
        rows=(*show_rows(side, locked=locked, favorites_filter=favorites_filter,
                         enhanced=enhanced, order=order_label, hosted=hosted,
                         own_window=own_window,
                         has_other_versions=host.has_other_versions),
              *(device.rows if device is not None else ())),
        # The device's own line and readout, where this window is the one
        # driving: on the panel the set is on, because a show is one host doing
        # both and a second panel underneath said everything twice.
        osr2_rows=device.osr2_rows if device is not None else (),
        osr2=device.osr2 if device is not None else "",
        osr2_control=device.osr2_control if device is not None else "",
        drive=device.drive if device is not None else None,
        max_intensity=device.max_intensity if device is not None else None,
        foot=foot,
        corner=_cell(shown.corner),
        seeds=tuple(_cell(slide) for slide in shown.seeds),
        actions=tuple(_cell(row.slide, row.label) for row in shown.column),
        current_action=shown.label,
        # The act(s) the show is narrowed to, so the rows the filter keeps
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
