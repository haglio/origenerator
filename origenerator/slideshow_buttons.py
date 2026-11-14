from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from funestra.funestra_verbs import NEXT_FUNSCRIPTED
from funestra.hud_button import FIT_THE_WORD, Button
from funestra.hud_controls import (
    RESET_PUTS_BACK_THE_SPEED,
    browse_order_buttons,
    favorites_only_tooltip,
    fmode_button,
    funscript_jump_button,
    lock_button,
    lock_tooltip,
    playback_speed_buttons,
    reset_button,
    transport,
    trash_button,
    versions_button,
)
from funestra.hud_icons import shared_icon
from funestra.hud_overlay import FOOT_DRAG, FOOT_PRESS, FOOT_RELEASE, FOOT_WHEEL
from funestra.hud_title import ENHANCED_LABEL, LATEST_LABEL
from funestra.inclusion_pair import BOTH, Included, InclusionPair, Kind
from funestra.loop_cycle import ACTION, SEED
from funestra.main_hud import VALUE_W

from origenerator.media import MediaType, icon_name
from origenerator.osr2_controls_commands import FILTER

SLIDE = "slide"

ORIGINALS_LABEL = "Originals"


def _pair(shape: str, name: str, first: Kind, second: Kind,
          spelled: tuple[str, str]) -> InclusionPair:
    first_alone, second_alone = spelled
    return InclusionPair(first, second, {
        (True, True): f"{shape}_{name}_both", (True, False): f"{shape}_{name}_{first_alone}",
        (False, True): f"{shape}_{name}_{second_alone}", (False, False): f"{shape}_{name}_none"})


def media_pair(shape: str) -> InclusionPair:
    return _pair(shape, "media", Kind("Images", shared_icon(icon_name(MediaType.IMAGE)), "images"),
                 Kind("Videos", shared_icon(icon_name(MediaType.VIDEO)), "videos"),
                 ("images", "videos"))


def enhancement_pair(shape: str) -> InclusionPair:
    return _pair(shape, "enhancement",
                 Kind(ENHANCED_LABEL, shared_icon("plus"), "enhanced {things}"),
                 Kind(ORIGINALS_LABEL, shared_icon("originals"), "original {things}"),
                 ("enhanced", "originals"))


def _enhancement_buttons(shape: str, included: Included) -> tuple:
    enhanced, originals = enhancement_pair(shape).buttons(included, remembered=False,
                                                          things="items")
    return replace(enhanced, enhanced=True), originals
RESET_TOOLTIPS = {
    True: ("Reset — this shape's whole library back, with both filters off, "
           f"{RESET_PUTS_BACK_THE_SPEED}"),
    False: f"Reset — both filters off, {RESET_PUTS_BACK_THE_SPEED}, and this set from the top",
}


@dataclass(frozen=True, kw_only=True)
class SlideshowFacts:
    locked: bool = False
    favorites_filter: bool = False
    media: Included = BOTH
    enhancement: Included = BOTH
    order: str = ""
    hosted: bool = False
    has_other_versions: bool = False
    clip_seconds: int | None = None
    longer_than_a_step: bool = False
    image: bool = False
    has_funscript: bool = False
    has_osr2: bool = False
    nothing_to_reset: bool = False


def slideshow_rows(shape: str,
                   facts: SlideshowFacts | None = None) -> tuple[tuple[Button, ...], ...]:
    facts = facts or SlideshowFacts()
    row = (
        *transport(shape, noun=SLIDE, longer_than_a_step=facts.longer_than_a_step,
                   image=facts.image),
        funscript_jump_button(f"{shape}_funscript_jump", noun=SLIDE, has_osr2=facts.has_osr2,
                              has_funscript=facts.has_funscript),
        lock_button(shape, locked=facts.locked, tooltip=lock_tooltip(facts.locked, SLIDE)),
        trash_button(shape),
        fmode_button(shape, favorites_only_tooltip(), lit=facts.favorites_filter),
        reset_button(shape, nothing_to_reset=facts.nothing_to_reset,
                     tooltip=RESET_TOOLTIPS[facts.hosted]),
        *browse_order_buttons(shape, latest=facts.order == LATEST_LABEL),
        *media_pair(shape).buttons(facts.media, remembered=False, things="items"),
        *_enhancement_buttons(shape, facts.enhancement),
        versions_button(f"{shape}_cycle_version", noun=SLIDE,
                        has_other_versions=facts.has_other_versions),
    )
    pace = (() if facts.clip_seconds is None
            else (clip_seconds_row(shape, facts.clip_seconds),))
    return (row, *pace)


def clip_seconds_row(shape: str, seconds: int) -> tuple[Button, ...]:
    return (
        Button("", "Clip seconds", "", width=FIT_THE_WORD),
        Button(f"{shape}_clip_seconds_down", shared_icon("minus"), "Move on sooner"),
        Button("", f"{seconds}s", "", width=VALUE_W),
        Button(f"{shape}_clip_seconds_up", shared_icon("plus"), "Leave each clip longer"),
        *playback_speed_buttons(shape, in_a_column_of_labels=False),
    )


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
                                     "action_loop", "loop",
                                     "cycle_seed", "cycle_action"})
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

