"""What a show answers to — the interface, written down once.

Three things drive whatever is holding a region or sitting under a console:
the players' own HUD (:mod:`origenerator.gui.show_hud`), the on-video console
(:mod:`origenerator.gui.motion_panel`), and, inside a session, Fun Time's file
channels (:mod:`origenerator.gui.fun_time_bridge`). They reached it through
sixteen ``hasattr``/``getattr`` probes spread over those three modules, each
re-discovering the interface by guessing at attribute names — and the three did
not agree: the console called five of the names with no guard at all while the
other two guarded every one, so nothing in the repo said which was right.

There are exactly two hosts, and this says what each owes.
:class:`~origenerator.gui.slideshow_view.SlideshowView` has a set and answers
all of it. :class:`~origenerator.gui.slideshow_pace.PaceOnlyHost` is the main
window's console with no show under it — a pace to set and nothing to step —
so it inherits this and takes the answers below for the half it has no set for.
Those answers are exactly what the probes' defaults used to be, in one place
rather than sixteen.

A caller therefore asks; it does not check first. ``tests/test_show_host.py``
holds that per driver module at zero, and holds both hosts to every attribute.
"""

from __future__ import annotations

from typing import Protocol


class ShowHost(Protocol):
    """The surface a console, a HUD or a hosting session drives a show through.

    The first six attributes are the transport, and every host has them for real:
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

    def show_step(self, delta: int) -> None:
        """Move a slide either way — prev/next, however it was pressed."""
        ...

    def show_toggle_hold(self) -> None:
        """Hold what is on screen, or let it go."""
        ...

    def show_cull(self) -> None:
        """Take what is on screen away and move on."""
        ...

    # --- the set: what a host without one answers ---------------------------

    def show_reset(self) -> None:
        """Put the side back how it started. A host with no set never left."""

    def show_order(self, *, latest: bool) -> None:
        """Play the side's whole library newest first, or shuffled."""

    def show_loop(self, axis: str) -> None:
        """Loop the map's *axis* — "seed" or "config" — around what is on
        screen, or end the loop for "".  No set, nothing to loop."""

    def show_loop_cycle(self) -> None:
        """The loop key: seeds, then configs, then off — or the hold, with
        nothing on either axis to loop."""

    def show_more_seeds(self) -> None:
        """Widen the seed row past the exact configuration and loop it."""

    def show_filter(self, query: str) -> None:
        """Narrow to the configuration whose map row is labeled *query*: jump
        to it and loop its seed row."""

    def show_nav(self, direction: str) -> None:
        """Step to the map cell one *direction* from the lit one."""

    def hud_map(self):
        """The map the HUD draws around what is on screen
        (:class:`~origenerator.gui.show_map.ShowMap`), which says which of its
        axes is looping — or ``None`` for nothing to map, which is how a host
        with no set says so, and what
        :func:`~origenerator.gui.show_hud.show_hud_model` reads as no map at all.
        """

    @property
    def hud_f_mode(self) -> bool:
        """Whether the set is narrowed to the favorites. No set, no mode."""
        return False

    @property
    def hud_order_label(self) -> str:
        """The order the set is played in, in the players' own words."""
        return ""

    @property
    def hud_is_favorite(self) -> bool:
        """Whether the item on screen is starred — the players' star readout."""
        return False

    def toggle_f_mode(self) -> None:
        """Narrow the set to the favorites, or widen it back."""

    @property
    def hud_enhanced_mode(self) -> bool:
        """Whether the set is narrowed to the pictures this app has enhanced —
        the switch beside F-mode.  No set, no mode."""
        return False

    def toggle_enhanced_mode(self) -> bool:
        """Flip that switch — the HUD's own button, and the session console's.

        ``False`` where the switch did not move, which is the answer a host with
        no set always gives and the answer a set with nothing enhanced in it
        gives to being narrowed.
        """
        return False

    def set_enhanced_mode(self, on: bool) -> bool:
        """Put that switch a named way rather than flipping it — what a caller
        moving two regions together needs, since a flip each could leave them
        disagreeing.  ``False`` where it did not move."""
        return False

    def show_item(self, path, *, hold: bool = False) -> None:
        """Jump to the item the HUD map named; *hold* locks it there."""

    def current_media_path(self) -> str:
        """The file on screen — what a hosting session's status file says."""
        return ""
