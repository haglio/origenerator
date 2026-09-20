"""The satellite lock HUD, worn by every fullscreen show — the players' own.

A show covering a satellite region covers that player's HUD, and what replaced
it used to be a small strip of Qt buttons that only gestured at the real thing.
This widget draws the REAL thing: the same panel the players composite into
their video, rendered by the same shared code (``player_core.satellite_hud`` /
``_paint``), so a show's HUD and a player's HUD cannot drift apart — the status
line, the buttons this show declares (:mod:`origenerator.gui.show_buttons`) and
the nav map.

Standalone Origenerator wears it too, over its own fullscreen show.  Nothing
about a show is different for not being inside a session: it is the same set,
played the same way, out of the same window, and this is the one panel this
family of apps has for saying so.  What a standalone show has no counterpart
for is the pair of things that address a SESSION, and each is answered rather
than faked — see :func:`show_hud_model` for the mode row and
:meth:`ShowHud._act_here` for the transport.

The map speaks the players' vocabulary because the show's set IS those
concepts: the set's first item anchors the corner, the rest run right as the
seed row with their real ordinals ("Seed 2" over the second item), the counts
corner says "Seeds: N" for the whole set, and the cell actually on screen is
the lit one — exactly a satellite playing through a seed family.  A thumbnail
click jumps the show to that item, the way a map click switches a player.

It is the ONE panel a show wears.  Fun Time splits what is here across two
windows — each satellite's HUD for the set, the main player's console for the
device — because there they are two players; a show is one host doing both, and
wearing both panels put two status lines that disagreed on one screen with
prev/next/lock/trash drawn on each.  So the host hands over its device half
(:attr:`~origenerator.gui.show_host.ShowHost.hud_device`) and it rides here,
under the control band: the clip-seconds pace, the motion's hands-free row and
the four OSR2 control states, then the line naming whichever driver has the
device and the readout of what is being sent, all the main console's own code.

Presses that mean something to the session — the mode pair, this side's
prev/next/lock/trash — post onto the dashboard command file, the channel the
players' HUDs and the global hotkeys share.  The two filter switches — F-mode,
and the enhanced-only switch beside it that only a show's HUD grows — are the
show's own and land on it directly, hosted or not (:meth:`ShowHud._deliver`), and
so is everything about the device: the OSR2 is this app's to drive wherever the
show is drawn, so those go back to the host
(:meth:`~origenerator.gui.show_host.ShowHost.press_console`) rather than out to
the session.  The map's own chrome is the panel's rather than this show's, so a
press on a concept a hosted show does not have (the loops) is swallowed here,
where it can never reach the blacked player underneath.
"""

from __future__ import annotations

import time

from player_core.file_channel import append_command
from player_core.hud_status import looping_label, status_line
from player_core.modes import Osr2State
from player_core.satellite_hud import (
    MARGIN,
    HudCell,
    HudClicks,
    HudModel,
    HudTargets,
)
from player_core.satellite_hud_paint import HudRenderer
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui.console import REPAINT_MS
from origenerator.gui.media_overlay import float_over_media, raise_over_media
from origenerator.gui.show_buttons import answer, show_rows
from origenerator.ui_scale import (
    to_bitmap_pos,
    to_logical_size,
    unscaled_pixmap,
)

_REFRESH_MS = 300  # the players re-read their published panel on a tick too

# The two states with a line that moves: something is being sent, so the trace
# scrolls and the panel has to keep up with it.
_MOVING = frozenset({Osr2State.ROBOT_HAND, Osr2State.FUNSCRIPT})

# The presses a show answers for itself wherever it is drawn.  The transport is
# the other half, which a hosted window hands to its session instead.
_THE_SHOWS_OWN = frozenset({"fmode", "enhanced", "reset", "shuffle", "latest",
                            "no_loop", "seed_loop", "play_video", "lock_video"})


