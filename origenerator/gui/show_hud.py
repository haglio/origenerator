"""The satellite lock HUD, worn by a hosted region show — the players' own.

A show covering a satellite region covers that player's HUD, and what replaced
it used to be a small strip of Qt buttons that only gestured at the real thing.
This widget draws the REAL thing: the same panel the players composite into
their video, rendered by the same shared code (``player_core.satellite_hud`` /
``_paint``), so a show's HUD and a player's HUD cannot drift apart — the mode
row with minimize riding it, the status line, the transport controls, and the
nav map.

The map speaks the players' vocabulary because the show's set IS those
concepts: the set's first item anchors the corner, the rest run right as the
seed row with their real ordinals ("Seed 2" over the second item), the counts
corner says "Seeds: N" for the whole set, and the cell actually on screen is
the lit one — exactly a satellite playing through a seed family.  A thumbnail
click jumps the show to that item, the way a map click switches a player.

Presses that mean something to the session — the mode pair, this side's
prev/next/lock/trash — post onto the dashboard command file, the channel the
players' HUDs and the global hotkeys share.  Presses whose concepts a show
does not have (F-mode, minimize, the loops) are drawn for sameness but
swallowed here, so they can never reach the blacked player underneath.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()
from player_core.file_channel import append_command
from player_core.hud_status import SHUFFLE_LABEL, status_line
from player_core.satellite_hud import (
    MARGIN,
    HudCell,
    HudClicks,
    HudModel,
    HudTargets,
)
from player_core.satellite_hud_paint import HudRenderer

_REFRESH_MS = 300  # the players re-read their published panel on a tick too


def show_hud_model(side: str, host) -> HudModel | None:
    """The host show's state as the players' HUD model, or ``None`` for a show
    with nothing to map (``hud_items`` empty or unanswered)."""
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
    order_label = getattr(host, "hud_order_label", "")
    order_label = SHUFFLE_LABEL if order_label == "Shuffle" else order_label
    return HudModel(
        side=side,
        locked=locked,
        lock_label=status_line(locked=locked, order=order_label, f_mode=f_mode),
        # The players' favorite star and F-mode, over the same collection the
        # Favorites shelf lists: the star lights when the item on screen is a
        # favorite, and F-mode narrows the set to them.
        is_favorite=bool(getattr(host, "hud_is_favorite", False)),
        f_mode=f_mode,
        corner=hud_cells[0],
        seeds=hud_cells[1:],
        seed_count=len(hud_cells),
        playing=("corner", 0) if position <= 1 else ("seed", position - 2),
        # The seed row's loop button is lit, because a show is exactly that:
        # this row, played round and round.  On a player the button starts such
        # a loop; here the loop is already what is happening, so the light says
        # so and a press ends it — which is the button meaning the same thing on
        # both, "stop looping this row".
        active_loop="seed",
        satellites_mode="origenerator",  # a show exists only in this mode
    )


class ShowHud(QLabel):
    """One show's HUD: model from the host, bitmap from the shared renderer."""

    def __init__(self, host: QWidget, *, side: str, dashboard_cmd_file):
        super().__init__(host)
        self._host = host
        self._side = side
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
        self.move(MARGIN, MARGIN)
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()
        self.raise_()
        self.show()

    # --- model in, pixels out ---------------------------------------------

    def _tick(self) -> None:
        model = show_hud_model(self._side, self._host)
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

    def _draw(self) -> None:
        if self._model is None:
            self._targets = None
            self.hide()
            return
        rendered = self._renderer.render(
            self._model, hover_loop=self._hover_loop,
            hover_tip=self._hover_tip, hover_pos=self._hover_pos,
        )
        self._targets = rendered.targets
        bgra = rendered.bgra
        height, width, _ = bgra.shape
        image = QImage(bgra.tobytes(), width, height, width * 4,
                       QImage.Format.Format_ARGB32)
        self.setPixmap(QPixmap.fromImage(image))
        self.resize(width, height)
        self.raise_()
        if self.isHidden():
            self.show()

    # --- presses, the players' own grammar --------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._targets is None:
            return
        pos = event.position()
        command = self._clicks.press(self._targets, int(pos.x()), int(pos.y()),
                                     now=time.monotonic())
        if command:
            self._deliver(command)

    def mouseMoveEvent(self, event):
        if self._targets is None:
            return
        from player_core.satellite_hud import button_tooltip, hit_test_targets

        pos = event.position()
        px, py = int(pos.x()), int(pos.y())
        hover = hit_test_targets(self._targets.loop, px, py)
        tip = button_tooltip(self._targets, px, py)
        if hover == self._hover_loop and tip == self._hover_tip:
            return
        self._hover_loop, self._hover_tip, self._hover_pos = hover, tip, (px, py)
        self._draw()

    def _deliver(self, command: str) -> None:
        """Route one HUD press: map clicks act on the show itself, session
        commands go out on the dashboard channel, and the rest are swallowed.
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
        if verb in (f"{self._side}_no_loop", f"{self._side}_seed_loop"):
            # The seed row is the show, and its loop button is drawn lit for
            # that reason — so the press that would stop the loop closes the
            # show, and the region goes back to whatever it was doing.
            self._host.close()
            return
        if verb == f"{self._side}_reset" and hasattr(self._host, "stroke_reset"):
            # The players' reset, meaning here what it means there: put the
            # side back how it started.  The show owns what that is, and the
            # session's spoken "reset" reaches the same method.
            self._host.stroke_reset()
            self._tick()
            return
        allowed = (
            "players_activate", "origenerator_activate",
            f"{self._side}_prev", f"{self._side}_next",
            f"{self._side}_lock", f"{self._side}_trash",
        )
        if command in allowed and self._dashboard_cmd_file is not None:
            append_command(self._dashboard_cmd_file, command)
        # Anything else (minimize, the loops, F-mode on a show without one) is
        # a player concept this show has no counterpart for: drawn for
        # sameness, swallowed here.

    def _jump(self, path: str, *, hold: bool) -> None:
        if hasattr(self._host, "show_item"):
            self._host.show_item(path, hold=hold)
