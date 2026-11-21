from __future__ import annotations

from funestra.hud_kinds import HudFacts, HudKind, hud_rows

from origenerator.slideshow_buttons import HUD_FACTS, answer


class _Host:
    def __init__(self):
        self.calls = []
        self.transport = self
        self.action_presses = self

    def slideshow_step(self, delta, *, verb=None):
        self.calls.append(("step", delta) if verb is None else ("step", delta, verb))

    def nudge(self, delta):
        self.calls.append(("nudge", delta))

    def funscript_jump(self):
        self.calls.append("funscript jump")

    def back_to_normal_speed(self):
        self.calls.append("normal speed")

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
        self.calls.append("favorites")

    def toggle_enhanced_filter(self):
        self.calls.append("enhanced")

    def set_media(self, included):
        self.calls.append(("media", included))

    def show_item(self, path, *, lock=False):
        self.calls.append(("item", path, lock))

    def switch_to(self, path):
        self.calls.append(("switch", path))

    def slideshow_loop(self, axis):
        self.calls.append(("loop", axis))

    def slideshow_loop_cycle(self):
        self.calls.append("loop key")

    def slideshow_more_seeds(self):
        self.calls.append("more seeds")

    def slideshow_nav(self, direction):
        self.calls.append(("nav", direction))

    def slideshow_cycle(self, axis):
        self.calls.append(("cycle", axis))

    def filter(self, query):
        self.calls.append(("filter", query))

    def filter_to_the_one_on_screen(self):
        self.calls.append("filter to the action on screen")

    def slideshow_step_version(self, delta):
        self.calls.append(("version", delta))

    def clear_filter(self):
        self.calls.append("action filter off")


def test_a_state_said_of_a_side_is_asked_for_by_name_rather_than_flipped():
    host = _Host()

    for action in ("lock_on", "lock_off", "favorites_on", "favorites_off"):
        assert answer(host, action), action

    assert host.calls == [("locked", True), ("locked", False),
                          ("favorites filter", True), ("favorites filter", False)], (
        "a spoken lock, unlock, f mode on or f mode off names the state wanted; a flip would "
        "hand the other one to a speaker who cannot see which way the switch stands")


def test_filter_said_of_a_side_narrows_to_the_action_on_screen():
    host = _Host()

    assert answer(host, "lock_action")

    assert host.calls == ["filter to the action on screen"]


def test_every_declared_button_is_answered_by_the_slideshow():
    host = _Host()
    (row,) = hud_rows(HudKind.SLIDESHOW, HudFacts(funestra="portrait", hosted=True, latest=False, favorites=False))
    for button in row:
        assert answer(host, button.command.removeprefix("portrait_")), button.command

    assert sorted(host.calls, key=repr) == sorted([
        ("step", -1), ("nudge", -1), ("nudge", 1), ("step", 1),
        "funscript jump", "cull", "lock",
        "normal speed", "reset",
        ("order", False), ("order", True),
        ("media", (False, True)), ("media", (True, False)),
        "enhanced", "favorites",
        ("version", -1)], key=repr)


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

    assert host.calls == [("switch", "scene one.png"),
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
        ("cycle", "seed"), ("cycle", "action"), "action filter off", ("filter", "dawn"),
    ]


def test_a_press_a_slideshow_has_no_answer_to_says_so():
    host = _Host()

    assert not answer(host, "minimize")
    assert not answer(host, "made_up_press")
    assert host.calls == []
