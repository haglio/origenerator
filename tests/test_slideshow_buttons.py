from __future__ import annotations

import pytest
from funestra.hud_controls import AN_IMAGE, TRASH_TOOLTIP, lock_tooltip
from funestra.hud_title import LATEST_LABEL, SHUFFLE_LABEL

from origenerator.slideshow_buttons import HUD_FACTS, answer, slideshow_rows

THE_ROW = [
    "prev", "nudge_prev", "nudge_next", "next", "funscript_jump", "lock", "trash", "fmode",
    "enhanced", "reset", "shuffle", "latest", "cycle_version"]


def _button_row(**fields) -> tuple:
    return slideshow_rows("portrait", **fields)[-1]


def _names(buttons) -> list[str]:
    return [button.command.removeprefix("portrait_") for button in buttons]


def _by_name(**fields) -> dict:
    row = _button_row(**fields)
    return dict(zip(_names(row), row, strict=True))


def test_the_band_is_the_controls_a_slideshow_answers_in_the_funestras_order():
    assert _names(_button_row()) == THE_ROW


def test_every_button_posts_that_sides_own_verb_and_names_itself():
    for shape in ("portrait", "landscape"):
        for button in slideshow_rows(shape)[-1]:
            assert button.command.startswith(f"{shape}_"), button.command
            assert button.tooltip, button.command


def test_the_band_breaks_into_groups_where_the_controls_stop_being_about_one_thing():
    assert [name for name, button in zip(_names(_button_row()), _button_row(), strict=True) if button.group_break] == [
        "lock", "enhanced", "shuffle", "cycle_version"]


def test_the_switches_light_and_the_things_done_never_do():
    row = _by_name(locked=True, favorites_filter=True, enhanced=True)

    assert row["lock"].lit
    assert row["lock"].favorite
    assert row["fmode"].lit
    assert row["fmode"].favorite
    assert row["enhanced"].lit
    assert row["enhanced"].enhanced
    assert row["trash"].danger
    assert not any(row[name].lit for name in ("prev", "next", "trash", "reset"))
    at_rest = _by_name()
    assert not any(at_rest[name].lit for name in ("lock", "fmode", "enhanced"))


def test_the_order_the_set_plays_in_is_the_one_lit_of_the_pair():
    for order, lit in ((SHUFFLE_LABEL, ["shuffle"]), (LATEST_LABEL, ["latest"])):
        row = _button_row(order=order)
        assert [name for name, button in zip(_names(row), row, strict=True)
                if name in ("shuffle", "latest") and button.lit] == lit, order


class TestTheWords:

    def test_the_controls_both_modes_share_read_as_kino_reads_them(self):
        row = _by_name(has_other_versions=True)

        assert row["prev"].tooltip == "Previous slide"
        assert row["next"].tooltip == "Next slide"
        assert row["nudge_prev"].tooltip.startswith("Back 10s")
        assert row["nudge_next"].tooltip.startswith("Forward 10s")
        assert row["funscript_jump"].tooltip.startswith(
            "Skip ahead to where this slide's scripting starts up again")
        assert row["fmode"].tooltip == "F-Mode — browse only the favorites on this Funestra"
        assert row["shuffle"].tooltip == f"{SHUFFLE_LABEL} — reshuffle what plays"
        assert row["latest"].tooltip == f"{LATEST_LABEL} — reload it newest-first"
        assert row["cycle_version"].tooltip == "Another version of this slide"

    def test_the_lock_and_the_trash_read_as_kinos_and_reset_says_what_it_does_here(self):
        row = _by_name()

        assert row["lock"].tooltip == lock_tooltip(False, "slide")
        assert row["trash"].tooltip == TRASH_TOOLTIP
        assert row["reset"].tooltip.startswith("Reset — ")


class TestTheTenSecondSteps:
    def test_step_a_video_longer_than_ten_seconds(self):
        row = _by_name(longer_than_a_step=True)

        assert [row[step].dim for step in ("nudge_prev", "nudge_next")] == [False, False]

    def test_are_faded_on_a_video_of_ten_seconds_or_shorter_and_say_so(self):
        row = _by_name(longer_than_a_step=False)

        for step in ("nudge_prev", "nudge_next"):
            assert row[step].dim
            assert row[step].tooltip.endswith("(this slide is 10s or shorter)")

    def test_are_faded_on_an_image_and_say_so(self):
        row = _by_name(longer_than_a_step=True, image=True)

        for step in ("nudge_prev", "nudge_next"):
            assert row[step].dim
            assert row[step].tooltip.endswith(f"({AN_IMAGE})")


class TestSkipAhead:
    def test_is_live_with_the_osr2_on_this_funestra_and_a_funscript_on_screen(self):
        assert not _by_name(has_osr2=True, has_funscript=True)["funscript_jump"].dim

    @pytest.mark.parametrize(("has_osr2", "has_funscript", "why"), [
        (False, True, "this Funestra doesn't have the OSR2"),
        (True, False, "this slide has no funscript"),
        (False, False, "this Funestra doesn't have the OSR2 and this slide has no funscript"),
    ])
    def test_is_faded_without_the_osr2_or_a_funscript_and_says_which(
            self, has_osr2, has_funscript, why):
        jump = _by_name(has_osr2=has_osr2, has_funscript=has_funscript)["funscript_jump"]

        assert jump.dim
        assert jump.tooltip.endswith(f"({why})")


def test_reset_is_faded_with_nothing_to_put_back():
    assert _by_name(nothing_to_reset=True)["reset"].dim
    assert not _by_name(nothing_to_reset=False)["reset"].dim


