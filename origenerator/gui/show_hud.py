"""The satellite lock HUD, worn by every fullscreen show — the players' own.

A show covering a satellite region covers that player's HUD, and what replaced
it used to be a small strip of Qt buttons that only gestured at the real thing.
This widget draws the REAL thing: the same panel the players composite into
their video, rendered by the same shared code (``player_core.satellite_hud`` /
``_paint``), so a show's HUD and a player's HUD cannot drift apart — the mode
row with minimize riding it, the status line, the transport controls, and the
nav map.

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

Presses that mean something to the session — the mode pair, this side's
prev/next/lock/trash — post onto the dashboard command file, the channel the
players' HUDs and the global hotkeys share.  The two filter switches — F-mode,
and the enhanced-only switch beside it that only a show's HUD grows — are the
show's own and land on it directly, hosted or not (:meth:`ShowHud._deliver`).
Presses whose concepts a hosted show does not have (minimize, the loops) are
drawn for sameness but swallowed there, so they can never reach the blacked
player underneath.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.ui_scale import (
    to_bitmap_pos, to_logical_size, unscaled_pixmap,
)
from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()
from player_core.file_channel import append_command
from player_core.hud_status import SHUFFLE_LABEL, looping_label, status_line
from player_core.satellite_hud import (
    MARGIN,
    HudCell,
    HudClicks,
    HudModel,
    HudTargets,
)
from player_core.satellite_hud_paint import HudRenderer

_REFRESH_MS = 300  # the players re-read their published panel on a tick too

# Whether this player_core's HUD knows the enhanced-only switch: the model field
# that grows the button, and the status line's slot that names it (one change
# there, so one question here).  Asked rather than assumed, for the reason
# :func:`~origenerator.gui.gallery_view._shared_hud_widget` asks whether there
# is a shared HUD at all: the switch lives in the newest player_core, and a show
# opened over an older checkout must come up without the button rather than not
# come up.
_HUD_HAS_ENHANCED_SWITCH = "enhanced_filter" in HudModel.__dataclass_fields__


def show_hud_model(side: str, host, *, hosted: bool = True) -> HudModel | None:
    """The host show's state as the players' HUD model, or ``None`` for a show
    with nothing to map (``hud_items`` empty or unanswered).

    *hosted* is whether a Fun Time session is behind the show, and the only
    thing it governs is the mode row.  Defaulted to the hosted answer because
    that is what every reading of a region's model wants; :class:`ShowHud`
    passes its own.
    """
    if not hasattr(host, "hud_items"):
        return None
    cells, position, locked = host.hud_items()
    if not cells:
        return None
    hud_cells = tuple(
        HudCell(path=str(path), thumb=str(thumb) if thumb else "")
        for path, thumb in cells
    )
    f_mode = bool(getattr(host, "hud_f_mode", False))
    enhanced = bool(getattr(host, "hud_enhanced_mode", False))
    order_label = getattr(host, "hud_order_label", "")
    order_label = SHUFFLE_LABEL if order_label == "Shuffle" else order_label
    # A show someone ASKED for is a loop -- this set, played round and round --
    # and the map's loop button is lit for it.  A region's base state is not:
    # it is that side browsing its whole library, exactly what a satellite does
    # with no loop on, so the button is dark and the line just names the order.
    looping = bool(getattr(host, "hud_looping", True))
    # The line says what the light says, in the words a satellite says it in --
    # the two HUDs are one HUD in two places.  Nothing playing_set when nothing
    # is looping, so the base state reads "Unlocked · Shuffle" exactly as a
    # satellite browsing its library does.
    line = dict(playing_set=looping_label("seed") if looping else "",
                locked=locked, order=order_label, f_mode=f_mode)
    switches = {}
    if _HUD_HAS_ENHANCED_SWITCH:
        # Named on or off, never None: a show HAS the switch, so its HUD grows
        # the button -- where a player, publishing nothing for it, does not --
        # and the line names the narrowing beside F-mode while it is on.
        line["enhanced"] = enhanced
        switches["enhanced_filter"] = enhanced
    return HudModel(
        side=side,
        locked=locked,
        lock_label=status_line(**line),
        # The players' favorite star and F-mode, over the same collection the
        # Favorites shelf lists: the star lights when the item on screen is a
        # favorite, and F-mode narrows the set to them.
        is_favorite=bool(getattr(host, "hud_is_favorite", False)),
        f_mode=f_mode,
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
        # Hosted, a show exists only in this mode, and the pair is the way back
        # to the player under it.  Standalone there is no player under it and no
        # session to tell, so the row is not drawn at all — the same "" a
        # session with no hosted Origenerator publishes.  Drawing a dead pair
        # would be the one place on this panel where a lit button is a picture
        # of a button.
        satellites_mode="origenerator" if hosted else "",
        **switches,
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
        # A video surface is a native window on Windows, and a plain sibling
        # widget cannot paint over one however it is stacked — which is why
        # this map vanished the moment a show put media on screen (the same
        # symptom position_caption.py fixed the same way).  Native itself, it
        # stacks against the media by Z-order like any other window.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
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
        self.raise_()
        self.show()

    # --- model in, pixels out ---------------------------------------------

    def _tick(self) -> None:
        model = show_hud_model(self._side, self._host,
                               hosted=self._dashboard_cmd_file is not None)
        if model != self._model:
            self._model = model
            self._draw()
        elif self._model is not None:
            # Media widgets come and go above this map as slides change; the
            # model often doesn't change with them, so re-assert the Z-order
            # every tick rather than only on a redraw.
            self.raise_()
        # A first thumbnail click waits out the double-click window before it
        # posts, exactly as on a player (single switches, double locks).
        due = self._clicks.due(now=time.monotonic())
        if due:
            self._deliver(due)

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
        self.raise_()
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

    def mouseMoveEvent(self, event):
        if self._targets is None:
            return
        from player_core.satellite_hud import button_tooltip, hit_test_targets

        px, py = to_bitmap_pos(event.position().x(), event.position().y())
        hover = hit_test_targets(self._targets.loop, px, py)
        tip = button_tooltip(self._targets, px, py)
        if hover == self._hover_loop and tip == self._hover_tip:
            return
        self._hover_loop, self._hover_tip, self._hover_pos = hover, tip, (px, py)
        self._draw()

    def _deliver(self, command: str) -> None:
        """Route one HUD press: map clicks act on the show itself, session
        commands go out on the dashboard channel — or, with no session behind
        this show, onto the show as well (:meth:`_act_here`) — and the rest are
        swallowed.
        """
        verb, _, path = command.partition("|")
        if verb == f"{self._side}_play_video":
            self._jump(path, hold=False)
            return
        if verb == f"{self._side}_lock_video":
            self._jump(path, hold=True)
            return
        if verb == f"{self._side}_fmode" and hasattr(self._host, "toggle_f_mode"):
            # The players' F-mode, meaning here what it means there: narrow
            # the set to the favorites.  Handled on the show itself — the
            # session's player-side F-mode is about a blacked player's browse.
            self._host.toggle_f_mode()
            self._tick()
            return
        if verb == f"{self._side}_enhanced" and hasattr(self._host, "toggle_enhanced_mode"):
            # The switch beside F-mode, and the show's own the same way: keep
            # only the pictures this show has enhanced, or widen back.
            self._host.toggle_enhanced_mode()
            self._tick()
            return
        if verb in (f"{self._side}_no_loop", f"{self._side}_seed_loop"):
            # Stop looping this row: the region goes back to what it does when
            # nothing is looping, which is browse its whole library — the same
            # place its reset button leads, and the same thing the press means
            # on a player.  Pressed while nothing is looping it is the dark
            # button it looks like: a show cannot start a loop it is not in.
            if getattr(self._host, "hud_looping", True):
                self._host.stroke_reset()
                self._tick()
            return
        if verb == f"{self._side}_reset" and hasattr(self._host, "stroke_reset"):
            # The players' reset, meaning here what it means there: put the
            # side back how it started.  The show owns what that is, and the
            # session's spoken "reset" reaches the same method.
            self._host.stroke_reset()
            self._tick()
            return
        if self._dashboard_cmd_file is None:
            self._act_here(verb)
            return
        allowed = (
            "players_activate", "origenerator_activate",
            f"{self._side}_prev", f"{self._side}_next",
            f"{self._side}_lock", f"{self._side}_trash",
        )
        if command in allowed:
            append_command(self._dashboard_cmd_file, command)
        # Anything else (minimize, the loops, a filter switch on a show without
        # one) is a player concept a hosted show has no counterpart for: drawn
        # for sameness, swallowed here so it can never reach the player
        # underneath.

    def _act_here(self, verb: str) -> None:
        """A press with no session behind it: the show answers it itself.

        Standalone there is no dashboard channel and no player under the show,
        so the transport cannot take the round trip a hosted press takes — out
        onto the session's command file, through its dispatch, and back onto
        this very show.  It lands on the show directly instead, through the same
        four methods that round trip ends at and that the arrow keys and genau's
        console already use, so the button does the one thing it is labeled for
        either way.

        Minimize is the press that means MORE standalone than hosted rather than
        less: hosted it would hit the blacked player under the show, so it is
        swallowed there; standalone the show IS the window and the button parks
        it, exactly as it parks a satellite's.
        """
        step = {f"{self._side}_prev": -1, f"{self._side}_next": 1}.get(verb)
        if step is not None:
            self._host.stroke_step(step)
        elif verb == f"{self._side}_lock":
            self._host.stroke_toggle_hold()
        elif verb == f"{self._side}_trash":
            self._host.stroke_cull()
        elif verb == f"{self._side}_minimize":
            self._host.window().showMinimized()
            return  # nothing on the panel changed, and it is off screen anyway
        else:
            # Everything a hosted press has no counterpart for either — the
            # expand button's "more seeds", a mode press this panel does not
            # even draw — swallowed here as it is swallowed there.
            return
        self._tick()  # the readout answers the press without waiting for the beat

    def _jump(self, path: str, *, hold: bool) -> None:
        if hasattr(self._host, "show_item"):
            self._host.show_item(path, hold=hold)
