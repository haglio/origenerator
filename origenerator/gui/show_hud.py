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

The map is the players' map drawn over this app's generations
(:mod:`origenerator.gui.show_map`): the slide on screen in the corner, the
same configuration under other seeds running right as the seed row, the same
seed under other configurations running down as the column, the loop button
lit for whichever axis is playing round and round, and the cell actually on
screen the lit one — exactly a satellite mapping its clip against its
library.  A thumbnail click jumps the show to that item, the way a map click
switches a player, and the map's own chrome — the two loop buttons and the
expand mark — means here what it means there.

Presses that mean something to the session — the mode pair, this side's
prev/next/lock/trash — post onto the dashboard command file, the channel the
players' HUDs and the global hotkeys share.  Everything else on the panel is
the show's own and lands on it directly, hosted or not
(:meth:`ShowHud._deliver`): the two filter switches, reset, the loops, the
expand mark and the map's cells.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui.media_overlay import float_over_media, raise_over_media
from origenerator.gui.show_buttons import answer, show_rows
from origenerator.gui.show_map import CONFIG_AXIS, SEED_AXIS
from origenerator.gui.show_set import thumb_of
from origenerator.paths import ensure_player_core_on_path
from origenerator.ui_scale import (
    to_bitmap_pos,
    to_logical_size,
    unscaled_pixmap,
)

ensure_player_core_on_path()
from player_core.file_channel import append_command
from player_core.hud_status import looping_label, status_line
from player_core.satellite_hud import (
    MARGIN,
    HudCell,
    HudClicks,
    HudModel,
    HudTargets,
)
from player_core.satellite_hud_paint import HudRenderer

_REFRESH_MS = 300  # the players re-read their published panel on a tick too

# The presses a show answers for itself wherever it is drawn: the two filters,
# reset, the order pair, the loops, the expand mark, the map's own clicks and
# its keys.  The transport is the other half, which a hosted window hands to
# its session instead.
_THE_SHOWS_OWN = frozenset({
    "fmode", "enhanced", "reset", "shuffle", "latest", "no_loop", "seed_loop",
    "action_loop", "loop", "more_seeds", "play_video", "lock_video", "filter",
    "no_filter", "nav_left", "nav_right", "nav_up", "nav_down", "cycle_seed",
    "cycle_action",
})

# The map's second axis, in the players' spelling: their column is the
# subject's other acts, and the panel names it so wherever it says which axis
# a loop or a lit cell is on.
_PANEL_AXIS = {CONFIG_AXIS: "action"}


def _cell(slide, label: str = "") -> HudCell:
    return HudCell(path=str(slide.path), thumb=thumb_of(slide), label=label)


def split_press(side: str, verb: str, argument: str = "") -> tuple[str, str]:
    """A press as the panel spells it, taken apart into what it asks and what
    it carries: ``<side>_<action>`` and its ``|`` payload for most, and — the
    one verb spelled the other way round — ``filter_<side>_<row>``, whose
    payload is the row it names."""
    filtering = f"filter_{side}_"
    if verb.startswith(filtering):
        return "filter", verb[len(filtering):]
    return verb.removeprefix(f"{side}_"), argument


def show_hud_model(side: str, host, *, hosted: bool = True,
                   own_window: bool = True) -> HudModel | None:
    """The host show's state as the players' HUD model, or ``None`` for a show
    with nothing to map (``hud_map`` unanswered).

    *hosted* is whether a Fun Time session is under the show and *own_window*
    whether this app is drawing it in a window of its own; together they decide
    which buttons the panel declares (see
    :func:`~origenerator.gui.show_buttons.show_rows`) and what reset goes back
    to.  Both default to what a region show wants, which is what every reading
    of one wants; :class:`ShowHud` and a show handed to a player pass their own.
    """
    shown = host.hud_map()
    if shown is None:
        return None  # a host with no set under it, and so nothing to map
    locked = host.locked
    f_mode = host.hud_f_mode
    enhanced = host.hud_enhanced_mode
    order_label = host.hud_order_label
    loop = _PANEL_AXIS.get(shown.loop, shown.loop)
    bucket, index = shown.playing
    return HudModel(
        side=side,
        locked=locked,
        # The line says what the map's light says, in the words a satellite
        # says it in -- the two HUDs are one HUD in two places.  Nothing
        # playing_set when nothing is looping, so a show browsing its set reads
        # "Unlocked · Shuffle" exactly as a satellite browsing its library does;
        # and it names both narrowings beside the rest — F-mode over the
        # favorites, and the enhanced-only switch a show's HUD is the one
        # panel here to carry.
        lock_label=status_line(playing_set=looping_label(shown.loop) if shown.loop else "",
                               locked=locked, order=order_label,
                               f_mode=f_mode, enhanced=enhanced),
        # The players' favorite star, over the same collection the Favorites
        # shelf lists: it lights when the item on screen is a favorite.
        is_favorite=host.hud_is_favorite,
        # The buttons this show answers, in the bands the panel draws them in —
        # which ones depends on what is drawing it.
        rows=show_rows(side, locked=locked, f_mode=f_mode, enhanced=enhanced,
                       order=order_label, hosted=hosted, own_window=own_window),
        corner=_cell(shown.corner),
        seeds=tuple(_cell(slide) for slide in shown.seeds),
        actions=tuple(_cell(slide, label)
                      for slide, label in zip(shown.configs, shown.config_labels)),
        current_action=shown.label,
        # The row the show is narrowed to — a satellite's act filter, here the
        # configuration whose seed row is looping — so its button lights and a
        # second press on it lifts the loop rather than starting it again.
        filter_query=shown.label if shown.loop == SEED_AXIS else "",
        seed_count=len(shown.seeds) + 1,
        action_count=len(shown.configs) + 1,
        playing=(_PANEL_AXIS.get(bucket, bucket), index),
        active_loop=loop,
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
                               hosted=self._dashboard_cmd_file is not None)
        # The loop and filter buttons toggle off what they read as lit, so the
        # clicks mirror the show's loop the way a player's mirror its published
        # panel.
        self._clicks.active_loop = model.active_loop if model is not None else ""
        self._clicks.active_filter = model.filter_query if model is not None else ""
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
        """Route one HUD press: what the show answers for itself lands on it,
        and the session's transport goes out on the dashboard channel — or, with
        no session under this show, onto the show as well (:meth:`_act_here`).

        The players' chrome that a show has no counterpart for (the strike
        under an act) is swallowed either way, so it can never reach the
        player a region window covers.
        """
        verb, _, path = command.partition("|")
        action, path = split_press(self._side, verb, path)
        if action in _THE_SHOWS_OWN:
            # The two filters, reset, the loops, the expand mark and the map's
            # own clicks mean on a show what they mean on a player, and the
            # show owns what each is — so they land here, hosted or not.
            answer(self._host, action, path)
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
