"""The buttons Origenerator declares on a show's HUD: what each posts, its
face, its tooltip and the state it draws."""
from __future__ import annotations

from origenerator.gui.show_buttons import answer, show_rows


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


def test_a_show_handed_to_a_player_declares_its_band_and_nothing_around_it():
    """The player's window is the session's, so minimize is the session's; and
    the mode pair is on the panel the session draws around this band, not in
    it.  What is left is exactly what the show itself answers."""
    rows = show_rows("portrait", hosted=True, own_window=False)

    assert len(rows) == 1
    assert _names(rows[0]) == [
        "prev", "next", "lock", "trash", "fmode", "enhanced", "reset"]


class _Host:
    """A show reduced to the calls a press can make of one."""

    def __init__(self, *, looping=True):
        self.hud_looping = looping
        self.calls = []

    def show_step(self, delta):
        self.calls.append(("step", delta))

    def show_toggle_hold(self):
        self.calls.append("hold")

    def show_cull(self):
        self.calls.append("cull")

    def show_reset(self):
        self.calls.append("reset")

    def toggle_f_mode(self):
        self.calls.append("fmode")

    def toggle_enhanced_mode(self):
        self.calls.append("enhanced")

    def show_item(self, path, *, hold=False):
        self.calls.append(("item", path, hold))


def test_every_declared_button_is_answered_by_the_show():
    """A button this panel declares and nothing answers would be drawn dead —
    so every one of them, minimize aside, reaches the show."""
    host = _Host()
    for button in show_rows("portrait", hosted=True, own_window=False)[0]:
        assert answer(host, button.action.removeprefix("portrait_")), button.action

    assert host.calls == [("step", -1), ("step", 1), "hold", "cull", "fmode",
                          "enhanced", "reset"]


def test_a_map_click_plays_that_item_and_a_double_click_holds_it():
    host = _Host()

    answer(host, "play_video", "scene one.png")
    answer(host, "lock_video", "scene two.png")

    assert host.calls == [("item", "scene one.png", False),
                          ("item", "scene two.png", True)]


def test_the_loop_button_ends_a_loop_and_starts_none():
    """Stop looping this row: a show asked for goes back to the side's base
    state, the way the press ends a loop on a player — and pressed where
    nothing is looping it is the dark button it looks like."""
    looping, browsing = _Host(looping=True), _Host(looping=False)

    for host in (looping, browsing):
        answer(host, "no_loop")
        answer(host, "seed_loop")

    assert looping.calls == ["reset", "reset"]
    assert browsing.calls == []


def test_a_press_a_show_has_no_answer_to_says_so():
    """Minimize parks a window, which is not the show's to answer; nor is the
    map's chrome for acts and seeds a show does not have."""
    host = _Host()

    assert not answer(host, "minimize")
    assert not answer(host, "more_seeds")
    assert host.calls == []


def test_reset_says_what_the_side_goes_back_to_where_it_is_being_shown():
    """Hosted it is the region's base state — that side's whole library, the
    way a player's reset leaves it browsing its own; standalone there is no
    such state and it is this set from the top."""
    hosted = next(b for b in _band(hosted=True) if b.action == "portrait_reset")
    alone = next(b for b in _band() if b.action == "portrait_reset")

    assert "library" in hosted.tooltip and "library" not in alone.tooltip
