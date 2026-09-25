"""The fullscreen player — the one way this app fills the screen with a picture.

It plays a set of generations: a folder's, a shelf's, or the one folder a
double-clicked picture came from. **A double-click opens this same view at a
pace of nought**, holding the clicked picture until an arrow moves it, which is
why there is no second fullscreen viewer with its own keys and its own copy of
the counter, the neighbor stills and the culling; turning the console's
clip-seconds pace up off nought sets such a show going.

The set is not frozen at the opening: a run joins it on its first frame rather
than when it lands, because the first iterations are what a show of a filling
folder is watched for — and not before, a black screen reading "Generating…"
being nothing to watch.

The creep into a picture while it holds the screen is the *engine's*, not this
window's, so a show handed to one of a session's players creeps the same way,
and turning the pace up slows the creep instead of cropping harder.

One panel, not two. Fun Time splits the device across the main player's console
and the set across each satellite's HUD, because there they are two players; a
show is one host doing both, and wearing both panels says the status twice in
two lines that can disagree, with prev/next/lock/trash drawn on each.

Being the deliberate foreground view, it plays sound — the inline preview pane
stays muted.

What every key does, what the lock takes with it, what a filter narrows and
where a closing show leaves you are `tests/test_slideshow_view.py`'s to state:
each is a test named for the claim.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator import osr2 as osr2_device
from origenerator.gui.console import post_console_action, show_device
from origenerator.gui.holdable_timer import HoldableTimer
from origenerator.gui.level_stepper import LevelStepper
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.neighbor_previews import NeighborPreviews, still_for
from origenerator.gui.notice_overlay import NOTICE, WARNING, NoticeOverlay
from origenerator.gui.position_caption import PositionCaption
from origenerator.gui.show_map import SEED_AXIS
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
from origenerator.gui.show_surface import ShowSurface
from origenerator.gui.show_wiring import ShowActions
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_queue import SlideshowQueue
from origenerator.media import MediaType
from origenerator.osr2_driver import drive_target_for
from origenerator.slideshow import LIVE, ShowState, Slide, in_order

logger = logging.getLogger(__name__)

# What the map's chrome says when it does what it says, in the players' own
# words, and the three ways it can have nothing to do.
_MORE_SEEDS = "More seeds"
_WIDENING_FAILED = "Widening net failed"
_NOTHING_TO_LOOP = "Nothing to loop"
_NOTHING_THAT_WAY = "Nothing that way"


class SlideshowView(QWidget):
    # Enter on an item: leave the slideshow for that generation's own folder.
    open_requested = pyqtSignal(str)
    # The show was dismissed (Escape, Enter out, or culled empty) — the gallery
    # keeps voice-command listening tied to a fullscreen surface being up.
    closed = pyqtSignal()
    # A different item (or version) is on screen — re-aim the OSR2 drive.
    media_changed = pyqtSignal()

    def __init__(self, items, *, frame=None, start=None, image_dwell_ms=None,
                 shuffle=None, actions=None, hud=None, engine=None, motion=None,
                 pace=None, parent=None):
        super().__init__(parent)
        # What a press here asks the gallery to do on its behalf — the half of
        # each gesture that lands on the generation rather than on the slide.
        # None of it, for a show standing on its own (see ShowActions).
        self._actions = actions if actions is not None else ShowActions()
        self._motion = motion  # the gallery's app-global motion driver, or None
        # How long a slide holds the screen is app-wide, because the console
        # that sets it is: turned up here or in the main window, it is the
        # same number. An explicit dwell (a double-clicked picture's nought,
        # or a test's) wins until the console next moves the pace.
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        self._pace.changed.connect(self._on_pace_changed)
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
        self._pane = ShowSurface(engine=engine, muted=False,
                                    on_double_click=self.close,
                                    on_press=self._toggle_pause)
        self._pane.media_ended.connect(self._on_media_ended)
        self._pane.media_unplayable.connect(self._on_media_unplayable)
        # The media is refitted a beat after the window resizes (and again when a
        # video's resolution arrives), so re-place the neighbors when it lands.
        self._pane.media_resized.connect(self._reposition_neighbors)
        layout.addWidget(self._pane, 1)

        # The items either side of this one, floated over the black surround.
        self._neighbors = NeighborPreviews(self)

        # Where in the set this one is, floated over the foot of the media.
        self._counter = PositionCaption(self)
        # The lower strip's queue itself — the live frame, the bar, the rows and
        # their buttons — floated into the corner this view leaves empty. The
        # strip that normally carries it is under this window, and a show is
        # both when the queue stops moving (its videos are held) and when the
        # user keeps adding to it (a locked slide asks for an enhancement).
        self._queue = SlideshowQueue(self)
        # For a beat, whatever a switch or a spoken fix just did. It is a Fun
        # Time notice, at the top center where Fun Time flashes the same kind of
        # line over a player, because this surface wears the players' own HUD.
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
        self._live_clock = HoldableTimer(self)
        self._live_clock.timeout.connect(self._on_media_ended)
        self._frames_on_screen = False
        self._hud = None

        # A pause — the hosting session's OmniPause, or a click on a show with no
        # session — held here so it survives navigation: a step lands on a NEW
        # slide (the freeze does not un-aim the transport), but the slide must
        # arrive frozen — no dwell armed, its video paused — rather than playing
        # out from under the freeze.
        self._paused = False
        # The players' HUD replaces this view's own furnishings (the neighbor
        # stills, the position plate) with its map — see adopt_hud.
        self._hud_dressed = False

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
        # Every run this show has already taken in as a slide of its own frames.
        # A run is offered once: one culled off the show would otherwise be put
        # straight back by its next frame, which is the opposite of what Up says.
        self._seen_live: set[str] = set()
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
                            acts=self._actions.acts)

    @property
    def _playlist(self):
        """The pass this show is playing — the set's, since the set deals it."""
        return self._set.playlist

    def _pass_changed(self, kept: bool) -> None:
        """A fresh pass was dealt over the set: show whatever is on it now.

        *kept* says the slide that was on screen survived into it — a switch
        narrowing what you are looking through — so the picture stays and only
        what says where in the set it is has moved.  Without it the pass has
        stood somewhere else up, and the view follows.
        """
        if kept:
            self._update_counter()
            self._update_neighbors()
        else:
            self._show_current()

    # --- playback ----------------------------------------------------------

    def _show_current(self):
        """Put the current item on the engine, which holds a picture for the
        pace and ends it the way it ends a finished clip."""
        if self._live:
            # Nothing on disk yet: the run's own frames stand in for a slide.
            if self._frame is not None:
                self._pane.show_frame(self._frame)
            else:
                self._pane.show_message(GENERATING)  # opened before the first one
            self._update_counter()
            self._update_neighbors()
            return
        slide = self._playlist.current()
        if slide is None:
            return
        self._levels.restart()  # a new item, so its own versions from the top
        frame = self._set.frame_being_made_of(slide)
        self._frames_on_screen = frame is not None
        if self._frames_on_screen:
            self._pane.show_frame(frame)
            self._start_the_live_clock()
        else:
            self._live_clock.cancel()
            self._open_on_engine(slide.path, slide.media_type)
        self._update_counter()
        self._update_neighbors()
        self._refresh_note()  # the note belongs to whatever is on screen now
        self._apply_freeze()  # a slide arrived at under a freeze arrives frozen
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    # --- the slide's own clock, which is the engine's -----------------------

    def _open_on_engine(self, path, media_type) -> None:
        # The pace before the file: the engine reads it as it opens one.
        self._pane.set_pace(self._pace_on_screen())
        self._pane.show_media(path, media_type)

    def _pace_on_screen(self) -> float:
        return self._set.pace_for(self._playlist.current(), self._dwell_s)

    def _start_the_live_clock(self) -> None:
        if self._dwell_s:
            self._live_clock.run_for(int(self._pace_on_screen() * 1000))
        else:
            self._live_clock.cancel()

    def _apply_freeze(self) -> None:
        """Hand the engine whatever is holding the show still.

        The room's freeze stops everything.  A spoken request stops the show
        moving on rather than stopping the clip: it is about what is on screen,
        and a clip that stopped mid-sentence would be answering a question
        nobody asked.  A picture under one holds where the creep had got to,
        since the alternative is its dwell running out and starting over under
        the speaker.
        """
        request_stills_a_picture = (self._playlist.paused
                                    and not self._pane.is_showing_video())
        held = self._paused or request_stills_a_picture
        self._pane.set_paused(held)
        self._live_clock.hold(held)

    def set_playlist(self, items, index: int) -> None:
        """Re-seed the set this show plays, on ``index``.

        What a double-clicked picture's show is armed with once the gallery has
        worked out the folder under it: the view comes up on the one item the
        pane had, and this hands it the rest in the browser's own order. A view
        still following a generation keeps its frames — it has no place among
        those files until an arrow leaves them for one.
        """
        self._set.reseed(items, start=index, shuffle=in_order)
        if self._live:
            self._update_counter()
            self._update_neighbors()
        else:
            self._show_current()

    def playing_now(self):
        return None if self._live else self._playlist.playing_now()

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm Shift+Left/Right to step an item's versions.

        ``levels_by_path`` maps the file the set shows an item under to that
        item's versions, newest first, as ``(path, media_type, label)``. Plain
        Left/Right still steps the set; the shifted pair moves within the one
        item — its own axis, because a version is not a neighbor.
        """
        self._levels.arm(levels_by_path)

    def add_levels(self, levels_by_path: dict) -> None:
        self._levels.add(levels_by_path)

    def queue(self) -> SlideshowQueue:
        """The floated queue, for the gallery to wire its reorder and clear to —
        it is the same widget as the lower strip and asks the same things."""
        return self._queue

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        """Show what is in flight in the corner — the same list, in the same
        order, the lower strip this view is covering would be showing."""
        self._queue.set_items(items, foreign_queued)
        self._reposition_queue()

    def _reposition_queue(self) -> None:
        """Place the queue, keeping it clear of the position counter — the two
        share the foot of the screen, and the counter's width moves with what it
        says."""
        counter = None if self._counter.isHidden() else self._counter.geometry()
        self._queue.reposition(avoid=counter)

    # --- picking a closed show back up --------------------------------------

    def state(self) -> ShowState:
        """Where this show is, in the terms a later one can be opened at."""
        return ShowState(
            order=tuple(self._playlist.order_ids()),
            current=self._current_prompt_id(),
            locked=self._playlist.locked,
            level_index=self._levels.index,
        )

    def resume(self, state: ShowState) -> bool:
        """Open where a closed show left off rather than at the top of a fresh
        shuffle. Returns whether the place carried.

        Closing a show is usually a detour — the folder under the picture, a fix
        in a tab — so coming back is coming back to that picture: the slide it
        ended on, still locked if it was locked, still showing the version it had been
        stepped to. The place carries only while that slide is among these items,
        since a show of another folder has nowhere to put it.

        Called after :meth:`set_levels`, because which version a slide was showing
        is only a version once the levels under it are armed.
        """
        if self._live or not self._playlist.resume(state.order, state.current):
            return False
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
        """A generation that belongs to what this show is playing has landed: it
        joins the set, queued to come up next.  ``favorited`` and ``enhanced`` are
        what the gallery knows of its row, so the two switches can judge it.

        A folder that is auto-generating is the case this is for. Without it the
        show plays the fixed set it opened with, so the very items being made
        while it runs — the ones being watched for — are the ones it never gets
        to. The slide on screen is left alone; only the counter and the stills
        either side move, since the set they describe just grew.

        One the show has been watching being made is already in the set as its
        own frames, and finishing is not a second slide: it keeps its place in
        the pass and simply becomes the file.
        """
        if favorite:
            self._set.favorite_ids.add(prompt_id)
        if enhanced:
            self._set.enhanced_ids.add(prompt_id)
        slide = Slide(path, media_type, prompt_id, still)
        self._set.remember(slide)
        if self._playlist.replace_live(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._show_current()  # the file itself now, and on a clock again
            self._update_neighbors()  # it may be the still riding either side
            return
        # Into the pass only past the switches: a show narrowed to its favorites
        # must not fill back up with every unfavorited thing the loop makes.  The
        # whole set remembers it either way, for when the switch comes off.
        if self._set.passes(slide) and self._playlist.add(slide):
            self._update_counter()
            self._update_neighbors()

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
                self._pane.show_frame(frame)
            else:
                self._update_neighbors()  # it may be the still riding either side
            return
        if prompt_id in self._seen_live:
            return
        self._seen_live.add(prompt_id)
        live = Slide(frame, LIVE, prompt_id)
        self._set.remember(live)
        # A run still being made is neither a favorite nor enhanced, so a
        # narrowed show leaves its frames out of the pass and takes them in
        # when the switch comes off, the way it takes in anything else it has.
        if self._set.passes(live) and self._playlist.add(live):
            self._update_counter()
            self._update_neighbors()

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
            if self._playlist.is_empty():
                self.close()  # a show of nothing but that run has nothing left
                return
            if showing:
                self._show_current()
            else:
                self._update_counter()
                self._update_neighbors()

    def holds(self, prompt_id: str) -> bool:
        """Whether this show already has a slide for that generation — what the
        gallery asks before working out whether a run belongs in here at all."""
        return self._playlist.holds(prompt_id)

    def _advance(self):
        self._playlist.advance()
        self._show_current()

    def release_media(self, paths):
        """Let go of any of ``paths`` on screen — a file about to be deleted (its
        own Up key condemns the item it's playing)."""
        self._pane.release_media(paths)

    def _delete_current(self):
        """Up, the players' "weird": a favorite loses its star and the show
        moves on; anything else is deleted (if a deleter is wired) and the show
        moves on.

        Two things on one key, as on a satellite, and the star on screen says
        which: locking a slide starred it, so the first press takes that back
        and only the second condemns it.  A slide that is still being made has
        nothing to condemn: the run is on the GPU and its row is a record of
        that, not a picture that has been judged.  Up takes such a slide off
        the show and leaves the run alone — calling one off is the queue
        plate's Cancel, in the corner of this very screen.
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
        self._update_counter()
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
        self._open_on_engine(*level[:2])
        self.media_changed.emit()

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
            self._pane.show_frame(data)

    def show_landed(self, media: tuple, generation: str | None) -> None:
        """The followed generation finished: its saved file takes the place of
        its frames, at the head of the folder the show was armed with."""
        if not self._live:
            return
        self._live = False
        folder = [slide for slide in self._set.all_items if slide.prompt_id != generation]
        self._set.reseed([Slide(*media, generation), *folder], shuffle=in_order)
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
        if self._set.drop_the_switches():
            return  # the fresh pass is on screen already (see _pass_changed)
        self._playlist.restart()
        self._show_current()

    def retune(self, items, *, enhanced_ids=None) -> None:
        """Point this show at the region's base set instead.

        What a hosted reset does.  The window stays up rather than being closed
        and reopened: it covers a satellite player, and a region that blinks
        black between two shows is the thing the base state exists to avoid.
        Both switches and the lock come off the way any reset takes them off,
        and the pass is a fresh shuffle.

        A base state is one KIND of set and always the same one, so it is
        re-dressed rather than re-described: shuffled, and NOT a loop anyone
        asked for — that side browsing its whole library, which is what a
        satellite does with no loop on.  It kept the favorited ids it had, and
        still does; nothing about a reset changes which items are favorites.
        ``enhanced_ids`` is which of the new items carry an enhancement — a
        new set, so a new answer.
        """
        self._live = not items
        self._set.retune(items, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=()) -> None:
        self._live = not items
        self._set.reorder(items, latest=latest, enhanced_ids=enhanced_ids)

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
            if self._set.end_loop():
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

    def show_loop_cycle(self) -> None:
        """The loop key, as on a player: seeds, then actions, then off — and
        the lock when there is nothing on either axis to loop, which is Down's
        whole gesture here."""
        stepped = self._set.step_loop()
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
        return self._set.act_filter

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

    def audio_muted(self) -> bool:
        return self._pane.audio_muted()

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

    def current_media_path(self) -> str:
        """The file on screen — what a hosting Fun Time session's status says."""
        return self._pane.current_media_path()

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
        return self._set.favorites_filter

    @property
    def hud_enhanced_mode(self) -> bool:
        """Whether the show is narrowed to the pictures that have been enhanced
        — the switch beside F-mode on its HUD."""
        return self._set.enhanced_mode

    def toggle_favorites_filter(self) -> bool:
        """Narrow the set to the favorites, or widen it back — the players' own
        F-mode, over the favorited items.  ``True`` when the switch moved."""
        return self.set_favorites_filter(not self._set.favorites_filter)

    def toggle_enhanced_mode(self) -> bool:
        """Narrow the set to the pictures that have been enhanced, or widen it
        back — the HUD's switch beside F-mode.  ``True`` when the switch moved."""
        return self.set_enhanced_mode(not self._set.enhanced_mode)

    def set_favorites_filter(self, on: bool) -> bool:
        return self._set.set_modes(favorites_filter=bool(on), enhanced=self._set.enhanced_mode)

    def set_enhanced_mode(self, on: bool) -> bool:
        """Said which way rather than flipped — a speaker mid-show is not
        looking at the HUD to see which way it stands."""
        return self._set.set_modes(favorites_filter=self._set.favorites_filter, enhanced=bool(on))

    def clear_modes(self) -> bool:
        """Every switch off at once — what "clear filter" has to mean once
        there is more than one to clear."""
        return self._set.set_modes(favorites_filter=False, enhanced=False, act_filter="")

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
        """Freeze or resume the show whole — the hosting session's OmniPause, or
        a click on a show standing on its own.

        Distinct from the lock: a lock holds one slide by choice and replays
        its clip; this stops time itself.  The engine's clock is the show's, so
        a frozen picture stops counting down its dwell and a frozen clip stops
        playing, and a slide stepped to while frozen arrives frozen too.
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
        self._pane.set_pace(self._pace_on_screen())
        if not self._playlist.locked:
            # The engine reads the pace when it opens the file, so the picture
            # on screen takes the new pace by being opened again.
            self._show_current()

    def _on_media_ended(self):
        """The item ran out — a clip that finished, or a picture whose dwell
        expired.  Replay it while locked, else move on. A lock is
        repeat-one here, as it is on a Fun Time satellite — and a pace of nought
        holds the clip the same way, since nought means nothing moves on its own.
        A request being spoken stops it too: paging on mid-sentence is exactly
        what that pause exists to stop.
        """
        if self._playlist.locked_or_paused() or not self._dwell_s:
            self._show_current()
        else:
            self._advance()

    def _on_media_unplayable(self):
        """A file the engine will not open: step past it, whatever holds it.

        Unlike a clip that ended, this one never will, so the replay a lock or
        a pace of nought asks for would hold a black screen for the rest of the
        session.  The item stays in the set — the fault is the backend's, not
        the file's — but the show moves on.

        A pause is the one stop this yields to: the show is frozen, and a show
        that walked its set looking for something playable would be moving.
        The black rectangle waits for the resume.
        """
        if self._paused:
            return
        logger.warning("Slideshow: a clip would not play; stepping past it")
        self._advance()

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

        *working* means it hasn't done it yet: the corner holds that line
        instead of flashing it, because working out what a request changes can
        mean asking the local LLM which of the prompt's own terms the speaker
        meant — the case that outlasts a flash — and a corner that empties while
        the app is still working says the request was dropped when it wasn't.

        Which is why that line comes down only for the request that put it up.
        Nothing stops a second request being said over the first, and an answer
        to the first would otherwise blank the corner while the second is still
        out at the model — the same defect, one request later. An answer to
        anything else flashes over the held line and leaves it standing,
        because it is still true.
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
        this image has already been enhanced, whether its Enhance-on-lock
        switch is on at all, and an enhanced one wants nothing.  ``True`` back
        means a run started, and the HUD says so until the finished version
        arrives.
        """
        if self._actions.enhance is None:
            return
        if self._playlist.current_is_live():
            return  # no file yet to make a better version of; the lock still holds
        prompt_id = self._current_prompt_id()
        if prompt_id is None or self._set.enhancement_of(prompt_id):
            return
        if self._actions.enhance(prompt_id):
            self._set.note_enhancement_asked(prompt_id)

    def note_enhanced(self, prompt_id: str, path, media_type: str = MediaType.IMAGE,
                      still=None) -> None:
        """An enhancement of one of these items landed: the show points at it
        from here on, wherever that item sits in the running order.

        Not only while it is the one on screen. It was asked for minutes ago and
        the show may have paged on since; and the playlist is the fixed set the
        show opened with — nothing re-reads the folder — so a swap confined to the
        current slide would leave every later pass replaying the version this
        one replaced. What is on screen changes only when the upgraded item is
        what's on it.
        """
        self._set.note_enhancement_landed(prompt_id)
        upgraded = self._set.upgrade(prompt_id, path, media_type, still)
        if self._playlist.replace_item(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._show_current()
            self._update_neighbors()  # it may be the still riding either side
        elif upgraded is not None and self._set.passes(upgraded) and self._playlist.add(upgraded):
            # Kept out of an enhanced-only pass until now, being unenhanced; the
            # better version is exactly what that pass plays, so in it goes.
            self._update_counter()
            self._update_neighbors()

    def note_enhancing(self, statuses: dict, frames=None) -> None:
        self._set.note_enhancing(statuses, frames)
        current = self._playlist.current()
        if current is None or self._live or self._levels.stepping:
            return
        frame = self._set.frame_being_made_of(current)
        if frame is not None and self._frames_on_screen:
            self._pane.show_frame(frame)
        elif (frame is not None) != self._frames_on_screen:
            self._show_current()

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

    def _reposition_note(self):
        self._note.reposition()

    def _flip_lock(self) -> bool:
        """Flip the lock; returns whether the slide is now locked.

        Locking also stars what is on screen: locking a slide is how the user says
        this one is worth keeping, and having said it they should not have to say
        it twice in two ways.
        """
        if self._playlist.toggle_lock():
            self.favorite()
            self._update_counter()
            if self._actions.lock is not None:
                prompt_id = self._current_prompt_id()
                if prompt_id is not None:
                    self._actions.lock(prompt_id)
            return True
        self._show_current()  # released, so the dwell starts counting again
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
        return drive_target_for(self._pane.current_video_path(), self._pane)

    # --- the neighboring items ---------------------------------------------

    def adopt_hud(self, hud=None):
        """The players' HUD went on this show: its map now says where in the
        set this is and what is around it, so the view's own furnishings — the
        neighbor stills, the position plate — come off.

        Every show wears it, hosted on a satellite region or fullscreen on its
        own: the map is the same map either way, and a show that kept its own
        stills and plate beside it would be saying everything twice.

        *hud* is the panel itself, when the caller has it: the device rows and
        the readout ride on it, so a motion key has to reach it to redraw.
        """
        self._hud_dressed = True
        self._neighbors.set_neighbors(None, None)
        self._counter.hide()
        if hud is not None:
            self._hud = hud

    def _update_neighbors(self):
        """Draw the items either side of this one — nothing on a set too short
        for a neighbor to be anything but the item already on screen, nothing
        at all while this is following a generation, which has no place among
        them yet, and nothing at all once the players' HUD is drawing the map
        these stills are the small version of."""
        if self._hud_dressed or self._live or len(self._playlist) < 2:
            self._neighbors.set_neighbors(None, None)
            return
        self._neighbors.set_neighbors(
            still_for(self._playlist.peek(-1)), still_for(self._playlist.peek(1)),
            media_rect=self._media_rect(),
        )

    def _reposition_neighbors(self):
        self._neighbors.reposition(self._media_rect())

    def _media_rect(self):
        """Where the media is drawn, in this view's coordinates."""
        rect = self._pane.media_rect()
        rect.moveTopLeft(self._pane.mapTo(self, rect.topLeft()))
        return rect

    # --- caption -----------------------------------------------------------

    def _update_counter(self):
        """Say where in the set this is — nothing at all while following a
        generation still being made, which is nowhere in it yet, and nothing
        once the players' HUD is saying it instead."""
        if self._hud_dressed:
            return  # the HUD's map says the position now
        if self._live or self._playlist.is_empty():
            self._counter.hide()
            return
        self._counter.show()
        # Show the item's number within the set (its shuffled position), not the
        # step count — so a random slideshow visibly jumps around, e.g. 7, 23, 16.
        self._counter.show_position(
            self._playlist.order[self._playlist.index] + 1, len(self._playlist),
            "  ·  locked" if self._playlist.locked else "",
        )

    # --- Qt events ---------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
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
            if self._hud is not None:
                self._hud._tick()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._counter.reposition()
        self._reposition_queue()
        self._reposition_neighbors()
        self._reposition_note()

    def closeEvent(self, event):
        """Leave, handing the gallery the item the show ended on if there is one.

        Enter names that item; so does a lock, which is the user saying this is
        the one — so a show ended on a locked slide lands on that slide, rather
        than leaving the gallery wherever it was before the show. Ended on a
        slide nobody locked (Escape, a double-click, the spoken "close", the last
        item culled), it hands nothing over and leaves the gallery alone.
        """
        self._pane.clear()  # release any held file so it can be deleted
        self._pane.close_engine()
        self._live_clock.cancel()
        landing = self._land_on
        if landing is None and self._playlist.locked:
            landing = self._current_prompt_id()
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
