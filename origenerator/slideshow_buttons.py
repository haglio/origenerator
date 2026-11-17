from __future__ import annotations

from collections.abc import Callable
from typing import Any

from funestra.funestra_verbs import NEXT_FUNSCRIPTED
from funestra.hud_overlay import FOOT_DRAG, FOOT_PRESS, FOOT_RELEASE, FOOT_WHEEL
from funestra.inclusion_pair import Included, InclusionPair, enhancement_pair, media_pair
from funestra.loop_cycle import ACTION, SEED

from origenerator.osr2_controls_commands import FILTER

_NEWER, _OLDER = -1, 1


def _inclusion_presses(pair: InclusionPair,
                       press: Callable[[Any, Included], object]) -> dict:
    return {verb.removeprefix("_"): (lambda host, kept=included: press(host, kept))
            for verb, included in pair.asked.items()}


def _reset(host) -> None:
    host.transport.back_to_normal_speed()
    host.slideshow_reset()


_PRESSES: dict[str, Callable[[Any], object]] = {
    "prev": lambda host: host.slideshow_step(-1),
    "next": lambda host: host.slideshow_step(1),
    "nudge_prev": lambda host: host.transport.nudge(-1),
    "nudge_next": lambda host: host.transport.nudge(1),
    "funscript_jump": lambda host: host.transport.funscript_jump(),
    "next_funscripted": lambda host: host.slideshow_step(1, verb=NEXT_FUNSCRIPTED),
    "lock": lambda host: host.slideshow_toggle_lock(),
    "lock_on": lambda host: host.set_locked(True),
    "lock_off": lambda host: host.set_locked(False),
    "trash": lambda host: host.slideshow_cull(),
    "reset": _reset,
    "shuffle": lambda host: host.slideshow_order(latest=False),
    "latest": lambda host: host.slideshow_order(latest=True),
    "fmode": lambda host: host.toggle_favorites_filter(),
    "fmode_on": lambda host: host.set_favorites_filter(True),
    "fmode_off": lambda host: host.set_favorites_filter(False),
    **_inclusion_presses(media_pair(""), lambda host, kept: host.set_media(kept)),
    **_inclusion_presses(enhancement_pair(""), lambda host, kept: host.set_enhancement(kept)),
    "seed_loop": lambda host: host.slideshow_loop("seed"),
    "action_loop": lambda host: host.slideshow_loop("action"),
    "no_loop": lambda host: host.slideshow_loop(""),
    "loop": lambda host: host.slideshow_loop_cycle(),
    "more_seeds": lambda host: host.slideshow_more_seeds(),
    "no_filter": lambda host: host.action_presses.clear_filter(),
    "lock_action": lambda host: host.action_presses.filter_to_the_one_on_screen(),
    "wrong_action": lambda host: host.action_presses.strike_the_one_on_screen(),
    "nav_left": lambda host: host.slideshow_nav("left"),
    "nav_right": lambda host: host.slideshow_nav("right"),
    "nav_up": lambda host: host.slideshow_nav("up"),
    "nav_down": lambda host: host.slideshow_nav("down"),
    "cycle_seed": lambda host: host.slideshow_cycle(SEED),
    "cycle_action": lambda host: host.slideshow_cycle(ACTION),
    "cycle_version": lambda host: host.slideshow_step_version(_NEWER),
    "cycle_version_back": lambda host: host.slideshow_step_version(_OLDER),
    "clip_seconds_up": lambda host: host.step_dwell(1),
    "clip_seconds_down": lambda host: host.step_dwell(-1),
}
_PRESSES_ABOUT_A_FILE: dict[str, Callable[[Any, str], object]] = {
    "play_video": lambda host, path: host.switch_to(path),
    "lock_video": lambda host, path: host.show_item(path, lock=True),
}
HUD_CORNER = "hud_corner"
HUD_MINIMIZED = "hud_minimized"
HAS_THE_OSR2 = "osr2"
HUD_FACTS: dict[str, str] = {HUD_CORNER: "{corner}", HUD_MINIMIZED: "{on}", HAS_THE_OSR2: "{has}"}

PRESSES = tuple(_PRESSES)
PRESSES_ABOUT_THE_SLIDE = frozenset({"trash", "lock_action", "wrong_action", "seed_loop",
                                     "action_loop", "loop", "more_seeds",
                                     "cycle_seed", "cycle_action",
                                     "cycle_version", "cycle_version_back"})
PRESSES_ABOUT_A_FILE = tuple(_PRESSES_ABOUT_A_FILE)
PRESSES_ON_THE_QUEUE = {FOOT_PRESS: "{x}|{y}", FOOT_DRAG: "{x}|{y}", FOOT_RELEASE: "{x}|{y}",
                        FOOT_WHEEL: "{steps}|{x}|{y}"}


def answer(host, action: str, argument: str = "") -> bool:
    if action in _PRESSES:
        _PRESSES[action](host)
    elif action in _PRESSES_ABOUT_A_FILE:
        _PRESSES_ABOUT_A_FILE[action](host, argument)
    elif action in PRESSES_ON_THE_QUEUE:
        host.press_the_queue(action, argument)
    elif action == FILTER:
        host.action_presses.filter(argument)
    else:
        return False
    return True