def show_hud_model(side: str, host, *, hosted: bool = True,
                   own_window: bool = True, device=None) -> HudModel | None:
    """The host show's state as the players' HUD model, or ``None`` for a show
    with nothing to map (``hud_items`` empty or unanswered).

    *hosted* is whether a Fun Time session is under the show and *own_window*
    whether this app is drawing it in a window of its own; together they decide
    which buttons the panel declares (see
    :func:`~origenerator.gui.show_buttons.show_rows`) and what reset goes back
    to.  Both default to what a region show wants, which is what every reading
    of one wants; :class:`ShowHud` and a show handed to a player pass their own.

    *device* is what this window is doing to the OSR2
    (:class:`~origenerator.gui.console.ShowDevice`), for the one panel a show
    wears in a window of its own: the pace and motion rows under the control
    band, who has the device, and the readout.  None where this app is not the
    one driving -- a show handed to a session's player, whose device half is on
    the session's own main console, and any reading of the model that only wants
    the set.
    """
    cells, position, locked = host.hud_items()
    if not cells:
        return None  # a host with no set under it, and so nothing to map
    hud_cells = tuple(
        HudCell(path=str(path), thumb=str(thumb) if thumb else "")
        for path, thumb in cells
    )
    favorites_filter = host.hud_favorites_filter
    enhanced = host.hud_enhanced_mode
    order_label = host.hud_order_label
    # A show someone ASKED for is a loop -- this set, played round and round --
    # and the map's loop button is lit for it.  A region's base state is not:
    # it is that side browsing its whole library, exactly what a satellite does
    # with no loop on, so the button is dark and the line just names the order.
    looping = host.hud_looping
    # The line says what the light says, in the words a satellite says it in --
    # the two HUDs are one HUD in two places.  Nothing playing_set when nothing
    # is looping, so the base state reads "Unlocked · Shuffle" exactly as a
    # satellite browsing its library does.
    return HudModel(
        player=side,
        locked=locked,
        # The line names both narrowings beside the rest — F-mode over the
        # favorites, and the enhanced-only switch a show's HUD is the one panel
        # here to carry.
        lock_label=status_line(playing_set=looping_label("seed") if looping else "",
                               locked=locked, order=order_label,
                               f_mode=favorites_filter, enhanced=enhanced),
        # The players' favorite star, over the same collection the Favorites
        # shelf lists: it lights when the item on screen is a favorite.
        is_favorite=host.hud_is_favorite,
        # The buttons this show answers, in the bands the panel draws them in —
        # which ones depends on what is drawing it.
        rows=(*show_rows(side, locked=locked, favorites_filter=favorites_filter,
                         enhanced=enhanced, order=order_label, hosted=hosted,
                         own_window=own_window,
                         has_other_versions=host.has_other_versions),
              *(device.rows if device is not None else ())),
        # The device's own line and readout, where this window is the one
        # driving: on the panel the set is on, because a show is one host doing
        # both and a second panel underneath said everything twice.
        osr2_rows=device.osr2_rows if device is not None else (),
        osr2=device.osr2 if device is not None else "",
        osr2_control=device.osr2_control if device is not None else "",
        drive=device.drive if device is not None else None,
        corner=hud_cells[0],
        seeds=hud_cells[1:],
        seed_count=len(hud_cells),
        playing=("corner", 0) if position <= 1 else ("seed", position - 2),
        # Lit only while a set someone asked for is playing: on a player the
        # button starts a loop, and here that loop is already what is
        # happening, so the light says so and a press ends it — the button
        # meaning the same thing on both, "stop looping this row".  Dark in the
        # base state, where nothing is being looped.
        active_loop="seed" if looping else "",
    )