def test_a_hosted_slideshow_offers_the_session_the_way_back_instead_of_minimize():
    rows = slideshow_rows("portrait", hosted=True)
    mode_row = [button.command for button in rows[0]]

    assert mode_row == ["satellites_kino_activate", "origenerator_activate"]
    assert [button.icon for button in rows[0]] == ["Kino", "Origenerator"]
    assert [button.lit for button in rows[0]] == [False, True]
    assert "minimize" not in _names(rows[-1])


def test_a_slideshow_on_its_own_offers_no_minimize_and_no_session_to_switch():
    rows = slideshow_rows("portrait")

    assert len(rows) == 1
    assert "minimize" not in _names(rows[-1])


def test_a_slideshow_handed_to_a_funestra_declares_its_band_and_nothing_around_it():
    rows = slideshow_rows("portrait", hosted=True, own_window=False)

    assert len(rows) == 1
    assert _names(rows[0]) == THE_ROW


class _Host:
    def __init__(self):
        self.calls = []
        self.transport = self

    def slideshow_step(self, delta, *, verb=None):
        self.calls.append(("step", delta) if verb is None else ("step", delta, verb))

    def nudge(self, delta):
        self.calls.append(("nudge", delta))

    def funscript_jump(self):
        self.calls.append("funscript jump")

    def slideshow_toggle_lock(self):
        self.calls.append("lock")

    def set_locked(self, locked):
        self.calls.append(("locked", locked))

    def set_favorites_filter(self, on):
        self.calls.append(("favorites filter", on))

    def slideshow_cull(self):
        self.calls.append("cull")

    def slideshow_reset(self):
        self.calls.append("reset")

    def slideshow_order(self, *, latest):
        self.calls.append(("order", latest))

    def toggle_favorites_filter(self):
        self.calls.append("fmode")

    def toggle_enhanced_mode(self):
        self.calls.append("enhanced")

    def show_item(self, path, *, lock=False):
        self.calls.append(("item", path, lock))

    def slideshow_loop(self, axis):
        self.calls.append(("loop", axis))

    def slideshow_loop_cycle(self):
        self.calls.append("loop key")

    def slideshow_more_seeds(self):
        self.calls.append("more seeds")

    def slideshow_nav(self, direction):
        self.calls.append(("nav", direction))

    def slideshow_filter(self, query):
        self.calls.append(("filter", query))

    def slideshow_filter_to_the_action_on_screen(self):
        self.calls.append("filter to the action on screen")

    def slideshow_step_version(self, delta):
        self.calls.append(("version", delta))

    def clear_modes(self):
        self.calls.append("every narrowing off")


def test_a_state_said_of_a_side_is_asked_for_by_name_rather_than_flipped():
    host = _Host()

    for action in ("lock_on", "lock_off", "fmode_on", "fmode_off"):
        assert answer(host, action), action

    assert host.calls == [("locked", True), ("locked", False),
                          ("favorites filter", True), ("favorites filter", False)]


def test_filter_said_of_a_side_narrows_to_the_action_on_screen():
    host = _Host()

    assert answer(host, "lock_action")

    assert host.calls == ["filter to the action on screen"]


def test_the_versions_button_is_dim_where_the_item_has_only_itself():
    assert _by_name()["cycle_version"].dim
    assert not _by_name(has_other_versions=True)["cycle_version"].dim


def test_every_declared_button_is_answered_by_the_slideshow():
    host = _Host()
    for button in slideshow_rows("portrait", hosted=True, own_window=False)[0]:
        assert answer(host, button.command.removeprefix("portrait_")), button.command

    assert host.calls == [("step", -1), ("nudge", -1), ("nudge", 1), ("step", 1),
                          "funscript jump", "lock", "cull", "fmode", "enhanced", "reset",
                          ("order", False), ("order", True), ("version", -1)]


def test_the_next_scripted_slide_is_a_key_and_a_spoken_word_with_no_button():
    host = _Host()

    assert answer(host, "next_funscripted")

    assert host.calls == [("step", 1, "NEXT_FUNSCRIPTED")]


def test_the_session_tells_a_sides_hud_where_it_sits_and_whether_it_has_the_osr2():
    assert HUD_FACTS == {"hud_corner": "{corner}", "hud_minimized": "{on}", "osr2": "{has}"}
    assert not answer(_Host(), "osr2", "1")


def test_a_map_click_plays_that_item_and_a_double_click_locks_it():
    host = _Host()

    answer(host, "play_video", "scene one.png")
    answer(host, "lock_video", "scene two.png")

    assert host.calls == [("item", "scene one.png", False),
                          ("item", "scene two.png", True)]


def test_the_maps_chrome_loops_the_axes_widens_the_row_and_walks_the_cells():
    host = _Host()

    for action in ("seed_loop", "action_loop", "no_loop", "loop", "more_seeds",
                   "nav_left", "nav_right", "nav_up", "nav_down",
                   "cycle_seed", "cycle_action", "no_filter"):
        assert answer(host, action), action
    assert answer(host, "filter", "dawn")

    assert host.calls == [
        ("loop", "seed"), ("loop", "action"), ("loop", ""), "loop key", "more seeds",
        ("nav", "left"), ("nav", "right"), ("nav", "up"), ("nav", "down"),
        ("nav", "right"), ("nav", "down"), "every narrowing off", ("filter", "dawn"),
    ]


def test_a_press_a_slideshow_has_no_answer_to_says_so():
    host = _Host()

    assert not answer(host, "minimize")
    assert not answer(host, "wrong_action")
    assert host.calls == []


def test_reset_says_what_the_side_goes_back_to_where_it_is_being_shown():
    hosted = next(b for b in _button_row(hosted=True) if b.command == "portrait_reset")
    alone = next(b for b in _button_row() if b.command == "portrait_reset")

    assert "library" in hosted.tooltip
    assert "library" not in alone.tooltip
