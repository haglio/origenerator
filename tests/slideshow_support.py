from __future__ import annotations

from origenerator.gui.slideshow_pass import rotated_onto


def ahead(playlist, steps: int):
    turned = rotated_onto(playlist.in_play_order(), playlist.current())
    return turned[steps % len(turned)] if turned else None


def stop_the_poll_to_tick_by_hand(slideshow) -> None:
    slideshow._timer.stop()


def slides_named(*slides):
    named = {slide.prompt_id: slide for slide in slides}
    return lambda prompt_ids: tuple(named[pid] for pid in prompt_ids if pid in named)