class ShowHud(QLabel):
    """One show's HUD: model from the host, bitmap from the shared renderer."""

    def __init__(self, host: QWidget, *, side: str, dashboard_cmd_file,
                 label_for=None):
        super().__init__(host)
        self._host = host
        self._side = side
        # What to call the item on screen, in the app's OWN vocabulary — a
        # callable taking the media path, or None to say nothing.  The gallery
        # supplies it because naming a generation takes the database (see
        # GalleryView._show_item_label).
        self._label_for = label_for
        # The session's command channel, or ``None`` standalone — which is also
        # how this HUD knows which of the two it is on (see :meth:`_deliver`).
        self._dashboard_cmd_file = dashboard_cmd_file
        self._renderer = HudRenderer(side)
        self._clicks = HudClicks(side)
        self._targets: HudTargets | None = None
        self._model: HudModel | None = None
        self._hover_loop = ""
        self._hover_tip = ""
        self._hover_pos = (0, 0)
        self.setMouseTracking(True)  # hover tooltips render into the bitmap
        # Its map is clicked and hovered, so the mouse stops here.
        float_over_media(self, click_through=False)
        # The players' own inset, in DEVICE pixels: this panel swaps in and out
        # with the player's HUD under it, so the two have to sit on the same
        # corner or the swap reads as a jump.  move() takes logical pixels, and
        # left unconverted the scale pulled this one 4px in from the corner
        # against the player's 12.
        self.move(to_logical_size(MARGIN), to_logical_size(MARGIN))
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()
        self.show()

    # --- model in, pixels out ---------------------------------------------

    def _tick(self) -> None:
        model = show_hud_model(self._side, self._host,
                               hosted=self._dashboard_cmd_file is not None,
                               device=self._host.hud_device)
        if model != self._model:
            self._model = model
            self._draw()
        elif self._model is not None:
            raise_over_media(self)
        # A first thumbnail click waits out the double-click window before it
        # posts, exactly as on a player (single switches, double locks).
        due = self._clicks.due(now=time.monotonic())
        if due:
            self._deliver(due)
        self._sync_beat()

    def _sync_beat(self) -> None:
        """Beat fast enough for the trace while something is driving, and back
        to the panel's own beat when nothing is.

        The trace scrolls with the phase, so at the panel's resting beat it
        stepped in visible jumps; ten a second is what the console redraws a
        moving line at.  A still panel redrawn that often is the same picture at
        Pillow's price, paid for the whole show.
        """
        driving = self._model is not None and self._model.osr2 in _MOVING
        self._timer.setInterval(REPAINT_MS if driving else _REFRESH_MS)

    def _file_on_screen(self) -> str:
        """The muted line under the status: what is on this region right now.

        The players print the file they are decoding there, and this panel left
        it blank — the one line of the HUD that says WHAT you are looking at.

        Named the way THIS app names things, not the way the disk does.  Naming
        a generation off its path gives "image / ComfyUI_00123_" — the folder is
        the media type, which says nothing, and the file is a counter no one has
        ever seen in this UI.  The app calls the folder by what the tree calls
        it ("615F7744", or whatever the user typed onto it) and the item by its
        seed, which is what its tile in the browser is captioned with.
        """
        prompt_id = getattr(self._host, "hud_prompt_id", "")
        if not prompt_id or self._label_for is None:
            return ""
        try:
            return self._label_for(prompt_id) or ""
        except Exception:  # naming is decoration; it never costs the panel
            return ""

    def _draw(self) -> None:
        if self._model is None:
            self._targets = None
            self.hide()
            return
        rendered = self._renderer.render(
            self._model, video=self._file_on_screen(),
            hover_loop=self._hover_loop,
            hover_tip=self._hover_tip, hover_pos=self._hover_pos,
        )
        self._targets = rendered.targets
        bgra = rendered.bgra
        height, width, _ = bgra.shape
        image = QImage(bgra.tobytes(), width, height, width * 4,
                       QImage.Format.Format_ARGB32)
        # The app-wide scale shrinks the core window's panes; this panel is
        # already drawn at the family's own sizes and must not shrink with it.
        pixmap = unscaled_pixmap(QPixmap.fromImage(image))
        self.setPixmap(pixmap)
        self.resize(pixmap.deviceIndependentSize().toSize())
        raise_over_media(self)
        if self.isHidden():
            self.show()

    # --- presses, the players' own grammar --------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._targets is None:
            return
        # Bitmap pixels, not logical ones: the panel is drawn unscaled over a
        # scaled window, so its control rects are indexed in its own pixels.
        px, py = to_bitmap_pos(event.position().x(), event.position().y())
        command = self._clicks.press(self._targets, px, py,
                                     now=time.monotonic())
        if command:
            self._deliver(command)

    def mouseReleaseEvent(self, event):
        """Let go of whichever readout band the press took hold of."""
        self._clicks.release()

    def mouseMoveEvent(self, event):
        if self._targets is None:
            return
        from player_core.satellite_hud import button_tooltip, hit_test_targets

        px, py = to_bitmap_pos(event.position().x(), event.position().y())
        if self._clicks.holding:
            # A band the press took hold of goes on being set as the pointer
            # moves, so a level can be dragged and not only clicked.
            self._deliver(self._clicks.drag_to(px, py))
            return
        hover = hit_test_targets(self._targets.loop, px, py)
        tip = button_tooltip(self._targets, px, py)
        if hover == self._hover_loop and tip == self._hover_tip:
            return
        self._hover_loop, self._hover_tip, self._hover_pos = hover, tip, (px, py)
        self._draw()

    def _deliver(self, command: str) -> None:
        """Route one HUD press: what the show answers for itself lands on it,
        and the session's transport goes out on the dashboard channel — or, with
        no session under this show, onto the show as well (:meth:`_act_here`).

        The console's own verbs -- the pace, the motion, the four control
        states, a level dragged on the readout -- land on this window's motion
        and its OSR2 switch, hosted or not: the device is this app's to drive
        wherever the show is drawn, and the session has no say in it.

        The map's own chrome that a show has no counterpart for (the expand
        mark) is swallowed either way, so it can never reach the player a
        region window covers.
        """
        if not command:
            return
        verb, _, path = command.partition("|")
        action = verb.removeprefix(f"{self._side}_")
        if action in _THE_SHOWS_OWN:
            # The two filters, reset, the loop button and the map's own clicks
            # mean on a show what they mean on a player, and the show owns what
            # each is — so they land here, hosted or not.
            answer(self._host, action, path)
            self._tick()
            return
        if self._host.press_console(verb):
            self._tick()
            return
        if self._dashboard_cmd_file is None:
            self._act_here(action)
            return
        allowed = (
            "satellites_video_activate", "origenerator_activate",
            f"{self._side}_prev", f"{self._side}_next",
            f"{self._side}_lock", f"{self._side}_trash",
        )
        if command in allowed:
            append_command(self._dashboard_cmd_file, command)

    def _act_here(self, action: str) -> None:
        """A press with no session under it: the show answers it itself.

        Standalone there is no dashboard channel and no player under the show,
        so the transport cannot take the round trip a hosted press takes — out
        onto the session's command file, through its dispatch, and back onto
        this very show.  It lands on the show directly instead, through the same
        answers that round trip ends at, so the button does the one thing it is
        labeled for either way.

        Minimize is the button that only a show on its own has: the show IS the
        window here, so the button parks it exactly as it parks a satellite's,
        where a hosted show has no window of its own and declares none.
        """
        if action == "minimize":
            self._host.window().showMinimized()
            return  # nothing on the panel changed, and it is off screen anyway
        if answer(self._host, action):
            self._tick()  # the readout answers the press without waiting for the beat
