from __future__ import annotations

from origenerator.gui.show_pass import rotated_onto


def ahead(playlist, steps: int):
    """The slide *steps* on from the one on screen, around the running pass;
    None when the pass is empty."""
    turned = rotated_onto(playlist.in_play_order(), playlist.current())
    return turned[steps % len(turned)] if turned else None
