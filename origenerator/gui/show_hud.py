"""The one panel a show wears -- the players' own, drawn by their own code.

A show covering a satellite region covers that player's HUD, so what replaces
it is the same panel rather than a strip of Qt buttons gesturing at it
(``player_core.satellite_hud`` / ``_paint``).  A standalone show wears it too:
nothing about a show is different for not being inside a session.

Everything a show has to say is on it, because a second plate over the same
picture is a second HUD: the set and its map (:mod:`origenerator.gui.show_map`),
the clip's own track, time and volume (:mod:`player_core.hud_row`), the device
on a host driving one (:attr:`~origenerator.gui.show_host.ShowHost.hud_device`),
and at its foot the generation queue the covered lower strip would be showing
(:mod:`origenerator.gui.hud_queue`).  Fun Time splits the first two across two
windows because there they are two players; a show is one host doing both, and
wearing both panels put two disagreeing status lines on one screen.

Presses that mean something to the session post onto the dashboard command
file; everything else lands on the show itself (:meth:`ShowHud._deliver`).
"""

from __future__ import annotations

import time
from dataclasses import replace

from player_core.file_channel import append_command
from player_core.hud_placement import HudCorner, hud_origin
from player_core.hud_row import (
    MUTE,
    SCRUBBER,
    VOLUME,
    row_part,
    scrub_to,
    volume_to,
)
from player_core.hud_status import looping_label, status_line
from player_core.modes import Osr2State
from player_core.satellite_hud import (
    MARGIN,
    HudCell,
    HudClicks,
    HudModel,
    HudTargets,
    button_tooltip,
    hit_test_targets,
)
from player_core.satellite_hud_paint import HudRenderer
from player_core.timeline import bar_track_x
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.console_commands import side_press, spelled_for
from origenerator.funscript import heatmap_colors
from origenerator.gui.console import REPAINT_MS
from origenerator.gui.hud_queue import (
    CANCEL,
    CLEAR,
    FRAME,
    OPEN,
    ROWS,
    queue_section,
)
from origenerator.gui.media_overlay import float_over_media, raise_over_media
from origenerator.gui.show_map import SEED_AXIS
from origenerator.gui.show_set import thumb_of
from origenerator.show_buttons import answer, show_rows
from origenerator.ui_scale import (
    to_bitmap_pos,
    to_logical_size,
    unscaled_pixmap,
)

_REFRESH_MS = 300  # the players re-read their published panel on a tick too
# How far a press on a queue row has to travel before it is a drag rather than
# the click that opens the job's folder.
_DRAG_START = 6

# The two states with a line that moves: something is being sent, so the trace
# scrolls and the panel has to keep up with it.
_MOVING = frozenset({Osr2State.ROBOT_HAND, Osr2State.FUNSCRIPT})

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

_COLLAPSES = {"hud_minimize": True, "hud_restore": False}

def _cell(slide, label: str = "") -> HudCell:
    return HudCell(path="" if slide.is_live else str(slide.path), thumb=thumb_of(slide),
                   label=label)


def show_hud_model(side: str, host, *, hosted: bool = True,
                   own_window: bool = True, device=None, foot=None) -> HudModel | None:
    """The host show's state as the players' HUD model, or ``None`` for a show
    with nothing to map (``hud_map`` unanswered).

    *hosted* and *own_window* decide which buttons the panel declares
    (:func:`~origenerator.show_buttons.show_rows`) and what reset goes back to;
    both default to what a region show wants.  *foot* is the generation queue
    (:mod:`origenerator.gui.hud_queue`) and *device* what this window is doing
    to the OSR2 (:class:`~origenerator.gui.console.ShowDevice`) -- each None
    where there is none, which is what a show on a session's player answers.
    """
    shown = host.hud_map()
    if shown is None:
        return None  # a host with no set under it, and so nothing to map
    locked = host.locked
    favorites_filter = host.hud_favorites_filter
    enhanced = host.hud_enhanced_mode
    order_label = host.hud_order_label
    act_filter = host.hud_act_filter
    return HudModel(
        player=side,
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
                               f_mode=favorites_filter, enhanced=enhanced,
                               filter_label=act_filter),
        # The players' favorite star, over the same collection the Favorites
        # shelf lists: it lights when the item on screen is a favorite.
        is_favorite=host.hud_is_favorite,
        item_note=host.hud_item_note,
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
        max_intensity=device.max_intensity if device is not None else None,
        foot=foot,
        corner=_cell(shown.corner),
        seeds=tuple(_cell(slide) for slide in shown.seeds),
        actions=tuple(_cell(row.slide, row.label) for row in shown.column),
        current_action=shown.label,
        # The act(s) the show is narrowed to, so the rows the filter keeps
        # light their buttons and a second press on the row it already is
        # lifts it, exactly as on a satellite.  With no filter on, a seed
        # loop lights the row it is playing, which is what the button on
        # that row says about it.
        filter_query=act_filter or (shown.label if shown.loop == SEED_AXIS else ""),
        seed_count=len(shown.seeds) + 1,
        action_count=len(shown.column) + 1,
        playing=shown.playing,
        active_loop=shown.loop,
    )


