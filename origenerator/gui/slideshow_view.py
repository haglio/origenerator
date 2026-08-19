"""The fullscreen player — the one way this app fills the screen with a picture.

It plays a set of generations: a folder's, a shelf's (Recents, Starred), or the
one folder a double-clicked picture came from. Reuses :class:`PreviewWidget` (in
play-once mode) for the actual image/video rendering and a
:class:`~origenerator.slideshow.SlideshowPlaylist` for the order and pacing.
Images advance on a dwell timer; videos play once and advance when they end
(``PreviewWidget.video_ended``). The arrows step, Shift+arrows step the
enhancement levels of the picture on screen, Up culls, Down locks the slide
against the advance (a locked clip replays, and the hold both stars the slide and
asks for an enhancement — see :meth:`SlideshowView._hold_current`), Enter leaves
for the shown item's own folder (``open_requested``), and Escape closes. Ending
a show on a locked slide leaves for that slide's folder too: holding one is the
user saying this is the one, so the gallery lands there rather than back where
it was when the show started.

Closing one doesn't lose your place in it. :meth:`SlideshowView.state` is where
a show was — the pass, the slide, the hold on it — and :meth:`SlideshowView.resume`
opens the next one there, so the look at the folder behind a picture that closing
the show is usually for doesn't cost the picture.

**Double-clicking a picture opens this same view at a pace of nought** — its
folder in the browser's own order, starting on the picture that was clicked,
holding it until an arrow moves it. There used to be a second full-screen
viewer for that, with its own keys to learn and its own copy of the counter, the
neighbor stills, the level stepping and the culling; a show that simply never
moves on is the same thing with nothing to keep in sync. Turning the console's
clip-seconds pace up off nought is what sets such a show going.

Anything that moves off a locked slide — a step either way, a cull — releases the
lock, the way Fun Time's next/prev cancel a satellite's: the lock holds the slide
it was set on, not wherever the user wanders to.

A second hold is the show's own: :meth:`SlideshowView.hold_for_request` stops the
advance while a spoken request is being said, since the request is about what is
on screen and a show that pages on mid-sentence would aim it at the wrong slide.
It is independent of the lock, so releasing it never unlocks a held slide.

The set is not frozen at the opening. It holds only generations there is
something to look at, and the gallery hands each one over the moment there is
— which is well before it lands. A run with no frame yet is no slide: a black
screen reading "Generating…" is nothing to watch. But the first iterations
coming in are the most exciting thing in a folder that is filling, and they are
what a show of one is being watched for, so the run joins the set on its first
frame (:meth:`SlideshowView.note_generating`), keeps the newest one from there,
and swaps its frames for the file when it lands
(:meth:`SlideshowView.note_added`). A show of a folder that is auto-generating
therefore watches the loop work rather than only its results.

It also opens over a generation that's still running: built with no items, it
shows that generation's streamed low-res frames (:meth:`show_frame`) until the
pane that opened it hands over the finished file (:meth:`show_landed`), at which
point it is an ordinary show of that file. So a generation can be watched
full-screen while it's made, not only once it lands.

An image does not simply sit there while it holds the screen: the view creeps
into it, ending a tenth of the way in by the time the dwell runs out — the Ken
Burns move, paced by the dwell rather than by a clock of its own, so turning the
pace up slows the creep instead of cropping harder
(see :mod:`origenerator.ken_burns`, and :meth:`SlideshowView._arm_dwell` for the
one clock the advance and the move share).

Every show wears the players' own HUD (:meth:`SlideshowView.adopt_hud`,
:mod:`origenerator.gui.show_hud`) — hosted on a satellite region and fullscreen
alike — so its map replaces the view's own position plate and the small stills
riding either side of the picture (:mod:`origenerator.gui.neighbor_previews`).
What it has left to say for itself, it says in a Fun Time toast across the top
(:mod:`origenerator.gui.toast`).

The bottom strip's queue is floated into the bottom-left corner
(:mod:`origenerator.gui.slideshow_queue`) — live frame, progress bar, rows and
their buttons — since the strip that carries it is behind this window, and a show
is exactly when the line stops moving and when the user keeps adding to it. The
shared OSR2 stroke keys ride along too (Space and friends — see
:mod:`origenerator.gui.stroke_hud`) with genau's drive panel floated up top, so
the device can run over a show of stills; a clip that carries a funscript instead
offers itself as an :meth:`osr2_drive_target`. Being the deliberate foreground
view, it plays sound — the inline preview stays muted.
"""

import logging

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from origenerator.gui.neighbor_previews import NeighborPreviews, still_for
from origenerator.gui.osr2_driver import drive_target_for
from origenerator.gui.position_caption import PositionCaption
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_queue import SlideshowQueue
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.stroke_hud import apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel
from origenerator.gui.toast import Toast
from origenerator.ken_burns import TICK_MS, progress_step, zoom_at
from origenerator.slideshow import LIVE, ShowState, SlideshowPlaylist, in_order

