"""What a slideshow answers to — the interface, written down once.

Three things drive whatever is holding a region: the Funestras' own panel
(:mod:`origenerator.gui.slideshow_panel`), the console's clip-seconds pair
(:mod:`origenerator.gui.console`), and, inside a session, Fun Time's file
channels (:mod:`origenerator.fun_time_bridge`). They reached it through
sixteen ``hasattr``/``getattr`` probes spread over those three modules, each
re-discovering the interface by guessing at attribute names — and the three did
not agree: the console called five of the names with no guard at all while the
other two guarded every one, so nothing in the repo said which was right.

There are two hosts, :class:`~origenerator.gui.slideshow_view.SlideshowView`
and :class:`~origenerator.gui.funestra_slideshow.FunestraSlideshow`, and both answer all of
it. A caller therefore asks; it does not check first. ``tests/test_slideshow_host.py``
holds that per driver module at zero, and holds every host to every attribute.
"""

from __future__ import annotations

from typing import Protocol


class SlideshowHost(Protocol):
    """The surface a console, a HUD or a hosting session drives a slideshow through.

    The first six attributes are the transport: the four buttons and the pace
    pair that Genau's console, the Funestras' HUD and Fun Time's own hotkeys all
    reach for. The rest are about the *set* a slideshow is playing.
    """

    # --- the transport ------------------------------------------------------

    @property
    def locked(self) -> bool:
        """Whether what is on screen is locked — the console's padlock."""
        ...

    @property
    def dwell_s(self) -> int:
        """The seconds an unlocked slide holds the screen."""
        ...

    def set_dwell_s(self, seconds: int) -> None:
        """Take a new pace. It is app-wide, so this sets the next slideshow's too."""
        ...

    def slideshow_step(self, delta: int) -> None:
        """Move a slide either way — prev/next, however it was pressed."""
        ...

    def slideshow_toggle_lock(self) -> None:
        """Lock what is on screen, or let it go."""
        ...

    def set_locked(self, locked: bool) -> bool: ...

    def slideshow_cull(self) -> None:
        """Take what is on screen away and move on."""
        ...

    # --- the set ------------------------------------------------------------

    def slideshow_reset(self) -> None:
        """Put the side back how it started."""

    def slideshow_order(self, *, latest: bool) -> None:
        """Play the side's whole library newest first, or shuffled."""

    def slideshow_loop(self, axis: str) -> None:
        """Loop the map's *axis* — "seed" or "action" — around what is on
        screen, or end the loop for ""."""

    def slideshow_loop_cycle(self) -> None:
        """The loop key: seeds, then actions, then off — or the lock, with
        nothing on either axis to loop."""

    def slideshow_more_seeds(self) -> None:
        """Widen the seed row past what exactly matches and loop it."""

    def slideshow_filter(self, query: str) -> None:
        """Narrow the set to the act(s) *query* names, as the button at the
        head of a map row posts them."""

    def slideshow_filter_to_the_act_on_screen(self) -> None: ...

    def clear_modes(self) -> bool:
        """Every narrowing off at once — the favorites, the enhanced ones and
        the act filter — which is what "no filter" means said to a slideshow.
        ``False`` where nothing moved."""
        ...

    def slideshow_nav(self, direction: str) -> None:
        """Step to the map cell one *direction* from the lit one."""

    def hud_map(self):
        """The map the HUD draws around what is on screen
        (:class:`~origenerator.gui.slideshow_map.SlideshowMap`), which says which of its
        axes is looping — or ``None`` for nothing to map, which
        :func:`~origenerator.gui.slideshow_panel.slideshow_hud_model` reads as no map at all.
        """

    @property
    def hud_favorites_filter(self) -> bool:
        """Whether the set is narrowed to the favorites."""
        ...

    @property
    def hud_act_filter(self) -> str:
        """The act(s) the set is narrowed to, as the Funestras' HUD posts them
        — what lights the map's row buttons."""
        ...

    @property
    def hud_order_label(self) -> str:
        """The order the set is played in, in the Funestras' own words."""
        ...

    @property
    def hud_device(self):
        """What this window is doing to the OSR2, as the one panel a slideshow wears
        takes it (:class:`~origenerator.gui.console.SlideshowDevice`) — or None where
        this app is not the one driving.

        The slideshow is one host doing two things: browsing a set and driving the
        device.  It wore two panels for that, the Funestras' HUD over the set and
        Genau's whole console under it, which said the status twice and drew
        prev/next/lock/trash twice.  One panel now, and this is the half of it
        the host answers for.
        """
        ...

    def press_console(self, action: str) -> bool:
        """Do what a press on the console's own rows asks — the pace, the
        motion, the OSR2 switch, a level dragged on the readout —
        and say whether this was one of those verbs at all.

        False for a host with no device to drive, which leaves the panel to
        route the press the way it routes every other.
        """
        ...

    @property
    def hud_is_favorite(self) -> bool:
        """Whether the item on screen is favorited — the Funestras' star readout."""
        ...

    @property
    def hud_item_note(self) -> str: ...

    def toggle_favorites_filter(self) -> None:
        """Narrow the set to the favorites, or widen it back."""

    def set_favorites_filter(self, on: bool) -> bool: ...

    @property
    def hud_enhanced_mode(self) -> bool:
        """Whether the set is narrowed to the pictures this app has enhanced —
        the switch beside F-mode."""
        ...

    def toggle_enhanced_mode(self) -> bool:
        """Flip that switch — the HUD's own button, and the session console's.

        ``False`` where the switch did not move, which is the answer a set with
        nothing enhanced in it gives to being narrowed.
        """
        ...

    def set_enhanced_mode(self, on: bool) -> bool:
        """Put that switch a named way rather than flipping it — what a caller
        moving two regions together needs, since a flip each could leave them
        disagreeing.  ``False`` where it did not move."""
        ...

    def show_item(self, path, *, lock: bool = False) -> None:
        """Jump to the item the HUD map named; *lock* keeps it there."""

    @property
    def hud_queue(self) -> tuple[list, int]:
        """What is in flight here and how much of ComfyUI's queue is another
        app's, for the block the panel hangs at its foot
        (:mod:`origenerator.gui.hud_queue`)."""
        ...

    def set_audio_muted(self, muted: bool) -> None:
        """Silence this slideshow, or let it be heard."""

    def requeue(self, keys) -> None:
        """Re-line the queue in this order — a row dragged down the block."""

    def clear_foreign_queue(self) -> None:
        """Drop another app's work off ComfyUI, as that block's Clear asks."""