class ShowHud(QLabel):
    """One show's HUD: model from the host, bitmap from the shared renderer."""

    def __init__(self, host: QWidget, *, side: str, dashboard_cmd_file,
                 label_for=None, corner: HudCorner = HudCorner.UPPER_LEFT,
                 minimized: bool = False, collapse=None):
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
        self._corner = corner
        self._minimized = minimized
        self._collapse = collapse
        self._renderer = HudRenderer(side)
        self._clicks = HudClicks(side)
        self._targets: HudTargets | None = None
        self._model: HudModel | None = None
        self._hover_loop = ""
        self._hover_tip = ""
        self._hover_pos = (0, 0)
        # What the row at the panel's foot last showed, kept because the panel
        # is redrawn when it moves and a press along its track is placed
        # against the length it was drawn with.
        self._row = None
        # The funscript's colors across the track, and the width they were
        # built for: the panel sizes itself, so a render that comes back a
        # different size rebuilds them.
        self._heatmap = None
        self._heatmap_of: tuple[str, int] | None = None
        # Which control of that row a press is holding, so a level or a place
        # in the clip can be dragged and not only clicked.
        self._row_hold = ""
        self._queue_first = 0
        self._queue_press: tuple[str, int, int, bool] | None = None
        self._queue_drag: str | None = None
        self._queue_drop: int | None = None
        self.setMouseTracking(True)  # hover tooltips render into the bitmap
        # Its map is clicked and hovered, so the mouse stops here.
        float_over_media(self, click_through=False)
        self._place()
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()
        self.show()

    @property
    def side(self) -> str:
        return self._side

    def set_hud_place(self, corner: HudCorner, minimized: bool) -> None:
        if (corner, minimized) == (self._corner, self._minimized):
            return
        self._corner, self._minimized = corner, minimized
        self._forget_the_pointer()
        self._tick()
        self._place()

    def _place(self) -> None:
        margin = to_logical_size(MARGIN)
        size = self.size()
        self.move(*hud_origin(self._corner, panel=(size.width(), size.height()),
                              window=(self._host.width(), self._host.height()),
                              margin=margin))

    # --- model in, pixels out ---------------------------------------------

    def _tick(self) -> None:
        model = show_hud_model(self._side, self._host,
                               hosted=self._dashboard_cmd_file is not None,
                               device=self._host.hud_device,
                               foot=self._queue())
        if model is not None:
            model = replace(model, hud_corner=self._corner,
                            hud_minimized=self._minimized)
        # The loop and filter buttons toggle off what they read as lit, so the
        # clicks mirror the show's loop the way a player's mirror its published
        # panel.
        self._clicks.active_loop = model.active_loop if model is not None else ""
        self._clicks.active_filter = model.filter_query if model is not None else ""
        row = self._host.hud_scrubber
        if (model, row) != (self._model, self._row):
            self._model, self._row = model, row
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
        """Beat fast enough for whatever is moving on the panel — the drive's
        trace, and the playcursor along a video's track — and back to the
        panel's own beat when nothing is, a still panel redrawn ten times a
        second being the same picture at Pillow's price.
        """
        moving = (self._model is not None and self._model.osr2 in _MOVING)             or self._row is not None
        self._timer.setInterval(REPAINT_MS if moving else _REFRESH_MS)

    def _file_on_screen(self) -> str:
        """The muted line under the status: what is on this region right now,
        named the way THIS app names it — the folder as the tree shows it and
        the item by its seed, not "image / ComfyUI_00123_" off the path.
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
        rendered = self._render()
        row = rendered.targets.row
        if row is not None:
            drawn_with = self._heatmap
            if self._colors_for(_track_width(row[2])) is not drawn_with:
                rendered = self._render()
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
        self._place()
        raise_over_media(self)
        if self.isHidden():
            self.show()

    def _render(self):
        return self._renderer.render(
            self._model, video=self._file_on_screen(),
            hover_loop=self._hover_loop,
            hover_tip=self._hover_tip, hover_pos=self._hover_pos,
            clip_row=self._row, heatmap=self._heatmap,
        )

    def _colors_for(self, track_width: int):
        """The funscript's colors across a track that wide, kept until the clip
        or the width moves."""
        key = (self._host.current_media_path(), track_width)
        if key != self._heatmap_of:
            self._heatmap_of = key
            self._heatmap = heatmap_colors(self._host.hud_funscript, track_width) or None
        return self._heatmap

    # --- the queue block, which is this app's own ---------------------------

    def _queue(self):
        """What is in flight, as the block the panel hangs at its foot."""
        items, foreign = self._host.hud_queue
        return queue_section(items, foreign, first=self._queue_first,
                             drop_at=self._queue_drop)

    def _queue_item(self, key: str):
        """The job that row stands for, or ``None`` once it has left the line."""
        return next((item for item in self._host.hud_queue[0] if item.key == key), None)

    def _press_queue(self, verb: str, key: str) -> None:
        """A press on the block: throw a job away, go to the folder it will
        land in, or drop another app's work -- a press on a ROW only once
        :meth:`mouseReleaseEvent` says it was a click rather than a drag.
        """
        if verb == CLEAR:
            self._host.clear_foreign_queue()
        elif verb == CANCEL:
            item = self._queue_item(key)
            if item is not None and item.cancel is not None:
                item.cancel()
        else:
            item = self._queue_item(key)
            if item is not None:
                item.reveal()
        self._tick()

    def _queue_rows(self) -> list[tuple[tuple, str]]:
        """Each drawn row's rect and the job it stands for, in the order drawn."""
        if self._targets is None:
            return []
        return [(rect, button.command.partition("|")[2])
                for rect, button in self._targets.buttons
                if button.command.startswith(f"{OPEN}|")]  # not the head's picture

    def _drop_index(self, py: int) -> int:
        """Which slot in the line a drop at ``py`` lands in: above the row whose
        upper half it fell on, else at the end of what is drawn."""
        rows = self._queue_rows()
        for index, (rect, _key) in enumerate(rows):
            if py < rect[1] + rect[3] / 2:
                return self._queue_first + index
        return self._queue_first + len(rows)

    def _drag_to(self, key: str, target: int) -> None:
        """Re-line the queue with *key*'s row let go at *target*.

        Nothing may be moved in front of what ComfyUI is already rendering, and
        a row let go where it already was asks for nothing.
        """
        items = self._host.hud_queue[0]
        keys = [item.key for item in items]
        if key not in keys:
            return
        source = keys.index(key)
        # The slot was read with the dragged row still in place, so a drop below
        # it names one further along than it will end up in.
        target = min(target - 1 if target > source else target, len(keys) - 1)
        first = next((index for index, item in enumerate(items)
                      if not item.reading.rendering), len(items))
        if not first <= source or not first <= target:
            return
        moved = list(keys)
        moved.insert(target, moved.pop(source))
        if moved != keys:
            self._host.requeue(moved)

    def wheelEvent(self, event):
        """Scroll the line past the rows the block draws.

        Only over the block itself: the wheel anywhere else on the panel is not
        this app's to take, and a map that scrolled under the pointer would be a
        surprise.
        """
        px, py = to_bitmap_pos(event.position().x(), event.position().y())
        rows = self._queue_rows()
        if not rows or not any(rect[1] <= py < rect[1] + rect[3] for rect, _key in rows):
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() // 120 or (1 if event.angleDelta().y() > 0 else -1)
        lines = len(self._host.hud_queue[0])
        self._queue_first = max(0, min(self._queue_first - steps, max(0, lines - ROWS)))
        self._tick()

    # --- the row at the foot, which is the players' own --------------------

    def _press_row(self, px: int, py: int) -> bool:
        """A press on the track, the chip or the time; False if it missed them.
        The row is hit-tested in its own coordinates, the way every panel that
        hosts it does (:func:`player_core.hud_row.row_part`)."""
        rect = self._targets.row if self._targets is not None else None
        if rect is None or self._row is None:
            return False
        x, y, width, height = rect
        if not (x <= px < x + width and y <= py < y + height):
            return False
        part = self._row_hold = row_part(px - x, py - y, width=width)
        if part == SCRUBBER:
            self._host.scrub_to(scrub_to(px - x, width=width,
                                         duration_ms=self._row.duration_ms))
        elif part == VOLUME:
            self._host.set_volume(volume_to(px - x, py - y, width=width))
        elif part == MUTE:
            self._host.set_audio_muted(not self._host.audio_muted())
        self._tick()
        return True

    # --- presses, the players' own grammar --------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._targets is None:
            return
        # Bitmap pixels, not logical ones: the panel is drawn unscaled over a
        # scaled window, so its control rects are indexed in its own pixels.
        px, py = to_bitmap_pos(event.position().x(), event.position().y())
        if self._press_row(px, py):
            return
        command = self._clicks.press(self._targets, px, py,
                                     now=time.monotonic())
        verb, _, key = command.partition("|")
        if verb in (OPEN, FRAME):
            # A row is pressed for two things — its folder and a place further
            # down the line — so the press is held until the release says which.
            # The head's picture is pressed for the folder alone.
            self._queue_press = (key, px, py, verb == OPEN)
            return
        if command:
            self._deliver(command)

    def mouseReleaseEvent(self, event):
        """Let go of whichever readout band the press took hold of, and finish
        whatever a press on the queue turned out to be."""
        self._clicks.release()
        self._row_hold = ""
        pending, self._queue_press = self._queue_press, None
        dragged, drop = self._queue_drag, self._queue_drop
        self._queue_drag, self._queue_drop = None, None
        if dragged is not None:
            if drop is not None:
                self._drag_to(dragged, drop)
            self._tick()
        elif pending is not None:
            self._press_queue(OPEN, pending[0])

    def mouseMoveEvent(self, event):
        if self._targets is None:
            return

        px, py = to_bitmap_pos(event.position().x(), event.position().y())
        if self._row_hold and event.buttons() & Qt.MouseButton.LeftButton:
            self._press_row(px, py)
            return
        if self._queue_press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_row(px, py)
            return
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

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._hover_loop or self._hover_tip:
            self._forget_the_pointer()
            self._draw()

    def _forget_the_pointer(self) -> None:
        self._hover_loop = self._hover_tip = ""

    def _drag_row(self, px: int, py: int) -> None:
        """A press on a row that travels is a drag, and the block marks where it
        would land.  The row being rendered stays where it is: nothing can be
        moved in front of what ComfyUI is already working on, itself included.
        """
        key, start_x, start_y, draggable = self._queue_press
        if self._queue_drag is None:
            if not draggable or abs(px - start_x) + abs(py - start_y) < _DRAG_START:
                return
            line = next((line for line in (self._model.foot.lines if self._model
                                           and self._model.foot else ())
                         if line.key == key), None)
            if line is None or not line.movable:
                self._queue_press = None
                return
            self._queue_drag = key
        self._queue_drop = self._drop_index(py)
        self._tick()

    def _deliver(self, command: str) -> None:
        """Route one HUD press: what the show answers for itself lands on it,
        the session's transport goes out on the dashboard channel — or, with no
        session under this show, onto the show as well (:meth:`_act_here`) —
        and the device's own verbs land on this window either way, the OSR2
        being this app's to drive wherever the show is drawn.
        """
        if not command:
            return
        verb, _, path = command.partition("|")
        if verb in (CANCEL, CLEAR, FRAME, OPEN):
            self._press_queue(verb, path)  # this app's own line, never a session's
            return
        action, path = side_press(self._side, verb, path)
        if action in _COLLAPSES:
            self._collapse_here_or_out_there(command, _COLLAPSES[action])
            return
        if action in _THE_SHOWS_OWN:
            # The two filters, reset, the loops, the expand mark and the map's
            # own clicks mean on a show what they mean on a player, and the
            # show owns what each is — so they land here, hosted or not.
            answer(self._host, action, path)
            self._tick()
            return
        if self._host.press_console(verb):
            self._tick()
            return
        if self._dashboard_cmd_file is None:
            self._act_here(action)
            return
        allowed = ("satellites_kino_activate", "origenerator_activate",
                   *(spelled_for(self._side, verb)
                     for verb in ("prev", "next", "lock", "trash")))
        if command in allowed:
            append_command(self._dashboard_cmd_file, command)

    def _collapse_here_or_out_there(self, command: str, minimized: bool) -> None:
        if self._dashboard_cmd_file is not None:
            append_command(self._dashboard_cmd_file, command)
            return
        if self._collapse is not None:
            self._collapse(minimized)

    def _act_here(self, action: str) -> None:
        """A press with no session under it: the show answers it itself.

        Standalone there is no command file to take the round trip a hosted
        press takes, so the press lands on the show through the same answers
        that round trip would have ended at.  Minimize is the one button only a
        show on its own has, the show being the window here.
        """
        if action == "minimize":
            self._host.window().showMinimized()
            return  # nothing on the panel changed, and it is off screen anyway
        if answer(self._host, action):
            self._tick()  # the readout answers the press without waiting for the beat


def _track_width(row_width: int) -> int:
    """How many pixels of a row that wide the track itself covers."""
    x0, x1 = bar_track_x(row_width)
    return x1 - x0
