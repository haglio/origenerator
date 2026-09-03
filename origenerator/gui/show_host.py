"""What a show answers to — the interface, written down once.

Three things drive whatever is holding a region or sitting behind a console:
the players' own HUD (:mod:`origenerator.gui.show_hud`), the on-video console
(:mod:`origenerator.gui.stroke_panel`), and, inside a session, Fun Time's file
channels (:mod:`origenerator.gui.fun_time_bridge`). They reached it through
sixteen ``hasattr``/``getattr`` probes spread over those three modules, each
re-discovering the interface by guessing at attribute names — and the three did
not agree: the console called five of the names with no guard at all while the
other two guarded every one, so nothing in the repo said which was right.

There are exactly two hosts, and this says what each owes.
:class:`~origenerator.gui.slideshow_view.SlideshowView` has a set and answers
all of it. :class:`~origenerator.gui.slideshow_pace.PaceOnlyHost` is the main
window's console with no show behind it — a pace to set and nothing to step —
so it inherits this and takes the answers below for the half it has no set for.
Those answers are exactly what the probes' defaults used to be, in one place
rather than sixteen.

A caller therefore asks; it does not check first. ``tests/test_show_host.py``
holds that per driver module at zero, and holds both hosts to every member.
"""

from __future__ import annotations

from typing import Protocol


class ShowHost(Protocol):
    """The surface a console, a HUD or a hosting session drives a show through.

    The first six members are the transport, and every host has them for real:
    they are the four buttons and the pace pair that Genau's console, the
    players' HUD and Fun Time's own hotkeys all reach for. The rest are about
    the *set* a show is playing, and carry the answer a host without one gives.
    """

    # --- the transport: what every host answers for itself ------------------

    @property
    def locked(self) -> bool:
        """Whether what is on screen is being held — the console's padlock."""
        ...

    @property
    def dwell_s(self) -> int:
        """The seconds an unheld slide holds the screen; nought means never."""
        ...

    def set_dwell_s(self, seconds: int) -> None:
        """Take a new pace. It is app-wide, so this sets the next show's too."""
        ...

    def stroke_step(self, delta: int) -> None:
        """Move a slide either way — prev/next, however it was pressed."""
        ...

    def stroke_toggle_hold(self) -> None:
        """Hold what is on screen, or let it go."""
        ...

    def stroke_cull(self) -> None:
        """Take what is on screen away and move on."""
        ...

    # --- the set: what a host without one answers ---------------------------

    def stroke_reset(self) -> None:
        """Put the side back how it started. A host with no set never left."""

    def hud_items(self):
        """``(cells, position, locked)`` for the HUD's nav map.

        ``cells`` empty means there is nothing to map, and that is how a host
        with no set says so — :func:`~origenerator.gui.show_hud.show_hud_model`
        reads it and draws no map at all.
        """
        return (), 0, self.locked

    @property
    def hud_f_mode(self) -> bool:
        """Whether the set is narrowed to the favorites. No set, no mode."""
        return False

    @property
    def hud_order_label(self) -> str:
        """The order the set is played in, in the players' own words."""
        return ""

    @property
    def hud_looping(self) -> bool:
        """Whether a set someone asked for is playing round and round.

        True for a host with no set, because that is the answer that leaves the
        map's loop button meaning what it means on a player.
        """
        return True

    @property
    def hud_is_favorite(self) -> bool:
        """Whether the item on screen is starred — the players' star readout."""
        return False

    def toggle_f_mode(self) -> None:
        """Narrow the set to the favorites, or widen it back."""

    def show_item(self, path, *, hold: bool = False) -> None:
        """Jump to the item the HUD map named; *hold* locks it there."""

    def current_media_path(self) -> str:
        """The file on screen — what a hosting session's status file says."""
        return ""
