"""The buttons Origenerator declares on a show's HUD: what each posts, its
face, its tooltip and the state it draws."""
from __future__ import annotations

from origenerator.gui.show_buttons import show_rows


def _band(**fields) -> tuple:
    return show_rows("portrait", **fields)[-1]


def _names(buttons) -> list[str]:
    return [button.action.removeprefix("portrait_") for button in buttons]


def test_the_band_is_the_controls_a_show_answers_in_the_players_order():
    """The step either way, then the three about the item on screen, then what
    narrows the set and the way back out of all of it — the satellites' own
    order, so a reader glancing between two screens finds one panel."""
    assert _names(_band()) == [
        "prev", "next", "lock", "trash", "fmode", "enhanced", "reset", "minimize"]


def test_every_button_posts_that_sides_own_verb_and_names_itself():
    """"portrait_next", "landscape_trash" — the same spelling a satellite's
    band posts, so the session routes a show's press with no new verbs; and
    every glyph on this panel is cryptic on purpose, so each one names itself
    on hover."""
    for side in ("portrait", "landscape"):
        for button in show_rows(side)[-1]:
            assert button.action.startswith(f"{side}_"), button.action
            assert button.tooltip, button.action


def test_the_band_breaks_into_groups_where_the_controls_stop_being_about_one_thing():
    """A run of evenly spaced squares reads as one undifferentiated strip; the
    wider gap opens at the seams the players' own band opens them at."""
    assert [name for name, button in zip(_names(_band()), _band()) if button.group_break] == [
        "lock", "enhanced", "minimize"]


def test_the_switches_light_and_the_things_done_never_do():
    """The hold and the two filters are states the show sits in — the hold and
    F-mode in the favorites' green, the enhanced-only switch in an enhanced
    picture's own amber; a step, the bin and reset are things done."""
    band = dict(zip(_names(_band(locked=True, f_mode=True, enhanced=True)),
                    _band(locked=True, f_mode=True, enhanced=True)))

    assert band["lock"].lit and band["lock"].favorite
    assert band["fmode"].lit and band["fmode"].favorite
    assert band["enhanced"].lit and band["enhanced"].enhanced
    assert band["trash"].danger
    assert not any(band[name].lit for name in ("prev", "next", "trash", "reset", "minimize"))
    at_rest = dict(zip(_names(_band()), _band()))
    assert not any(at_rest[name].lit for name in ("lock", "fmode", "enhanced"))


def test_a_hosted_show_offers_the_session_the_way_back_instead_of_minimize():
    """Hosted, this show covers a satellite player and has no window of its own
    to park, so the mode pair leads the panel with this mode lit — and the
    minimize a player's band ends with is not declared at all."""
    rows = show_rows("portrait", hosted=True)
    mode_row = [button.action for button in rows[0]]

    assert mode_row == ["satellites_video_activate", "origenerator_activate"]
    assert [button.lit for button in rows[0]] == [False, True]
    assert "minimize" not in _names(rows[-1])


def test_a_show_on_its_own_has_a_window_to_park_and_no_session_to_switch():
    """Standalone there is no player under it and no mode to leave, so the pair
    is not drawn — a lit button nothing answers would be a picture of one."""
    rows = show_rows("portrait")

    assert len(rows) == 1
    assert "minimize" in _names(rows[-1])


def test_reset_says_what_the_side_goes_back_to_where_it_is_being_shown():
    """Hosted it is the region's base state — that side's whole library, the
    way a player's reset leaves it browsing its own; standalone there is no
    such state and it is this set from the top."""
    hosted = next(b for b in _band(hosted=True) if b.action == "portrait_reset")
    alone = next(b for b in _band() if b.action == "portrait_reset")

    assert "library" in hosted.tooltip and "library" not in alone.tooltip