logger = logging.getLogger(__name__)

_GENERATING = "Generating…"
# What the corner says about an enhancement of the slide on screen. Which of the
# two is a fact about the run, not about the ask: holding slide after slide
# sends out a line of runs, and ComfyUI is making exactly one of them.
_ENHANCING = "Enhancing…"
_ENHANCE_QUEUED = "Enhancement queued"


class SlideshowView(QWidget):
    # Enter on an item: leave the slideshow for that generation's own folder.
    open_requested = pyqtSignal(str)
    # The show was dismissed (Escape, Enter out, or culled empty) — the gallery
    # keeps voice-command listening tied to a fullscreen surface being up.
    closed = pyqtSignal()
    # A different item (or version) is on screen — re-aim the OSR2 drive.
    media_changed = pyqtSignal()

    def __init__(self, items, *, frame=None, start=None, image_dwell_ms=None,
                 shuffle=None, on_delete=None, on_enhance=None, on_star=None,
                 on_lock=None, player=None, stroke=None, pace=None,
                 on_drive_toggle=None, parent=None, order_label="Shuffle",
                 starred_ids=None, on_reset=None, looping=True):
        super().__init__(parent)
        self._on_delete = on_delete
        # Where reset means something bigger than this show: hosted, a region
        # has a base state to go back to, and only the gallery knows it (see
        # :meth:`stroke_reset`).  Standalone there is none, and reset is local.
        self._on_reset = on_reset
        # Told when a hold engages (with the held item's prompt_id): a hosting
        # session answers a lock by opening that item as a generate tab.
        self._on_lock = on_lock
        # What this show's own HUD says about it: how the set is
        # ordered (Recents plays Latest, everything else Shuffle — the players'
        # own vocabulary), and which items are favorites, so the star readout
        # and the F-mode narrowing mean here what they mean on a player.
        self.hud_order_label = order_label
        # Whether this show is a LOOP as a player means it: a set someone asked
        # for, played round and round.  A region's base state is not one -- it
        # is that side browsing its whole library, the same thing a satellite
        # does when no loop is on -- so its HUD must not light the loop button
        # or say "Looping seeds" over it.
        self.hud_looping = looping
        self._starred_ids = set(starred_ids or ())
        self._f_mode = False
        self._all_items = list(items)
        # Holding a slide is also how you ask for it: Down enhances what is on
        # screen if it has never been enhanced, so the one you stopped on is the
        # one that gets the better version — and one that already has a better
        # version is left alone. ``E`` turns that off for the session, for when
        # it is in the way.
        self._on_enhance = on_enhance
        self._enhance_on_hold = on_enhance is not None
        self._enhancing: set[str] = set()  # prompt_ids with a run in flight
        # How each enhancement in flight is actually going, as the gallery
        # reads it (``prompt_id`` -> "running"/"queued"). Pushed in by
        # :meth:`note_enhancing`: the show knows what it asked for, and only
        # the side holding the jobs knows which of them is on the GPU.
        self._enhance_status: dict[str, str] = {}
        self._on_star = on_star
        self._stroke = stroke  # the gallery's app-global stroke driver, or None
        # Space goes to the gallery's one OSR2 switch rather than straight to
        # the stroke: which source drives is that switch's call, not a key's.
        self._on_drive_toggle = on_drive_toggle
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
        # The enhancement levels of each item that has any, keyed by the file the
        # set lists it under, so Shift+Left/Right steps the versions of whatever
        # is on screen. The base path is remembered separately: once you have
        # stepped onto a level, the file showing is no longer the key.
        self._levels_by_path: dict[str, list[tuple]] = {}
        self._level_base: str | None = None
        self._level_index = 0
        # How long a slide holds the screen is app-wide, because the console
        # that sets it is: turned up here or in the main window, it is the
        # same number. An explicit dwell (a double-clicked picture's nought,
        # or a test's) wins until the console next moves the pace.
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        if image_dwell_ms is None:
            image_dwell_ms = self._pace.dwell_ms
        self._dwell_s = image_dwell_ms // 1000
        self._pace.changed.connect(self._on_pace_changed)
        playlist_kwargs = {"image_dwell_ms": image_dwell_ms, "start": start}
        if shuffle is not None:  # else the playlist uses its own random shuffle
            playlist_kwargs["shuffle"] = shuffle
        self._playlist = SlideshowPlaylist(items, **playlist_kwargs)
        self.setWindowTitle("Slideshow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)  # a solid black surround behind the media
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Already the fullscreen view, so a double-click leaves it rather than
        # spawning a nested one. It plays sound (mute_audio=False), unlike the
        # muted inline preview, and wears the funscript strip a scripted clip's
        # stroke motion shows in.
        self._preview = PreviewWidget(player=player, loop_videos=False,
                                      allow_fullscreen=False,
                                      show_funscript_strip=True, mute_audio=False,
                                      on_double_click=self.close)
        self._preview.video_ended.connect(self._on_video_ended)
        self._preview.video_unplayable.connect(self._on_video_unplayable)
        # The media is refitted a beat after the window resizes (and again when a
        # video's resolution arrives), so re-place the neighbors when it lands.
        self._preview.media_resized.connect(self._reposition_neighbors)
        layout.addWidget(self._preview, 1)

        # The items either side of this one, floated over the black surround.
        self._neighbors = NeighborPreviews(self)

        # Where in the set this one is, floated over the bottom of the media.
        self._counter = PositionCaption(self)
        # The bottom strip's queue itself — the live frame, the bar, the rows and
        # their buttons — floated into the corner this view leaves empty. The
        # strip that normally carries it is behind this window, and a show is
        # both when the queue stops moving (its videos are held) and when the
        # user keeps adding to it (a held slide asks for an enhancement).
        self._queue = SlideshowQueue(self)
        # A note about the item on screen: which of its versions this is, that an
        # enhancement of it is being made, and for a beat whatever a switch or a
        # spoken fix just did — the only way to tell, in a view with no panels,
        # that a press did anything. It is a Fun Time toast, at the top center
        # where Fun Time flashes the same kind of line over a player, because
        # this surface wears the players' own HUD and had no business saying
        # things in a second dialect at the other end of the screen.
        self._note = Toast(self)
        # What the corner reads while a spoken request holds the show; empty
        # whenever nothing is being dictated.
        self._request_note = ""
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)
        self._stroke_panel = StrokePanel(stroke, self, host=self) if stroke is not None else None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        # The slow push into the still on screen. It runs on exactly the same
        # clock as the advance — armed and disarmed together (see _arm_dwell) —
        # so everything that stops a slide moving on stops the camera moving in.
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setInterval(TICK_MS)
        self._zoom_timer.timeout.connect(self._zoom_tick)
        self._zoom_progress = 0.0
        # The hosting session's OmniPause, held here so it survives navigation:
        # a step lands on a NEW slide (the room being frozen does not un-aim the
        # transport), but the slide must arrive holding — no dwell armed, its
        # video paused — rather than playing out from under the freeze.
        self._session_paused = False
        # The players' HUD replaces this view's own furnishings (the neighbor
        # stills, the position plate) with its map — see adopt_hud.
        self._hud_dressed = False

        self._show_current()

    # --- playback ----------------------------------------------------------

    def _show_current(self):
        """Render the current item and arm the dwell timer if it's an image."""
        self._disarm_dwell()
        self._restart_the_push()  # a new slide begins where the move begins
        if self._live:
            # Nothing on disk yet: the run's own frames stand in for a slide.
            if self._frame is not None:
                self._preview.show_frame(self._frame)
            else:
                self._preview.show_message(_GENERATING)  # opened before the first one
            self._update_counter()
            self._update_neighbors()
            return
        item = self._playlist.current()
        if item is None:
            return
        self._level_base = None  # a new item, so its own versions from the top
        self._level_index = 0
        if item[1] == LIVE:
            # Still being made: what it looks like so far, rather than a file.
            self._preview.show_frame(item[0])
        else:
            self._preview.show_media(item[0], item[1])
        self._update_counter()
        self._update_neighbors()
        self._refresh_note()  # the note belongs to whatever is on screen now
        if self._session_paused:
            self._preview.set_playback_paused(True)  # arrive holding
            return
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._arm_dwell(dwell)
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    # --- the slide's own clock: the advance, and the push that runs with it ---

    def _arm_dwell(self, dwell_ms: int) -> None:
        """Start the slide counting down, and the camera creeping in.

        One call rather than two, so the push can only ever be moving while the
        slide is actually on its way out. A lock, a spoken request, the
        session's OmniPause and a video all stop the advance, and each of them
        has to stop the move as well — a picture nothing is going to page off
        is a picture being looked at, not a shot being made.
        """
        self._timer.start(dwell_ms)
        self._zoom_timer.start()

    def _disarm_dwell(self) -> None:
        """Stop both, leaving the push exactly where it had got to — so a hold
        released mid-slide carries on from there rather than snapping back out."""
        self._timer.stop()
        self._zoom_timer.stop()

    def _restart_the_push(self) -> None:
        """Back to the whole picture, for the slide about to be drawn."""
        self._zoom_progress = 0.0
        self._preview.set_zoom(1.0)

    def _zoom_tick(self) -> None:
        """One step of the push, at the rate the pace asks for right now.

        Against the CURRENT dwell rather than the one the slide opened at: the
        pace is app-wide and can be turned up from another window mid-slide, and
        the move then simply slows from that moment. Recomputing the whole move
        against the new number instead would jump the picture back out.
        """
        self._zoom_progress += progress_step(TICK_MS, self._playlist.image_dwell_ms)
        self._preview.set_zoom(zoom_at(self._zoom_progress))

    def set_playlist(self, items, index: int) -> None:
        """Re-seed the set this show plays, on ``index``.

        What a double-clicked picture's show is armed with once the gallery has
        worked out the folder behind it: the view comes up on the one item the
        pane had, and this hands it the rest in the browser's own order. A view
        still following a generation keeps its frames — it has no place among
        those files until an arrow leaves them for one.
        """
        self._playlist = SlideshowPlaylist(
            items, image_dwell_ms=self._dwell_s * 1000, shuffle=in_order,
            start=index,
        )
        if self._live:
            self._update_counter()
            self._update_neighbors()
        else:
            self._show_current()

    def playing_now(self):
        """This pass as another show could take it up — its items in the order it
        is playing them, which one is on screen, and how long a slide holds — or
        ``None`` when there is no pass to take up.

        What Esc keeps when it closes the show, so pressing it again opens the
        same set on the same picture rather than a fresh shuffle of the folder.
        A show still following a generation has no items of its own and answers
        ``None``: what it was watching is either finished or gone by then.
        """
        if self._live or self._playlist.is_empty():
            return None
        return (self._playlist.in_play_order(), self._playlist.index,
                self._dwell_s * 1000)

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm Shift+Left/Right to step an image's enhancement levels.

        ``levels_by_path`` maps the file the set shows an image under to that
        image's versions, newest first, as ``(path, media_type, label)``. Plain
        Left/Right still steps the set; the shifted pair moves within the one
        image — its own axis, because a version is not a neighbor.
        """
        self._levels_by_path = {str(k): list(v) for k, v in levels_by_path.items()}
        self._refresh_note()

    def queue(self) -> SlideshowQueue:
        """The floated queue, for the gallery to wire its reorder and clear to —
        it is the same widget as the bottom strip and asks the same things."""
        return self._queue

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        """Show what is in flight in the corner — the same list, in the same
        order, the bottom strip this view is covering would be showing."""
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
            level_index=self._level_index,
            enhance_on_hold=self._enhance_on_hold,
        )

    def resume(self, state: ShowState) -> bool:
        """Open where a closed show left off rather than at the top of a fresh
        shuffle. Returns whether the place carried.

        Closing a show is usually a detour — the folder behind the picture, a fix
        in a tab — so coming back is coming back to that picture: the slide it
        ended on, still held if it was held, still showing the version it had been
        stepped to. The switch (holding-to-enhance) carries whether or not the
        place does; the place carries only while that slide is among these items,
        since a show of another folder has nowhere to put it.

        Called after :meth:`set_levels`, because which version a slide was showing
        is only a version once the levels behind it are armed.
        """
        if self._on_enhance is not None:
            self._enhance_on_hold = state.enhance_on_hold
        if self._live or not self._playlist.resume(state.order, state.current):
            return False
        self._playlist.set_locked(state.locked)
        self._show_current()
        if state.level_index:
            # A fresh slide sits at its top version, so the remembered index is
            # exactly the number of steps down to the one that was on screen.
            self._step_level(state.level_index)
        return True

    def note_added(self, path, media_type: str, prompt_id: str, still=None) -> None:
        """A generation that belongs to what this show is playing has landed: it
        joins the set, queued to come up next.

        A folder that is auto-generating is the case this is for. Without it the
        show plays the fixed set it opened with, so the very items being made
        while it runs — the ones being watched for — are the ones it never gets
        to. The slide on screen is left alone; only the counter and the stills
        either side move, since the set they describe just grew.

        One the show has been watching being made is already in the set as its
        own frames, and finishing is not a second slide: it keeps its place in
        the pass and simply becomes the file.
        """
        if self._playlist.replace_live(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._show_current()  # the file itself now, and on a clock again
            self._update_neighbors()  # it may be the still riding either side
            return
        if self._playlist.add((path, media_type, prompt_id, still)):
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
                self._preview.show_frame(frame)
            else:
                self._update_neighbors()  # it may be the still riding either side
            return
        if prompt_id in self._seen_live:
            return
        self._seen_live.add(prompt_id)
        if self._playlist.add((frame, LIVE, prompt_id, None)):
            self._update_counter()
            self._update_neighbors()

    def note_in_flight(self, prompt_ids) -> None:
        """Which runs are still being made, so a slide that has stopped being one
        leaves rather than holding the pass with the half-finished frame it got
        to. Cancelled and failed runs are what this is for; a finished one is out
        of this set too, but by then it is a file (:meth:`note_added`) and no
        longer a live slide to drop.
        """
        for prompt_id in [pid for pid in self._playlist.live_ids()
                          if pid not in prompt_ids]:
            showing = self._current_prompt_id() == prompt_id
            self._playlist.drop(prompt_id)
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
        self._preview.release_media(paths)

    def _delete_current(self):
        """Delete the current item (if a deleter is wired) and advance to the next.

        A slide that is still being made has nothing to condemn: the run is on the
        GPU and its row is a record of that, not a picture that has been judged.
        Up takes such a slide off the show and leaves the run alone — calling one
        off is the queue plate's Cancel, in the corner of this very screen.
        """
        self._playlist.unlock()  # the held slide is the one being culled
        item = self._playlist.current()
        if item is None:
            return
        if self._on_delete is not None and len(item) > 2 and item[1] != LIVE:
            self._on_delete(item[2])
        # Out of the full set too, so widening F-mode back cannot resurrect it.
        self._all_items = [kept for kept in self._all_items if kept is not item]
        self._playlist.remove_current()
        if self._playlist.is_empty():
            self.close()
        else:
            self._show_current()

    def _step(self, delta: int):
        """Manual stepping — an arrow, or the console's transport: moving off a
        slide releases its lock, so the way out of a hold is the same key that
        got you anywhere else, not a second press of the one that set it."""
        if self._live and self._playlist.is_empty():
            return  # a run with no folder armed behind it: nowhere to step to
        self._playlist.unlock()
        self._live = False  # stepped off a live generation: its frames stop landing
        if delta > 0:
            self._playlist.advance()
        else:
            self._playlist.back()
        self._show_current()

    def _step_level(self, delta: int) -> None:
        """Step ``delta`` enhancement levels within the image on screen.

        A no-op for an image with one version, and for a video — there is
        nothing to compare it against, and silently doing nothing is better
        than stepping the set when the shift was the whole point.
        """
        base = self._level_base or self._current_base()
        levels = self._levels_by_path.get(base) or []
        if len(levels) <= 1:
            return
        self._live = False
        self._level_base = base
        self._level_index = (self._level_index + delta) % len(levels)
        self._preview.show_media(*levels[self._level_index][:2])
        self._refresh_note()
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
            self._preview.show_frame(data)

    def show_landed(self, media: tuple) -> None:
        """The followed generation finished: show the saved file in place of its
        frames, and become an ordinary show of it."""
        if not self._live:
            return
        self._live = False
        self._playlist = SlideshowPlaylist(
            [media], image_dwell_ms=self._dwell_s * 1000, shuffle=in_order,
        )
        self._show_current()

    # --- what Genau's console acts on here ---------------------------------
    # Its transport steps Genau's clips and its clip-seconds pace how long an
    # unheld one stays up. Here the clips are the slides, so the same four
    # buttons step, hold and cull them, and the same pair sets the dwell.

    @property
    def dwell_s(self) -> int:
        """The seconds this show leaves an unheld slide up — nought while it is
        holding one picture, which is how a double-clicked one opens."""
        return self._dwell_s

    @property
    def locked(self) -> bool:
        """Whether what is on screen is being held — the console's padlock."""
        return self._playlist.locked

    # --- the transport, for whoever is driving: a key, the console, a word ---

    def step(self, delta: int) -> None:
        """Move a slide either way — what the arrows do, for a caller with no
        keyboard to press them with."""
        self._step(delta)

    def toggle_hold(self) -> None:
        """Hold the slide on screen, or let it go — Down's whole gesture."""
        self._hold_current()

    def cull(self) -> None:
        """Take the slide on screen away and move on — Up's."""
        self._delete_current()

    def stroke_reset(self) -> None:
        """Put the side back how it started, the players' own reset: F-mode
        dropped, the hold released, and the base set on screen again.

        Hosted, "how it started" is the REGION's base state, not this show's
        own: a player's reset drops its filter and leaves it browsing its whole
        library again, so a show started on one folder goes back to the library
        too rather than restarting that folder.  The gallery owns that set, so
        it comes in as a hook.  Standalone there is no such state and a show's
        defaults are simply its own set from the beginning.
        """
        if self._on_reset is not None:
            self._on_reset(self)
            return
        self.reset_in_place()

    def reset_in_place(self) -> None:
        """This show's own reset: F-mode dropped, the hold released, and the top
        of the set it is already playing back on screen."""
        if self._f_mode:
            self.toggle_f_mode()
        self._playlist.unlock()
        self._playlist.restart()
        self._show_current()

    def retune(self, items, *, order_label="Shuffle", looping=False) -> None:
        """Point this show at *items* instead, back at its own defaults.

        What a hosted reset does with the region's base set.  The window stays
        up rather than being closed and reopened: it covers a satellite player,
        and a region that blinks black between two shows is the thing the base
        state exists to avoid.  F-mode and the hold come off the way any reset
        takes them off, and the pass is a fresh shuffle.
        """
        self._f_mode = False
        self._all_items = list(items)
        self.hud_order_label = order_label
        self.hud_looping = looping
        self._live = not items
        self._replace_items(self._all_items)

    def set_audio_muted(self, muted: bool) -> None:
        """Silence (or voice) this show outright — what a hosting session does
        to a show landing on a satellite region."""
        self._preview.set_audio_muted(muted)

    def audio_muted(self) -> bool:
        return self._preview.audio_muted()

    def set_held(self, held: bool) -> bool:
        """Hold the slide on screen or let it go, saying which way rather than
        flipping; ``True`` when that moved it.

        Spoken "lock" and "unlock" are two words for a reason: someone talking
        to a picture is asking for a state, not for the other one — and cannot
        see the counter's padlock to know which the flip would give them.
        Holding is Down's whole gesture here, star and enhance included, because
        that is what holding means in this view and a spoken hold must not
        quietly mean less than a pressed one.
        """
        if held == self._playlist.locked:
            return False
        self._hold_current() if held else self._toggle_lock()
        return True

    def star(self) -> bool:
        """Bookmark the slide on screen; ``False`` when there is nothing to
        bookmark — a live generation has no row of its own yet."""
        item = self._playlist.current()
        if self._on_star is None or item is None or len(item) <= 2:
            return False
        self._on_star(item[2])
        return True

    # The stroke console reaches the three above by its own names: it drives this
    # view through a host protocol the main window's console shares.
    def stroke_step(self, delta: int) -> None:
        self.step(delta)

    def stroke_toggle_hold(self) -> None:
        self.toggle_hold()

    def stroke_cull(self) -> None:
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
        return self._preview.current_media_path()

    # --- what this show's HUD says, in the players' vocabulary -------------

    @property
    def hud_is_favorite(self) -> bool:
        """Whether the item on screen is a favorite (starred) — the players'
        star readout, over the same collection the Favorites shelf lists."""
        current = self._playlist.current()
        return bool(current and len(current) > 2 and current[2] in self._starred_ids)

    @property
    def hud_f_mode(self) -> bool:
        return self._f_mode

    def toggle_f_mode(self) -> None:
        """Narrow the set to the favorites, or widen it back — the players' own
        F-mode, over the starred items.  Ignored when no item of the set is a
        favorite: an empty show is not a mode."""
        if self._f_mode:
            self._f_mode = False
            self._replace_items(self._all_items)
            return
        narrowed = [item for item in self._all_items
                    if len(item) > 2 and item[2] in self._starred_ids]
        if not narrowed:
            return
        self._f_mode = True
        self._replace_items(narrowed)

    def _replace_items(self, items) -> None:
        """Stand a fresh pass up over *items*, keeping the pace and the pause."""
        self._playlist = SlideshowPlaylist(
            items, image_dwell_ms=self._playlist.image_dwell_ms)
        self._show_current()

    def hud_items(self):
        """The set for this show's HUD: ``(path, still)`` per item in
        stable order, the current item's 1-based position in that order, and
        the lock."""
        items = self._playlist.items
        cells = [(item[0], still_for(item) or "") for item in items]
        position = (self._playlist.order[self._playlist.index] + 1) if items else 0
        return cells, position, self._playlist.locked

    def show_item(self, path, *, hold: bool = False) -> None:
        """Jump to the item the HUD map named — a thumbnail click, the same
        jump a satellite's map makes; *hold* locks it there (the double-click),
        exactly as it locks a player's clip."""
        for index, item in enumerate(self._playlist.items):
            if str(item[0]) != str(path):
                continue
            self._playlist.unlock()
            self._playlist.jump_to(index)
            self._show_current()
            if hold:
                self._toggle_lock()
            return

    def set_session_paused(self, paused: bool) -> None:
        """Freeze or resume the show whole — the hosting session's OmniPause.

        Distinct from the lock: a lock holds one slide by choice and replays
        its clip; this stops time itself — the dwell clock and any playing
        video — and hands both back on resume.  Held as state rather than
        applied once: a step while frozen lands on a new slide, and that slide
        must arrive holding too (see :meth:`_show_current`).
        """
        self._session_paused = paused
        if paused:
            self._disarm_dwell()
        else:
            dwell = self._playlist.dwell_ms()
            if dwell is not None:
                self._arm_dwell(dwell)
        self._preview.set_playback_paused(paused)

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
        if not self._playlist.locked and not self._live:
            self._show_current()

    def _on_video_ended(self):
        """A clip finished: replay it while held, else move on. A lock is
        repeat-one here, as it is on a Fun Time satellite — and a pace of nought
        holds the clip the same way, since nought means nothing moves on its own.
        A request being spoken holds it too: paging on mid-sentence is exactly
        what that pause exists to stop.
        """
        if self._playlist.holding() or not self._dwell_s:
            self._show_current()
        else:
            self._advance()

    def _on_video_unplayable(self):
        """A clip this backend cannot open: step past it, whatever holds it.

        Unlike a clip that ended, this one never will, so the replay a lock or
        a pace of nought asks for would hold a black screen for the rest of the
        session.  The item stays in the set — the fault is the backend's, not
        the file's — but the show moves on.

        The session's OmniPause is the one hold this yields to: the room is
        frozen, and a show that walked its set looking for something playable
        would be the room moving.  The black rectangle waits for the resume.
        """
        if self._session_paused:
            return
        logger.warning("Slideshow: a clip would not play; stepping past it")
        self._advance()

    # --- the hold a spoken request puts on the show ------------------------

    def hold_for_request(self, holding: bool, note: str = "") -> None:
        """Stop (or release) the advance while a request is being spoken.

        Not the user's lock: a slide they had locked is still locked when the
        request ends, and one they hadn't goes back to its dwell. ``note`` is
        what the corner should say while it holds — the only sign, in a view
        with no panels, that the mic is taking a sentence.
        """
        self._playlist.set_paused(holding)
        if holding:
            self._disarm_dwell()
            self._note_timer.stop()  # it holds, rather than fading after a beat
            self._request_note = note
            self._refresh_note()
        else:
            self._request_note = ""
            self._refresh_note()
            if not self._playlist.locked:
                self._rearm_dwell()

    def note_request(self, message: str) -> None:
        """Say what a spoken request did, where the speaker is looking."""
        self._flash_note(message, ms=3000)

    def _rearm_dwell(self) -> None:
        """Start the dwell timer again for the slide already on screen — a
        released pause resumes the show rather than restarting the media, which
        for a video part-way through would send it back to its first frame."""
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._arm_dwell(dwell)

    def _hold_current(self):
        """Down: hold the slide, star it, and ask for it to be enhanced.

        Stopping on a picture is the gesture that says you want it, so it is
        also the one that stars it and the one that asks for the better version
        — nothing extra to press, and the run happens while you keep looking at
        it. Releasing the hold asks for nothing; only stopping does, and only on
        a picture that has never been enhanced (the gallery's call).
        """
        held = self._toggle_lock()
        if held:
            self._enhance_current()

    def _toggle_enhance_on_hold(self):
        """E: stop (or resume) holding a slide meaning "enhance this"."""
        if self._on_enhance is None:
            return
        self._enhance_on_hold = not self._enhance_on_hold
        self._flash_note(
            "Enhance on hold: on" if self._enhance_on_hold else "Enhance on hold: off"
        )

    def _enhance_current(self):
        """Ask the gallery to enhance the slide on screen, if it wants one.

        The gallery decides whether it does — it is the one that knows whether
        this image has already been enhanced, and an enhanced one wants nothing.
        ``True`` back means a run started, and the note says so until the
        finished version arrives.
        """
        if self._on_enhance is None or not self._enhance_on_hold:
            return
        if self._playlist.current_is_live():
            return  # no file yet to make a better version of; the hold still holds
        prompt_id = self._current_prompt_id()
        if prompt_id is None or prompt_id in self._enhancing:
            return
        if self._on_enhance(prompt_id):
            self._enhancing.add(prompt_id)
            self._refresh_note()

    def note_enhanced(self, prompt_id: str, path, media_type: str = "image",
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
        self._enhancing.discard(prompt_id)
        self._enhance_status.pop(prompt_id, None)
        if self._playlist.replace_item(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._level_base = None  # its versions are a level deeper now
                self._level_index = 0
                self._preview.show_media(path, media_type)
                self.media_changed.emit()
            self._update_neighbors()  # it may be the still riding either side
        self._refresh_note()

    def note_enhancing(self, statuses: dict) -> None:
        """How every enhancement in flight is going, as the gallery reads it:
        ``prompt_id`` -> ``"running"`` or ``"queued"``.

        Pushed in whenever it changes rather than asked for, because the show has
        no way to tell: a hold launches a run and hears only that one started,
        and a show of held slides has a line of them out at once with ComfyUI
        working through it one at a time. Without this the note claimed every one
        of them was being made the moment it was asked for.

        Carries every run in flight, not only the ones this show asked for —
        which of them the corner speaks for is :meth:`_refresh_note`'s call, and
        the ones it doesn't cost a dict entry each.
        """
        if statuses == self._enhance_status:
            return
        self._enhance_status = dict(statuses)
        # Not over a flash: a status arriving mid-sentence would wipe the answer
        # to a spoken command. The flash's own timer refreshes on the way out.
        if not self._note_timer.isActive():
            self._refresh_note()

    def _current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a playlist assembled
        without ids (a test's) names nothing.

        Read off the playlist item rather than off the file showing, so it is
        still the right answer while Shift+Left/Right has stepped onto one of
        that item's other versions.
        """
        item = self._playlist.current()
        return item[2] if item is not None and len(item) > 2 else None

    def _current_base(self) -> str:
        """The file the set lists the item on screen under — what its versions
        are keyed by. Empty for one still being made: its slide is frames rather
        than a file, and nothing is keyed off those."""
        item = self._playlist.current()
        if item is None or item[1] == LIVE:
            return ""
        return str(item[0])

    def voice_target(self):
        """The generation a spoken order or request is about: the slide on
        screen — what the speaker is looking at while saying it."""
        return self._current_prompt_id()

    def note_voice_run(self, prompt_id, message: str) -> None:
        """Say what a spoken order did and, when it launched a run
        (``prompt_id``), keep the note on that run once the flash fades — the
        same note a hold's enhance earns, and it reads the same way: where the
        run has got to, not merely that one was asked for."""
        if prompt_id is not None:
            self._enhancing.add(prompt_id)
        self.note_voice_command(message)

    def note_voice_command(self, message: str) -> None:
        """Say what a spoken command did. Here rather than in the gallery's own
        caption because the speaker is looking at this — the window behind it is
        covered by the very show being talked to."""
        self._flash_note(message, ms=2500)

    def _refresh_note(self):
        """Say what there is to say about the item on screen: the request being
        spoken (which holds the show, so it outranks the rest), that this slide
        is still being made, where the version being made of it has got to, or —
        failing those — which of its versions this one is.

        Stepping levels is invisible without the last line: two versions of one
        picture differ by texture, which is exactly what you cannot tell apart
        from memory. And an early iteration looks exactly like a bad generation,
        so a slide that is still cooking says so, in the same corner and for the
        same reason an enhancement in flight does.
        """
        if self._request_note:
            self._show_note(self._request_note)
            return
        if self._playlist.current_is_live():
            self._show_note(_GENERATING)
            return
        prompt_id = self._current_prompt_id()
        if prompt_id is not None and prompt_id in self._enhancing:
            # Being made, or still in the line — an ask made minutes ago on a
            # slide the show has come back around to is usually the latter, and
            # "Enhancing…" over a run nobody has started yet is simply wrong
            # about the picture being looked at. A run nothing has been said
            # about counts as waiting: the ask is what has happened to it so far.
            self._show_note(_ENHANCING
                            if self._enhance_status.get(prompt_id) == "running"
                            else _ENHANCE_QUEUED)
            return
        levels = self._levels_by_path.get(self._level_base or self._current_base()) or []
        if len(levels) <= 1:
            self._note.hide()
            return
        level = levels[self._level_index]
        label = level[2] if len(level) > 2 else f"Version {self._level_index + 1}"
        self._show_note(f"{label} — {self._level_index + 1} of {len(levels)}")

    def _show_note(self, text: str) -> None:
        self._note.say(text)

    def _flash_note(self, text: str, ms: int = 1500):
        """Say something for a moment, then fall back to whatever the note would
        otherwise be saying."""
        self._show_note(text)
        self._note_timer.start(ms)

    def _reposition_note(self):
        self._note.reposition()

    def _toggle_lock(self) -> bool:
        """Flip the lock; returns whether the slide is now held.

        Locking also stars what is on screen: holding a slide is how the user says
        this one is worth keeping, and having said it they should not have to say
        it twice in two ways.
        """
        if self._playlist.toggle_lock():
            self._disarm_dwell()  # hold on the current item, and on the push
            self.star()
            self._update_counter()
            if self._on_lock is not None:
                prompt_id = self._current_prompt_id()
                if prompt_id is not None:
                    self._on_lock(prompt_id)
            return True
        self._show_current()  # released, re-arming the dwell timer
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
        return drive_target_for(self._preview.current_video_path(), self._preview.player())

    # --- the neighboring items ---------------------------------------------

    def adopt_hud(self):
        """The players' HUD went on this show: its map now says where in the
        set this is and what is around it, so the view's own furnishings — the
        neighbor stills, the position plate — come off.

        Every show wears it, hosted on a satellite region or fullscreen on its
        own: the map is the same map either way, and a show that kept its own
        stills and plate beside it would be saying everything twice.
        """
        self._hud_dressed = True
        self._neighbors.set_neighbors(None, None)
        self._counter.hide()

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
        rect = self._preview.media_rect()
        rect.moveTopLeft(self._preview.mapTo(self, rect.topLeft()))
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
            self._hold_current()    # hold it, star it, and enhance it
        elif key == Qt.Key.Key_E:
            self._toggle_enhance_on_hold()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_current()    # out of the slideshow, into its folder
        elif apply_stroke_key(self._stroke, key,
                              on_drive_toggle=self._on_drive_toggle):
            # Space belongs to the stroke cluster now, everywhere — locking the
            # slideshow is Down, matching the auto-generate view's lock.
            self._stroke_panel.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._counter.reposition()
        self._reposition_queue()
        self._reposition_neighbors()
        self._reposition_note()
        if self._stroke_panel is not None:
            self._stroke_panel.reposition()

    def closeEvent(self, event):
        """Leave, handing the gallery the item the show ended on if there is one.

        Enter names that item; so does a lock, which is the user saying this is
        the one — so a show ended on a held slide lands on that slide, rather
        than leaving the gallery wherever it was before the show. Ended on a
        slide nobody held (Escape, a double-click, the spoken "close", the last
        item culled), it hands nothing over and leaves the gallery alone.
        """
        self._disarm_dwell()
        self._preview.clear()  # release any held video file so it can be deleted
        landing = self._land_on
        if landing is None and self._playlist.locked:
            landing = self._current_prompt_id()
        # Both cleared before a second close could read them, so the handover
        # happens once. The lock outlives the first emit because the gallery
        # reads this show's state there, and a slide closed under a hold is one
        # a reopened show holds.
        self._land_on = None
        self.closed.emit()
        self._playlist.unlock()
        if landing is not None:
            self.open_requested.emit(landing)
        super().closeEvent(event)
