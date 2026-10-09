"""The fullscreen player -- the one way this app fills the screen with a picture.

It plays a set of generations: a folder's, a shelf's, or the one folder a
double-clicked picture came from, which is why there is no second fullscreen
viewer with its own keys.  The set is not frozen at the opening: a run joins it
on its first frame, which is what a show of a filling folder is watched for.

The Slideshow runs on a Funestra, the one this app activates for it
(:mod:`origenerator.gui.funestra_pane`): the Funestra plays the pass it is
handed, holds a picture for the pace and creeps over it, plays a clip to its
end and rolls onto the next, repeats what it is locked onto, draws the one
panel the show wears over the picture and places the presses on it.  What
this view answers for is the set, the pass dealt from it and the slide on
screen: it hands the pass over, follows the Funestra as it walks the pass,
and answers every press and key.  A show on one of a session's players
(:mod:`origenerator.gui.player_show`) keeps the same set and drives its
Funestra through files instead.

What every key does, what the lock takes with it, what a filter narrows and
where a closing show leaves you are `tests/test_slideshow_view.py`'s to state:
each is a test named for the claim.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

from player_core.console import ModeHud
from player_core.file_channel import append_command
from player_core.hud_overlay import FOOT_DRAG, FOOT_PRESS, FOOT_RELEASE, FOOT_WHEEL
from player_core.hud_placement import HudCorner
from player_core.modes import Osr2State
from player_core.playback_rate import RATE_STEP
from player_core.playlist import PlaylistItem
from player_core.pointer import OMNIPAUSE_TOGGLE
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator import osr2 as osr2_device
from origenerator.config import FRAMES_BEING_MADE_DIR
from origenerator.console_commands import side_press, spelled_for
from origenerator.gui.console import REPAINT_MS, post_console_action, show_device
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_pane import FunestraPane
from origenerator.gui.hud_queue import QueuePointer, queue_section
from origenerator.gui.level_stepper import LevelStepper
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.notice_overlay import NOTICE, WARNING, NoticeOverlay
from origenerator.gui.show_map import SEED_AXIS
from origenerator.gui.show_panel import COLLAPSES, THE_SHOWS_OWN, show_hud_model
from origenerator.gui.show_pass import playlist_item, rotated_onto, slide_item
from origenerator.gui.show_set import (
    GENERATING,
    LOOP_IS_A_LOCK,
    LOOP_OFF,
    ShowSet,
    item_note,
    looping_note,
    narrow_to_acts,
    narrow_to_the_act_on_screen,
)
from origenerator.gui.show_wiring import ShowActions
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.media import MediaType
from origenerator.osr2_driver import drive_target_for
from origenerator.show_buttons import answer
from origenerator.slideshow import ShowFilters, ShowState, Slide, in_order

logger = logging.getLogger(__name__)

# What the map's chrome says when it does what it says, in the players' own
# words, and the three ways it can have nothing to do.
_MORE_SEEDS = "More seeds"
_WIDENING_FAILED = "Widening net failed"
_NOTHING_TO_LOOP = "Nothing to loop"
_NOTHING_THAT_WAY = "Nothing that way"

# The run a show follows full screen, as its frames are filed.
_FOLLOWED = "followed"

# How often the panel is rebuilt: on its own beat, and faster while something
# on it is moving -- the drive's trace.
_REFRESH_MS = 300
_MOVING = frozenset({Osr2State.ROBOT_HAND, Osr2State.FUNSCRIPT})
_FOOT_VERBS = frozenset({FOOT_PRESS, FOOT_DRAG, FOOT_RELEASE, FOOT_WHEEL})

_PANEL_MOVES = {
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
}


class SlideshowView(QWidget):
    # Enter on an item: leave the slideshow for that generation's own folder.
    open_requested = pyqtSignal(str)
    # The show was dismissed (Escape, Enter out, or culled empty) — the gallery
    # keeps voice-command listening tied to a fullscreen surface being up.
    closed = pyqtSignal()
    # A different item (or version) is on screen — re-aim the OSR2 drive.
    media_changed = pyqtSignal()

    def __init__(self, items, *, frame=None, start=None, image_dwell_ms=None,
                 shuffle=None, actions=None, hud=None, player=None, motion=None,
                 pace=None, frames=None, clock=time.monotonic, parent=None):
        super().__init__(parent)
        # What a press here asks the gallery to do on its behalf — the half of
        # each gesture that lands on the generation rather than on the slide.
        # None of it, for a show standing on its own (see ShowActions).
        self._actions = actions if actions is not None else ShowActions()
        self._motion = motion  # the gallery's app-global motion driver, or None
        # How long a slide holds the screen is app-wide, because the console
        # that sets it is: turned up here or in the main window, it is the
        # same number. An explicit dwell (a test's) wins until the console
        # next moves the pace.
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        self._pace.changed.connect(self._on_pace_changed)
        self._clock = clock
        self._last_tick = clock()
        self._held_s = 0.0
        self._moves_on_early = False
        self._frames = frames if frames is not None else FrameFiles(FRAMES_BEING_MADE_DIR / "fullscreen")
        # The file the Funestra was last stood on, and what it is of: a slide,
        # one of its versions, or nothing while a run's frames are up.
        self._showing: Path | None = None
        self._showing_media: tuple | None = None
        self._frame_on_player: Path | None = None
        self._frames_on_screen = False
        self._loads_seen: int | None = None
        self._refusal_checked = True
        # The panel this show wears: which side's it is, who draws it, and
        # where it sits — settled when the show is dressed (see wear_the_hud).
        self._hud_side = ""
        self._dashboard_cmd_file = None
        self._label_for = None
        self._corner = HudCorner.UPPER_LEFT
        self._minimized = False
        self._collapse = None
        self._panel_model = None
        self._panel_built_at = float("-inf")
        self._panel_stale = True
        # What is in flight, for the block the panel hangs at its foot, and the
        # pointer on that block.
        self._queue_items: list = []
        self._foreign_queued = 0
        self._queue_pointer = QueuePointer(self)
        self._take_set(items, frame=frame, start=start,
                       image_dwell_ms=image_dwell_ms, shuffle=shuffle, hud=hud)
        self.setWindowTitle("Slideshow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)  # a solid black surround under the media
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Already the fullscreen view, so a double-click leaves it rather than
        # spawning a nested one. It plays sound, unlike the muted inline pane.
        self._pane = FunestraPane(
            self, user=self._as_the_funestra_sees_it, panel=self._hud_model,
            on_double_click=self.close, on_open=self._the_funestra_opened,
            player_for=None if player is None else (lambda _window_id: player))
        layout.addWidget(self._pane, 1)

        # A note about the item on screen: which of its versions this is, that an
        # enhancement of it is being made, and for a beat whatever a switch or a
        # spoken fix just did — the only way to tell, in a view with no panels,
        # that a press did anything. It is a Fun Time notice, at the top center
        # where Fun Time flashes the same kind of line over a player, because
        # this surface wears the players' own HUD and had no business saying
        # things in a second dialect at the other end of the screen.
        self._note = NoticeOverlay(self)
        # What the corner reads while a spoken request pauses the show; empty
        # whenever nothing is being dictated.
        self._request_note = ""
        # And what it reads afterwards, while the request said is still being
        # worked out — held rather than flashed, and cleared by that request's
        # own answer, which is why the request it is about is kept beside it.
        self._working_note = ""
        self._working_request = None
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)

        # The room's pause, held here so it survives navigation: a step lands on
        # a NEW slide (the freeze does not un-aim the transport), but the slide
        # must arrive frozen — no dwell armed, its video paused — rather than
        # playing out from under the freeze.
        self._paused = False

        self._show_current()

    # --- the set, and the pass dealt from it --------------------------------

    def play(self, items, *, frame=None, start=None, image_dwell_ms=None,
             shuffle=None, hud=None, actions=None) -> None:
        """Take a new set into this window and start it on that set.

        Standalone the monitor holds one show, so a second set asked for while
        this one is up arrives here rather than in a window of its own (see
        :meth:`~origenerator.gui.show_director.ShowDirector._open_a_window`) —
        the same re-pointing a region's player gets when the set it is showing
        changes.  It takes the set exactly as construction does, so a window
        re-pointed cannot drift from one freshly opened.
        """
        if actions is not None:
            self._actions = actions
        self._take_set(items, frame=frame, start=start,
                       image_dwell_ms=image_dwell_ms, shuffle=shuffle, hud=hud)
        self._show_current()

    def _take_set(self, items, *, frame, start, image_dwell_ms, shuffle, hud) -> None:
        # Following a generation still in flight: no items of its own, so the pane
        # that opened this feeds the frames and hands over the file that lands.
        self._live = not items
        self._frame = frame  # the frame the double-click landed on, if any
        # The item to hand the gallery on the way out, once there is one: Enter
        # names it outright, and a lock names it by being the slide the show
        # ended on. Read in :meth:`closeEvent`, which is where every way out of
        # the show meets.
        self._land_on: str | None = None
        # The versions of each item that has any, and the place within the one
        # being stepped: Shift+Left/Right moves there rather than along the set.
        self._levels = LevelStepper()
        if image_dwell_ms is None:
            image_dwell_ms = self._pace.dwell_ms
        self._dwell_s = image_dwell_ms // 1000
        # The set this show plays, the pass dealt from it, and what its two
        # switches keep of it — all of it the same whether a window or one of
        # a session's players is showing the slides (see ShowSet).  What this
        # view answers for is the slide on screen, so a re-dealt pass comes
        # back here as :meth:`_pass_changed`.
        self._set = ShowSet(items, image_dwell_ms=image_dwell_ms, shuffle=shuffle,
                            start=start, hud=hud, on_pass_change=self._pass_changed,
                            neighbors=self._actions.neighbors, widen=self._actions.widen,
                            acts=self._actions.acts,
                            on_filters_change=self._actions.filters_changed)

    @property
    def _playlist(self):
        """The pass this show is playing — the set's, since the set deals it."""
        return self._set.playlist

    def _pass_changed(self, kept: bool) -> None:
        """A fresh pass was dealt over the set: show whatever is on it now.

        *kept* says the slide that was on screen survived into it — a switch
        narrowing what you are looking through — so the picture stays and the
        Funestra is handed the new pass around it.  Without it the pass has
        stood somewhere else up, and the view follows.
        """
        if kept:
            self._hand_over(land=False)
        else:
            self._show_current()

    # --- what the Funestra plays --------------------------------------------

    def _show_current(self):
        """Stand the Funestra on the current item, which holds a picture for
        the pace and ends it the way it ends a finished clip."""
        if self._live:
            # Nothing on disk yet: the run's own frames stand in for a slide.
            if self._frame is not None:
                self._put_the_followed_run_up(self._frame)
            else:
                self._pane.show_message(GENERATING)  # opened before the first one
            return
        slide = self._playlist.current()
        if slide is None:
            return
        self._levels.restart()  # a new item, so its own versions from the top
        self._hand_over(land=True)
        self._show_what_is_being_made()
        self._move_on_early_from(slide)
        self._refresh_note()  # the note belongs to whatever is on screen now
        self._apply_freeze()  # a slide arrived at under a freeze arrives frozen
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    def _hand_over(self, *, land: bool) -> None:
        """Give the Funestra this pass to play, turned onto the slide this show
        stands on; *land* opens that slide afresh, where a pass handed over
        around the slide already up leaves it playing."""
        current = self._playlist.current()
        rotated = rotated_onto(self._playlist.in_play_order(), current)
        items = [self._player_item(slide) for slide in rotated]
        if land and current is not None:
            self._showing = self._file_of(current)
            self._showing_media = None if current.is_live else (current.path, current.media_type)
            self._frames_on_screen = False
            self._frame_on_player = None
        self._pane.hand_over(items, land=self._showing if land else None)
        self._settle()

    def _settle(self) -> None:
        """Hand the Funestra the pace and the hold, and take its reading of
        the pass as the one this show stands on."""
        playback = self._pane.playback
        if playback is None:
            return
        playback.set_pace(self._dwell_s)
        # A lock is repeat-one, as it is on a Fun Time satellite; a show
        # following a run holds its frames the same way, and so does a pace
        # of nought, since nought means nothing moves on its own -- a finished
        # clip included.
        playback.set_locked(self._playlist.locked or self._live or not self._dwell_s)
        self._loads_seen = playback.loads
        self._refusal_checked = False
        self._held_s = 0.0
        self._last_tick = self._clock()

    def _the_funestra_opened(self) -> None:
        self._settle()
        self._show_what_is_being_made()
        self._apply_freeze()

    def _player_item(self, slide) -> PlaylistItem:
        if slide.is_live:
            return PlaylistItem(self._file_of(slide))
        return slide_item(slide)

    def _file_of(self, slide) -> Path:
        if slide.is_live:
            return self._frames.first_of(slide.prompt_id)
        return Path(str(slide.path))

    def _as_the_funestra_sees_it(self, playback):
        return SlideshowOnAFunestra(self)

    def follow_the_funestra(self) -> None:
        """The pass of this show's own the Funestra gives it each frame: stand
        the set on whatever the Funestra moved onto by itself -- a picture's
        pace ran out, a clip ended -- step past an item it would not open,
        and move a picture being enhanced on early."""
        playback = self._pane.playback
        if playback is None:
            return
        now = self._clock()
        if playback.loads != self._loads_seen:
            self._loads_seen = playback.loads
            self._refusal_checked = False
            self._held_s = 0.0
            video = playback.current_video
            if video != self._showing:
                self._showing = video
                self._follow(video)
        elif not (self._paused or self._playlist.locked_or_paused()):
            self._held_s += now - self._last_tick
        self._last_tick = now
        if not self._refusal_checked and playback.idle:
            self._refusal_checked = True
            self._on_media_unplayable()
        self._move_on_early()

    def _follow(self, video: Path) -> None:
        """Stand the pass on the item the Funestra just moved to: how the map,
        the star and every word about "this one" find out which item that is."""
        for index, item in enumerate(self._playlist.items):
            if self._file_of(item) == video:
                self._playlist.jump_to(index)
                self._levels.restart()
                self._frames_on_screen = False
                self._frame_on_player = None
                self._showing_media = None if item.is_live else (item.path, item.media_type)
                self._show_what_is_being_made()
                self._move_on_early_from(item)
                self._refresh_note()
                self._apply_freeze()
                self.media_changed.emit()
                return

    def _open_again(self) -> None:
        """Open the slide on screen afresh -- the engine reads the pace as it
        opens a file, and a released lock's dwell starts counting again."""
        self._show_current()

    def _move_on_early_from(self, slide) -> None:
        held_for = self._set.pace_for(slide, self._dwell_s)
        self._moves_on_early = held_for < self._dwell_s and not self._playlist.locked
        self._held_s = 0.0

    def _move_on_early(self) -> None:
        if not (self._moves_on_early and self._dwell_s):
            return
        current = self._playlist.current()
        if current is None or self._held_s < self._set.pace_for(current, self._dwell_s):
            return
        self._moves_on_early = False
        playback = self._pane.playback
        if playback is not None and not self._playlist.locked_or_paused():
            playback.step(1)

    def _apply_freeze(self) -> None:
        """Hand the Funestra whatever is holding the show still.

        The room's freeze stops everything.  A spoken request stops the show
        moving on rather than stopping the clip: it is about what is on screen,
        and a clip that stopped mid-sentence would be answering a question
        nobody asked.  A picture under one holds where its move had got to,
        since the alternative is its dwell running out and starting over under
        the speaker.
        """
        request_stills_a_picture = self._playlist.paused and not self._showing_a_video()
        held = self._paused or request_stills_a_picture
        playback = self._pane.playback
        if playback is not None:
            playback.set_paused(held)

    def _showing_a_video(self) -> bool:
        return (self._showing_media is not None and not self._frames_on_screen
                and self._showing_media[1] == MediaType.VIDEO)

    def _current_video_path(self):
        """The clip on screen, or None for a picture -- what a funscript lookup
        and the device drive key off."""
        return self._showing_media[0] if self._showing_a_video() else None

    def set_playlist(self, items, index: int) -> None:
        """Re-seed the set this show plays, on ``index``.

        What a double-clicked picture's show is armed with once the gallery has
        worked out the folder under it: the view comes up on the one item the
        pane had, and this hands it the rest in the browser's own order. A view
        still following a generation keeps its frames — it has no place among
        those files until an arrow leaves them for one.
        """
        self._set.reseed(items, start=index, shuffle=in_order)
        if not self._live:
            self._show_current()

    def whole_set(self) -> list[Slide]:
        return self._set.whole_set()

    @property
    def filters(self) -> ShowFilters:
        return self._set.filters

    def take_up(self, filters: ShowFilters, *, keep_the_slide: bool = False) -> None:
        if not self._live:
            self._set.take_up(filters, keep_the_slide=keep_the_slide)

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm Shift+Left/Right to step an item's versions.

        ``levels_by_path`` maps the file the set shows an item under to that
        item's versions, newest first, as ``(path, media_type, label)``. Plain
        Left/Right still steps the set; the shifted pair moves within the one
        item — its own axis, because a version is not a neighbor.
        """
        self._levels.arm(levels_by_path)
        self.refresh_panel()

    def add_levels(self, levels_by_path: dict) -> None:
        self._levels.add(levels_by_path)
        self.refresh_panel()

    # --- the panel this show wears ------------------------------------------

    def wear_the_hud(self, side: str, *, dashboard_cmd_file=None, label_for=None,
                     corner: HudCorner = HudCorner.UPPER_LEFT, minimized: bool = False,
                     collapse=None) -> None:
        """Put the players' own panel on this show, drawn by the Funestra.

        *side* is whose panel it is, which spells its verbs; *dashboard_cmd_file*
        is the session's command channel, or ``None`` standalone -- which is also
        how a press knows which of the two it is on (see :meth:`press`);
        *label_for* names the item on screen in this app's own vocabulary, and
        *collapse* is what parks the panel in its corner where there is no
        session to ask.
        """
        self._hud_side = side
        self._dashboard_cmd_file = dashboard_cmd_file
        self._label_for = label_for
        self._corner, self._minimized = corner, minimized
        self._collapse = collapse
        self.refresh_panel()

    @property
    def hud_side(self) -> str:
        return self._hud_side

    def set_hud_place(self, corner, minimized: bool) -> None:
        if (corner, minimized) == (self._corner, self._minimized):
            return
        self._corner, self._minimized = corner, minimized
        self.refresh_panel()

    def refresh_panel(self) -> None:
        """The panel's answer may have changed under a press that redraws on
        no signal of its own: the next frame rebuilds it rather than the beat."""
        self._panel_stale = True

    def _hud_model(self):
        """The panel as the Funestra draws it, rebuilt on its own beat -- and
        faster while the drive's trace is moving across it."""
        if not self._hud_side:
            return None
        now = self._clock()
        beat = REPAINT_MS if self._panel_moving() else _REFRESH_MS
        if not self._panel_stale and (now - self._panel_built_at) * 1000 < beat:
            return self._panel_model
        self._panel_stale = False
        self._panel_built_at = now
        model = show_hud_model(self._hud_side, self,
                               hosted=self._dashboard_cmd_file is not None,
                               device=self.hud_device, foot=self._queue())
        if model is not None:
            model = replace(model, hud_corner=self._corner, hud_minimized=self._minimized)
        self._panel_model = model
        return model

    def _panel_moving(self) -> bool:
        return self._panel_model is not None and self._panel_model.osr2 in _MOVING

    def item_label(self) -> str:
        """The muted line under the status: what is on screen right now, named
        the way THIS app names it — the folder as the tree shows it and the
        item by its seed, not "image / ComfyUI_00123_" off the path."""
        prompt_id = self.hud_prompt_id
        if not prompt_id or self._label_for is None:
            return ""
        try:
            return self._label_for(prompt_id) or ""
        except Exception:  # naming is decoration; it never costs the panel
            return ""

    def press(self, command: str) -> bool:
        """Route one press on the panel, as the Funestra hands it over: the
        block at the foot takes the pointer, what the show answers for itself
        lands on it, the session's transport goes out on the dashboard channel
        — or, with no session under this show, onto the show as well
        (:meth:`_act_here`) — and the device's own verbs land on this window
        either way, the OSR2 being this app's to drive wherever the show is
        drawn.  A press on the picture itself asks for the pause.
        """
        verb, _, payload = command.partition("|")
        if verb in _FOOT_VERBS:
            self._press_the_queue(verb, payload)
            self.refresh_panel()
            return True
        if verb == OMNIPAUSE_TOGGLE:
            self._toggle_pause()
            return True
        action, path = side_press(self._hud_side, verb, payload)
        if action in COLLAPSES:
            self._collapse_here_or_out_there(command, COLLAPSES[action])
            return True
        if action in THE_SHOWS_OWN:
            # The two filters, reset, the loops, the expand mark and the map's
            # own clicks mean on a show what they mean on a player, and the
            # show owns what each is — so they land here, hosted or not.
            answer(self, action, path)
            self.refresh_panel()
            return True
        if self.press_console(verb):
            self.refresh_panel()
            return True
        if self._dashboard_cmd_file is None:
            return self._act_here(action)
        allowed = ("satellites_kino_activate", "origenerator_activate",
                   *(spelled_for(self._hud_side, verb)
                     for verb in ("prev", "next", "lock", "trash")))
        if command not in allowed:
            return False
        append_command(self._dashboard_cmd_file, command)
        return True

    def _press_the_queue(self, verb: str, payload: str) -> None:
        numbers = [int(part) for part in payload.split("|")]
        if verb == FOOT_WHEEL:
            self._queue_pointer.wheel(*numbers)
        elif verb == FOOT_PRESS:
            self._queue_pointer.press(*numbers)
        elif verb == FOOT_DRAG:
            self._queue_pointer.drag(*numbers)
        else:
            self._queue_pointer.release(*numbers)

    def _collapse_here_or_out_there(self, command: str, minimized: bool) -> None:
        if self._dashboard_cmd_file is not None:
            append_command(self._dashboard_cmd_file, command)
            return
        if self._collapse is not None:
            self._collapse(minimized)

    def _act_here(self, action: str) -> bool:
        """A press with no session under it: the show answers it itself.

        Standalone there is no command file to take the round trip a hosted
        press takes, so the press lands on the show through the same answers
        that round trip would have ended at.  Minimize is the one button only a
        show on its own has, the show being the window here; the rate is the
        Funestra's own, as on every player.
        """
        if action == "minimize":
            self.window().showMinimized()
            return True  # nothing on the panel changed, and it is off screen anyway
        if action in ("speed_up", "speed_down"):
            playback = self._pane.playback
            if playback is not None:
                playback.set_speed(playback.speed + (RATE_STEP if action == "speed_up" else -RATE_STEP))
            return True
        if answer(self, action):
            self.refresh_panel()  # the readout answers the press without waiting for the beat
            return True
        return False

    # --- the queue block at the panel's foot ---------------------------------

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        """Take what is in flight — the same list, in the same order, the lower
        strip this view is covering would be showing."""
        self._queue_items = list(items)
        self._foreign_queued = foreign_queued
        self.refresh_panel()

    @property
    def hud_queue(self) -> tuple[list, int]:
        """What is in flight, and how much of ComfyUI's queue is another app's —
        what the panel draws at its foot."""
        return self._queue_items, self._foreign_queued

    def _queue(self):
        return queue_section(self._queue_items, self._foreign_queued,
                             first=self._queue_pointer.first,
                             drop_at=self._queue_pointer.drop,
                             pointer=self._queue_pointer)

    def requeue(self, keys) -> None:
        """Re-line the queue in this order — a row dragged somewhere else on the
        panel.

        Re-listed here and then, rather than waiting for the poll that confirms
        it: the queue's agreement is a second and a half away, and a row that
        springs back to where it was reads as a failure.
        """
        by_key = {item.key: item for item in self._queue_items}
        self._queue_items = [by_key[key] for key in keys if key in by_key]
        if self._actions.requeue is not None:
            self._actions.requeue(list(keys))

    def clear_foreign_queue(self) -> None:
        """Drop another app's work off ComfyUI, as the block's Clear asks."""
        if self._actions.clear_queue is not None:
            self._actions.clear_queue()

    # --- picking a closed show back up --------------------------------------

    def state(self) -> ShowState:
        """Where this show is, in the terms a later one can be opened at."""
        return ShowState(
            order=tuple(self._playlist.order_ids()),
            current=self._current_prompt_id(),
            locked=self._playlist.locked,
            level_index=self._levels.index,
            loop=self._set.loop.axis if self._set.loop is not None else "",
        )

    def resume(self, state: ShowState) -> bool:
        """Open where a closed show left off rather than at the top of a fresh
        shuffle, and say whether the place carried.

        Closing a show is usually a detour, so coming back is coming back to
        that picture: the slide it ended on, its lock, and the version it had
        been stepped to -- which is why this is called after
        :meth:`set_levels`.  It carries only while that slide is among these
        items.
        """
        if self._live or not self._playlist.resume(state.order, state.current):
            return False
        if state.loop:
            self._set.start_loop(state.loop)
        self._playlist.set_locked(state.locked)
        led = self._set.lead_with_what_is_being_made()
        self._show_current()
        if state.level_index and not led:
            # A fresh slide sits at its top version, so the remembered index is
            # exactly the number of steps down to the one that was on screen.
            self._step_level(state.level_index)
        return True

    def note_added(self, path, media_type: str, prompt_id: str, still=None, *,
                   favorite: bool = False, enhanced: bool = False) -> None:
        """A generation that belongs to what this show is playing has landed:
        it joins the set, queued to come up next, so a show of a folder that is
        auto-generating reaches the items being made while it runs.
        ``favorited`` and ``enhanced`` are what the gallery knows of its row.

        The slide on screen is left alone; one the show has been watching being
        made keeps its place in the pass and simply becomes the file.
        """
        if favorite:
            self._set.favorite_ids.add(prompt_id)
        if enhanced:
            self._set.enhanced_ids.add(prompt_id)
        slide = Slide(path, media_type, prompt_id, still)
        self._set.remember(slide)
        if self._playlist.replace_live(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._show_current()  # the file itself now
            else:
                self._hand_over(land=False)
            self._frames.forget(prompt_id)
            return
        # Into the pass only past the switches: a show narrowed to its favorites
        # must not fill back up with every unfavorited thing the loop makes.  The
        # whole set remembers it either way, for when the switch comes off.
        if self._set.passes(slide) and self._playlist.add(slide):
            self._hand_over(land=False)

    def note_generating(self, prompt_id: str, frame: bytes) -> None:
        """A generation that belongs to what this show is playing has started to
        look like something: it joins the set on that first frame, and keeps
        whichever is newest from there.

        The wait is not worth a slide, but the first iterations arriving are the
        best thing in a folder that is filling — so the show puts them up as soon
        as there is anything to see, queued to come up next like any other
        arrival, rather than waiting out the minutes to the finished file.

        Offered once. A run taken off the show (its Up key) does not come back on
        its next frame, which would make that key mean nothing at all.
        """
        if self._live:
            return  # already following one run full-screen; this is that job
        if self._playlist.update_live(prompt_id, frame):
            if self._current_prompt_id() == prompt_id:
                self._put_a_frame_up(self._frames.write(prompt_id, frame))
            return
        if (self._set.first_offer_of(prompt_id) and self._frames.write(prompt_id, frame)
                and self._set.join_live(prompt_id, frame)):
            self._hand_over(land=False)

    def _put_a_frame_up(self, path) -> None:
        playback = self._pane.playback
        if path is None or playback is None or path == self._frame_on_player:
            return
        self._frame_on_player = path
        playback.show_frame(path)

    def note_in_flight(self, prompt_ids) -> None:
        """Which runs are still being made, so a slide that has stopped being one
        leaves rather than holding the pass with the half-finished frame it got
        to. Cancelled and failed runs are what this is for; a finished one is out
        of this set too, but by then it is a file (:meth:`note_added`) and no
        longer a live slide to drop.
        """
        for prompt_id in [pid for pid in self._set.live_ids() if pid not in prompt_ids]:
            showing = self._current_prompt_id() == prompt_id
            self._playlist.drop(prompt_id)
            self._set.forget_id(prompt_id)
            self._frames.forget(prompt_id)
            if self._playlist.is_empty():
                self.close()  # a show of nothing but that run has nothing left
                return
            if showing:
                self._show_current()
            else:
                self._hand_over(land=False)

    def holds(self, prompt_id: str) -> bool:
        """Whether this show already has a slide for that generation — what the
        gallery asks before working out whether a run belongs in here at all."""
        return self._playlist.holds(prompt_id)

    def release_media(self, paths):
        """Let go of any of ``paths`` on screen — a file about to be deleted (its
        own Up key condemns the item it's playing): the Funestra holds an open
        handle on whatever it is playing."""
        wanted = {str(path) for path in paths}
        if self._showing is None or str(self._showing) not in wanted:
            return
        playback = self._pane.playback
        if playback is not None:
            playback.let_go()
        self._showing = None
        self._showing_media = None

    def _delete_current(self):
        """Up, the players' "weird": a favorite loses its star and the show
        moves on; anything else is deleted (if a deleter is wired) and the show
        moves on.

        Two things on one key, as on a satellite, and the star on screen says
        which: locking a slide starred it, so the first press takes that back
        and only the second condemns it.  A slide still being made has nothing
        to condemn, so Up takes it off the show and leaves the run alone --
        calling one off is the Cancel on that run's own row of the panel.
        """
        self._playlist.unlock()  # the locked slide is the one being culled
        item = self._playlist.current()
        if item is None:
            return
        if self._set.unfavorite_current(self._actions.unfavorite):
            self._flash_note("Unfavorited")
            self._step(1)
            return
        if (self._actions.delete is not None
                and item.prompt_id is not None and not item.is_live):
            self._actions.delete(item.prompt_id)
        # Out of the whole set too, so widening a switch back cannot resurrect it.
        self._set.forget(item)
        self._playlist.remove_current()
        self._frames.forget(item.prompt_id)
        if self._playlist.is_empty():
            self.close()
            return
        if self._set.end_a_loop_of_one():
            self._lock_what_the_cull_left()
        self._show_current()

    def _lock_what_the_cull_left(self) -> None:
        """A row worn down to one picture plays that picture over and over,
        which is the lock — so the cull that wore it down ends the loop and
        locks what is left, as a satellite's does.  The lock is the state and
        nothing else: none of what a pressed lock also does — the star, the
        better version, the gallery — happened, because nobody pressed one.
        The flip is a lock because the cull released it three lines up."""
        self._playlist.toggle_lock()
        self._flash_note("Locked")

    def _step(self, delta: int):
        """Manual stepping — an arrow, or the console's transport: moving off a
        slide releases its lock, so the way out of a lock is the same key that
        got you anywhere else, not a second press of the one that set it."""
        if self._live and self._playlist.is_empty():
            return  # a run with no folder armed under it: nowhere to step to
        self._playlist.unlock()
        self._live = False  # stepped off a live generation: its frames stop landing
        self._set.step(delta)
        self._show_current()

    @property
    def has_other_versions(self) -> bool:
        """Whether the item on screen was filed more than once — what draws the
        band's versions button live rather than faded."""
        return len(self._levels.levels(base=self._current_base())) > 1

    def show_step_version(self, delta: int) -> None:
        self._step_level(delta)

    def _step_level(self, delta: int) -> None:
        """Step ``delta`` versions within the item on screen: an image's
        enhancement levels, or a video's Evolver upscale and the video itself.

        A no-op for an item with one version — there is nothing to compare it
        against, and silently doing nothing is better than stepping the set
        when the shift was the whole point.
        """
        level = self._levels.step(delta, base=self._current_base())
        if level is None:
            return
        self._live = False
        self._frames_on_screen = False
        self._put_up(*level[:2])
        self.media_changed.emit()

    def _put_up(self, path, media_type: str) -> None:
        """Open a file on the Funestra in the slide's place -- one of the
        slide's own versions -- as the one it is standing on."""
        item = playlist_item(path, media_type)
        self._showing = item.path
        self._showing_media = (path, media_type)
        self._frame_on_player = None
        playback = self._pane.playback
        if playback is not None:
            playback.play_file(item.path, item.funscript)
            self._loads_seen = playback.loads

    # --- opened over a generation still being made --------------------------

    def is_live(self) -> bool:
        """Whether this show is still following a generation in flight — the pane
        that opened it checks before feeding it another frame or its result."""
        return self._live

    def show_frame(self, data: bytes) -> None:
        """One more streamed frame of the generation being followed. Ignored once
        it has landed (or the show has stepped away), which is no longer this run."""
        if self._live:
            self._frame = data
            self._put_the_followed_run_up(data)

    def _put_the_followed_run_up(self, data: bytes) -> None:
        """The run's newest frame in the place of a slide: on the Funestra's
        move while it holds the screen, opened on it where nothing is up yet."""
        path = self._frames.write(_FOLLOWED, data)
        if path is None:
            return
        self._showing_media = None
        if self._pane.playback is None:
            self._showing = path
            self._pane.hand_over([PlaylistItem(path)])
            self._settle()
            self._apply_freeze()
            return
        self._put_a_frame_up(path)

    def show_landed(self, media: tuple, generation: str | None) -> None:
        """The followed generation finished: its saved file takes the place of
        its frames, at the head of the folder the show was armed with."""
        if not self._live:
            return
        self._live = False
        folder = [slide for slide in self._set.all_items if slide.prompt_id != generation]
        self._set.reseed([Slide(*media, generation), *folder], shuffle=in_order)
        self._frames.forget(_FOLLOWED)
        self._show_current()

    # --- what Genau's console acts on here ---------------------------------
    # Its transport steps Genau's clips and its clip-seconds pace how long an
    # unlocked one stays up. Here the clips are the slides, so the same four
    # buttons step, lock and cull them, and the same pair sets the dwell.

    @property
    def dwell_s(self) -> int:
        """The seconds this show leaves an unlocked slide up — nought while it is
        standing on one picture, which is how a double-clicked one opens."""
        return self._dwell_s

    @property
    def locked(self) -> bool:
        """Whether what is on screen is locked — the console's padlock."""
        return self._playlist.locked

    @property
    def locked_on(self) -> str | None:
        return self._current_prompt_id() if self.locked else None

    # --- the transport, for whoever is driving: a key, the console, a word ---

    def step(self, delta: int) -> None:
        """Move a slide either way — what the arrows do, for a caller with no
        keyboard to press them with."""
        self._step(delta)

    def toggle_lock(self) -> None:
        """Lock the slide on screen, or let it go — Down's whole gesture."""
        self._lock_current()

    def cull(self) -> None:
        """Take the slide on screen away and move on — Up's."""
        self._delete_current()

    def show_reset(self) -> None:
        """Put the side back how it started, the players' own reset: both
        switches dropped, the lock released, and the base set on screen again.

        Hosted, "how it started" is the REGION's base state, not this show's
        own: a player's reset drops its filter and leaves it browsing its whole
        library again, so a show started on one folder goes back to the library
        too rather than restarting that folder.  The gallery owns that set, so
        it comes in as a hook.  Standalone there is no such state and a show's
        defaults are simply its own set from the beginning.
        """
        if self._actions.reset is not None:
            self._actions.reset(self)
            return
        self.reset_in_place()

    def show_order(self, *, latest: bool) -> None:
        if self._actions.reorder is not None:
            self._actions.reorder(self, latest)

    def reset_in_place(self) -> None:
        """This show's own reset: both switches dropped, the lock released, and
        the top of the set it is already playing back on screen."""
        self._playlist.unlock()
        if self._set.drop_the_filters():
            return  # the fresh pass is on screen already (see _pass_changed)
        self._playlist.restart()
        self._show_current()

    def retune(self, items, *, enhanced_ids=None) -> None:
        """Point this show at the region's base set instead -- what a hosted
        reset does, with the window left up because a region that blinks black
        between two shows is what the base state exists to avoid.

        A base state is always the same kind of set: a fresh shuffle of that
        side's whole library, no loop, both switches and the lock off, the
        favorited ids it had kept.  ``enhanced_ids`` is which of the new items
        carry an enhancement.
        """
        self._live = not items
        self._set.retune(items, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=(),
                keep_slide: bool = False) -> None:
        self._live = not items
        self._set.reorder(items, latest=latest, enhanced_ids=enhanced_ids,
                          keep_slide=keep_slide)

    @property
    def hud_order_label(self) -> str:
        """How the set is ordered, in the players' words — read off this view
        by the show's own panel (see
        :class:`~origenerator.gui.show_host.ShowHost`)."""
        return self._set.order_label

    # --- the map, and the loops along it -----------------------------------

    def hud_map(self):
        """The map the HUD draws around the slide on screen."""
        return self._set.map()

    def pass_size(self) -> int:
        """How many slides the pass on screen holds — what a narrowing is
        answered with."""
        return len(self._playlist)

    def show_loop(self, axis: str) -> None:
        """Loop the map's *axis* around the slide on screen, or end the loop
        for "" — the map's two loop buttons, and the session's spoken loops.
        An axis holding only the slide on screen is held rather than looped
        (:meth:`_lock_instead_of_looping`)."""
        if not axis:
            if self._set.end_loop(self._browse_it_all):
                self._flash_note("Loop off")
            return
        if self._set.start_loop(axis):
            self._flash_note(looping_note(self._set))
        else:
            self._lock_instead_of_looping()

    def _lock_instead_of_looping(self) -> None:
        """Lock the slide on screen: the answer a loop asked of a row of one
        gets on a player, where the loop button of a group holding one clip
        locks that clip.  A row that size is the slide itself, so the press
        means "this one" rather than nothing; and a lock is not a loop, so a
        loop that was running is dropped."""
        self._set.end_loop()
        self.set_locked(True)
        self._flash_note("Locked")

    def _browse_it_all(self) -> bool:
        if self._actions.browse_all is None:
            return False
        return bool(self._actions.browse_all(self))

    def show_loop_cycle(self) -> None:
        """The loop key, as on a player: seeds, then actions, then off — and
        the lock when there is nothing on either axis to loop, which is Down's
        whole gesture here."""
        stepped = self._set.step_loop(self._browse_it_all)
        if stepped == LOOP_IS_A_LOCK:
            self._lock_current()
            self._flash_note("Locked" if self._playlist.locked else "Unlocked")
        elif stepped == LOOP_OFF:
            self._flash_note("Loop off")
        else:
            self._flash_note(looping_note(self._set))

    def show_more_seeds(self) -> None:
        """Widen the seed row past what exactly matches and loop it — the
        map's expand mark."""
        if self._set.more_seeds():
            self._flash_note(_MORE_SEEDS)
        else:
            self._flash_note(_WIDENING_FAILED, kind=WARNING)

    def show_filter(self, query: str) -> None:
        """The button at the head of a map row, and the session's spoken acts.

        A configuration's row is gone to and its seeds looped, the way it was
        before the acts joined the column; an act's narrows the show to it.
        """
        row = self._set.configuration_row(query)
        if row is not None:
            if row is not self._playlist.current():
                self._jump_to(row)
            self.show_loop(SEED_AXIS)
            return
        said, narrowed = narrow_to_acts(self._set, query)
        self._flash_note(said, kind=NOTICE if narrowed else WARNING)

    def show_filter_to_the_act_on_screen(self) -> None:
        said, narrowed = narrow_to_the_act_on_screen(self._set)
        self._flash_note(said, kind=NOTICE if narrowed else WARNING)

    @property
    def hud_act_filter(self) -> str:
        """The act(s) the set is narrowed to — what lights the map's row
        buttons (see :class:`~origenerator.gui.show_host.ShowHost`)."""
        return self._set.filters.act

    def show_nav(self, direction: str) -> None:
        """Step to the map cell one *direction* from the lit one, the way a
        thumbnail click lands on it."""
        target = self._set.nav_target(direction)
        if target is None:
            self._flash_note(_NOTHING_THAT_WAY, kind=WARNING)
            return
        self._jump_to(target)

    @property
    def hud_device(self):
        """What this window is doing to the OSR2, for the one panel to draw —
        None with no motion wired, and so no device half at all."""
        if self._motion is None:
            return None
        control = self._actions.osr2_control
        return show_device(
            self._motion, self, device_on=bool(osr2_device.device_on()),
            control=control.state() if control is not None else "",
            script=control.script if control is not None else None)

    def press_console(self, action: str) -> bool:
        """Take a press off the device rows of that panel — the pace, the
        motion, the four control states, a level dragged on the readout."""
        if self._motion is None:
            return False
        return post_console_action(action, motion=self._motion, host=self,
                                   control=self._actions.osr2_control)

    def set_audio_muted(self, muted: bool) -> None:
        """Silence (or voice) this show outright — what a hosting session does
        to a show landing on a satellite region."""
        self._pane.set_audio_muted(muted)

    def set_locked(self, locked: bool) -> bool:
        """Lock the slide on screen or let it go, saying which way rather than
        flipping; ``True`` when that moved it.

        Spoken "lock" and "unlock" are two words for a reason: someone talking
        to a picture is asking for a state, not for the other one — and cannot
        see the counter's padlock to know which the flip would give them.
        Locking is Down's whole gesture here, star and enhance included, because
        that is what locking means in this view and a spoken lock must not
        quietly mean less than a pressed one.
        """
        if locked == self._playlist.locked:
            return False
        self._lock_current() if locked else self._flip_lock()
        return True

    def favorite(self) -> bool:
        """Bookmark the slide on screen; ``False`` when there is nothing to
        bookmark — a live generation has no row of its own yet."""
        item = self._playlist.current()
        if self._actions.favorite is None or item is None or item.prompt_id is None:
            return False
        self._actions.favorite(item.prompt_id)
        self._set.favorite_ids.add(item.prompt_id)  # the star readout and F-mode follow it
        return True

    # The motion console reaches the three above by its own names: it drives this
    # view through a host protocol the main window's console shares.
    def show_step(self, delta: int) -> None:
        self.step(delta)

    def show_toggle_lock(self) -> None:
        self.toggle_lock()

    def show_cull(self) -> None:
        self.cull()

    def set_dwell_s(self, seconds: int) -> None:
        """Take a new pace, and hand it on: the number is app-wide, so a show
        opened at nought that is turned up sets the pace for the next one too.

        Applied here as well as posted to the pace, rather than only waiting for
        the signal back — a show sitting at nought while the app-wide pace already
        reads one gets no signal from a step up to one, and would stay frozen.
        """
        self._pace.set_seconds(seconds)  # fires _on_pace_changed if it moved
        self._apply_dwell(self._pace.seconds)  # and take it even if it didn't

    def is_showing(self) -> bool:
        """Whether this show is on screen — what says a region is occupied."""
        return self.isVisible()

    # --- what this show's HUD says, in the players' vocabulary -------------

    @property
    def hud_prompt_id(self) -> str:
        """The generation on screen, by id — what names it on the HUD.

        The id rather than the file, because what the panel prints is this
        app's own name for the item (its folder and its seed), and only the
        row under the id carries either.
        """
        current = self._playlist.current()
        return current[2] if current and len(current) > 2 else ""

    @property
    def hud_is_favorite(self) -> bool:
        """Whether the item on screen is a favorite (favorited) — the players'
        star readout, over the same collection the Favorites shelf lists."""
        return self._set.is_favorite

    @property
    def hud_favorites_filter(self) -> bool:
        return self._set.filters.favorites

    @property
    def hud_enhanced_mode(self) -> bool:
        """Whether the show is narrowed to the pictures that have been enhanced
        — the switch beside F-mode on its HUD."""
        return self._set.filters.enhanced

    def toggle_favorites_filter(self) -> bool:
        """Narrow the set to the favorites, or widen it back — the players' own
        F-mode, over the favorited items.  ``True`` when the switch moved."""
        return self.set_favorites_filter(not self._set.filters.favorites)

    def toggle_enhanced_mode(self) -> bool:
        """Narrow the set to the pictures that have been enhanced, or widen it
        back — the HUD's switch beside F-mode.  ``True`` when the switch moved."""
        return self.set_enhanced_mode(not self._set.filters.enhanced)

    def set_favorites_filter(self, on: bool) -> bool:
        return self._set.set_filters(replace(self._set.filters, favorites=bool(on)))

    def set_enhanced_mode(self, on: bool) -> bool:
        """Said which way rather than flipped — a speaker mid-show is not
        looking at the HUD to see which way it stands."""
        return self._set.set_filters(replace(self._set.filters, enhanced=bool(on)))

    def clear_modes(self) -> bool:
        """Every switch off at once — what "clear filter" has to mean once
        there is more than one to clear."""
        return self._set.set_filters(ShowFilters())

    def show_item(self, path, *, lock: bool = False) -> None:
        """Jump to the item the HUD map named — a thumbnail click, the same
        jump a satellite's map makes; *lock* keeps it there (the double-click),
        exactly as it locks a player's clip."""
        slide = self._set.slide_for_path(path)
        if slide is None:
            return
        self._jump_to(slide)
        if lock and not self._playlist.locked:
            self._flip_lock()

    def _jump_to(self, slide) -> None:
        """Stand the show on *slide*, wherever the map found it: the lock
        comes off, the way any step off a locked slide takes it off."""
        self._playlist.unlock()
        self._live = False
        self._set.jump_to(slide)
        self._show_current()

    def set_paused(self, paused: bool) -> None:
        """Freeze or resume the show whole, with the room.

        Distinct from the lock: a lock holds one slide by choice and replays
        its clip; this stops time itself.  The Funestra's clock is the show's,
        so a frozen picture stops counting down its dwell and a frozen clip
        stops playing, and a slide stepped to while frozen arrives frozen too.
        """
        self._paused = paused
        self._apply_freeze()

    def _toggle_pause(self) -> None:
        if self._actions.omnipause is not None:
            self._actions.omnipause()
        else:
            self.set_paused(not self._paused)

    def _on_pace_changed(self, seconds: int) -> None:
        """The pace moved — here or in another window — so the slide on screen
        takes the new one rather than waiting out the old."""
        self._apply_dwell(seconds)

    def _apply_dwell(self, seconds: int) -> None:
        seconds = max(0, int(seconds))
        if seconds == self._dwell_s:
            return
        self._dwell_s = seconds
        self._playlist.image_dwell_ms = seconds * 1000
        if self._live:
            return
        playback = self._pane.playback
        if playback is None:
            return
        playback.set_pace(self._dwell_s)
        if not self._playlist.locked:
            # The engine reads the pace when it opens the file, so the picture
            # on screen takes the new pace by being opened again.
            self._open_again()

    def _on_media_unplayable(self):
        """A file the Funestra will not open: step past it, whatever holds it.

        Unlike a clip that ended, this one never will, so the replay a lock or
        a pace of nought asks for would hold a black screen for the rest of the
        session.  The item stays in the set — the fault is the backend's, not
        the file's — but the show moves on.

        A pause is the one stop this yields to: the show is frozen, and a show
        that walked its set looking for something playable would be moving.
        The black rectangle waits for the resume.
        """
        if self._paused or self._live:
            return
        logger.warning("Slideshow: a clip would not play; stepping past it")
        self._playlist.unlock()
        self._set.step(1)
        self._show_current()

    # --- the pause a spoken request puts on the show -----------------------

    def pause_for_request(self, paused: bool, note: str = "") -> None:
        """Stop (or release) the advance while a request is being spoken.

        Not the user's lock: a slide they had locked is still locked when the
        request ends, and one they hadn't goes back to its dwell. ``note`` is
        what the corner should say while the show waits — the only sign, in a view
        with no panels, that the mic is taking a sentence.
        """
        self._playlist.set_paused(paused)
        if paused:
            self._note_timer.stop()  # it holds, rather than fading after a beat
            self._request_note = note
        else:
            self._request_note = ""
        self._refresh_note()
        self._apply_freeze()

    def note_request(self, message: str, request=None, *,
                     working: bool = False, kind: str = NOTICE) -> None:
        """Say what the spoken *request* did, where the speaker is looking.

        *working* means it has not done it yet, so the corner holds that line
        rather than flashing it: working out what a request changes can mean
        asking the local LLM, which outlasts a flash.  It comes down only for
        the request that put it up -- a second request said over the first
        would otherwise blank the corner while that one is still out -- and any
        other answer flashes over it and leaves it standing.
        """
        if working:
            self._working_note, self._working_request = message, request
            self._note_timer.stop()  # it holds, rather than fading after a beat
            self._refresh_note()
            return
        if request is self._working_request:
            self._working_note, self._working_request = "", None
        self._flash_note(message, ms=3000, kind=kind)

    def _lock_current(self):
        """Down: lock the slide, favorite it, and ask for it to be enhanced.

        Stopping on a picture is the gesture that says you want it, so it is
        also the one that favorites it and the one that asks for the better version
        — nothing extra to press, and the run happens while you keep looking at
        it. Releasing the lock asks for nothing; only stopping does, and only on
        a picture that has never been enhanced (the gallery's call).
        """
        locked = self._flip_lock()
        if locked:
            self._enhance_current()

    def _enhance_current(self):
        """Ask the gallery to enhance the slide on screen, if it wants one.

        The gallery decides whether it does — it is the one that knows whether
        this image has already been enhanced or has a run on its way, which the
        lock makes first.  ``True`` back means a run started, and the HUD says
        so until the finished version arrives.
        """
        if self._actions.enhance is None:
            return
        if self._playlist.current_is_live():
            return  # no file yet to make a better version of; the lock still holds
        prompt_id = self._current_prompt_id()
        if prompt_id is None:
            return
        if self._actions.enhance(prompt_id):
            self._set.note_enhancement_asked(prompt_id)
            self.refresh_panel()

    def note_enhanced(self, prompt_id: str, path, media_type: str = MediaType.IMAGE,
                      still=None) -> None:
        """An enhancement of one of these items landed: the show points at it
        from here on, wherever that item sits in the running order.

        Not only while it is the one on screen. It was asked for minutes ago and
        the show may have paged on since; and the playlist is the fixed set the
        show opened with — nothing re-reads the folder — so a swap confined to the
        current slide would leave every later pass replaying the version this
        one replaced. What is on screen changes only when the upgraded item is
        what's on it: it carries on the move the picture was on, as the frames
        of its making did.
        """
        self._set.note_enhancement_landed(prompt_id)
        upgraded = self._set.upgrade(prompt_id, path, media_type, still)
        if self._playlist.replace_item(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._levels.restart()
                self._frames_on_screen = False
                self._swap_in(path, media_type)
                self._move_on_early_from(self._playlist.current())
            self._hand_over(land=False)
        elif upgraded is not None and self._set.passes(upgraded) and self._playlist.add(upgraded):
            # Kept out of an enhanced-only pass until now, being unenhanced; the
            # better version is exactly what that pass plays, so in it goes.
            self._hand_over(land=False)
        self.refresh_panel()

    def _swap_in(self, path, media_type: str) -> None:
        """A better file of the item on screen, in the place of the one up,
        on the move that one was making."""
        item = playlist_item(path, media_type)
        self._put_a_frame_up(item.path)
        self._showing = item.path
        self._showing_media = (path, media_type)

    def note_enhancing(self, statuses: dict, frames=None) -> None:
        self._set.note_enhancing(statuses, frames)
        current = self._playlist.current()
        if current is None or self._live or self._levels.stepping:
            return
        self._show_what_is_being_made()
        self.refresh_panel()

    def _show_what_is_being_made(self) -> None:
        """The frames of the enhancement being made of the slide on screen, in
        its place while they come in -- and the picture itself back when they
        stop, on the move it was making."""
        current = self._playlist.current()
        playback = self._pane.playback
        if current is None or playback is None or current.is_live:
            return
        frame = (self._set.frame_being_made_of(current)
                 if self._file_of(current) == self._showing else None)
        if frame is not None:
            self._frames_on_screen = True
            self._put_a_frame_up(self._frames.write(current.prompt_id, frame))
        elif self._frames_on_screen:
            self._frames_on_screen = False
            self._frame_on_player = None
            self._frames.forget(current.prompt_id)
            playback.clear_frame()
            self._move_on_early_from(current)

    def lead_with_what_is_being_made(self) -> None:
        if self._set.lead_with_what_is_being_made():
            self._show_current()

    def _current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a playlist assembled
        without ids (a test's) names nothing.

        Read off the playlist item rather than off the file showing, so it is
        still the right answer while Shift+Left/Right has stepped onto one of
        that item's other versions.
        """
        return self._set.current_prompt_id()

    def _current_base(self) -> str:
        """The file the set lists the item on screen under — what its versions
        are keyed by. Empty for one still being made: its slide is frames rather
        than a file, and nothing is keyed off those."""
        item = self._playlist.current()
        if item is None or item.is_live:
            return ""
        return str(item.path)

    def voice_target(self):
        """The generation a spoken order or request is about: the slide on
        screen — what the speaker is looking at while saying it."""
        return self._current_prompt_id()

    def note_voice_run(self, prompt_id, message: str, *, kind: str = NOTICE) -> None:
        if prompt_id is not None:
            self._set.note_enhancement_asked(prompt_id)
            self.refresh_panel()
        self.note_voice_command(message, kind=kind)

    def note_voice_command(self, message: str, *, kind: str = NOTICE) -> None:
        """Say what a spoken command did. Here rather than in the gallery's own
        caption because the speaker is looking at this — the window under it is
        covered by the very show being talked to."""
        self._flash_note(message, ms=2500, kind=kind)

    def _refresh_note(self):
        if self._request_note:
            self._show_note(self._request_note)
        elif self._working_note:
            self._show_note(self._working_note)
        else:
            self._note.hide()

    @property
    def hud_item_note(self) -> str:
        return item_note(self._set, levels=self._levels.levels(base=self._current_base()),
                         level_index=self._levels.index)

    def _show_note(self, text: str, *, kind: str = NOTICE) -> None:
        self._note.say(text, kind=kind)

    def _flash_note(self, text: str, ms: int = 1500, *, kind: str = NOTICE):
        """Say something for a moment, then fall back to whatever the note would
        otherwise be saying."""
        self._show_note(text, kind=kind)
        self._note_timer.start(ms)

    def _flip_lock(self) -> bool:
        """Flip the lock; returns whether the slide is now locked.

        Locking also stars what is on screen: locking a slide is how the user says
        this one is worth keeping, and having said it they should not have to say
        it twice in two ways.
        """
        if self._playlist.toggle_lock():
            self._moves_on_early = False
            self.favorite()
            self._settle()
            self.refresh_panel()
            if self._actions.lock is not None:
                prompt_id = self._current_prompt_id()
                if prompt_id is not None:
                    self._actions.lock(prompt_id)
            return True
        self._open_again()  # released, so the dwell starts counting again
        return False

    def _open_current(self):
        """Enter: leave the slideshow and hand its item to the gallery, which
        opens the folder it lives in — the way out of a shelf's slideshow, where
        what you're watching came from folders all over the tree."""
        self._land_on = self._current_prompt_id()
        self.close()  # the handover is closeEvent's, so it happens exactly once

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the video on screen, or ``None`` for
        an image or a video with no funscript — mirrors the config panel's target so
        the gallery can point its one driver at whichever surface is foreground."""
        return drive_target_for(self._current_video_path(), self._pane)

    def _move_the_panel(self, key) -> None:
        direction = _PANEL_MOVES.get(key)
        if direction is not None and self._actions.move_hud is not None:
            self._actions.move_hud(direction)

    # --- Qt events ---------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._move_the_panel(key)
        elif key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step_level(-1) if shifted else self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step_level(1) if shifted else self._step(1)
        elif key == Qt.Key.Key_Up:
            self._delete_current()  # cull this one and move on
        elif key == Qt.Key.Key_Down:
            self._lock_current()    # lock it, favorite it, and enhance it
        elif key in (Qt.Key.Key_E, Qt.Key.Key_Home):
            # The loop key, on both of the keys a session gives its two
            # satellites: seeds, then actions, then off.
            self.show_loop_cycle()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_current()    # out of the slideshow, into its folder
        elif apply_motion_key(self._motion, key,
                              on_drive_toggle=self._actions.drive_toggle):
            # Space belongs to the motion cluster now, everywhere — locking the
            # slideshow is Down, matching the auto-generate view's lock.  The
            # panel redraws on its own beat, and this is the one moment the
            # answer can have changed under a driver that emits no signal.
            self.refresh_panel()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._note.reposition()

    def closeEvent(self, event):
        """Leave, handing the gallery the slide that was on screen.

        However the show is left — Escape, a double-click, Enter, the spoken
        "close", or ending on a locked slide — the picture you were looking at is
        the one you want to find afterwards, so the gallery picks it where the
        show was playing. Only a show with nothing on screen hands nothing over,
        which is a show whose last item was culled.
        """
        self.hide()
        self._pane.close_engine()  # lets go of every held file, so it can be deleted
        self._showing = None
        self._showing_media = None
        self._frames.forget_all()
        landing = self._land_on or self._current_prompt_id()
        # Both cleared before a second close could read them, so the handover
        # happens once. The lock outlives the first emit because the gallery
        # reads this show's state there, and a slide closed under a lock is one
        # a reopened show locks.
        self._land_on = None
        self.closed.emit()
        self._playlist.unlock()
        if landing is not None:
            self.open_requested.emit(landing)
        super().closeEvent(event)


class SlideshowOnAFunestra:
    """The Slideshow as the Funestra sees it: what runs on the window.

    The Funestra asks it about every press on the panel it wears and every
    verb, gives it a pass of its own each frame, and heads the panel with what
    it says it is playing.  The window is the show's own, so closing the
    Funestra closes nothing here: the show closes the Funestra, not the other
    way round.
    """

    def __init__(self, show: SlideshowView) -> None:
        self._show = show

    def apply_command(self, command: str) -> bool:
        return self._show.press(command)

    def tick(self) -> None:
        self._show.follow_the_funestra()

    def status_fields(self) -> dict[str, str]:
        return {}

    def top_block(self) -> ModeHud:
        return ModeHud(video=self._show.item_label())

    def set_showing(self, showing: bool) -> None:
        pass

    def picture(self) -> None:
        return None

    def close(self) -> None:
        pass
