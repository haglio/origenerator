"""The one slideshow, whichever Funestra shows it: one of a session's, or the one
in this app's own window.

It drives its Funestra through a channel that answers three calls -- the list it
plays, the verbs it takes, the status it reads back -- which a session's Funestra
answers on its files (:class:`~origenerator.fun_time_mode.FunestraChannel`) and
the window's in this process (:class:`~origenerator.gui.funestra_pane.PaneChannel`).
The Funestra owns what is on screen from there: it holds a picture for the pace,
plays a clip to its end and rolls onto the next, repeats the one it is locked
onto, and freezes with the room.  What differs is only where the slideshow is
seen -- *shown*: the panel, the lines it says and the room's pause go to the
session's Funestra and the gallery's caption, or to the window.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from funestra.file_channel import publish_whole
from funestra.funestra_verbs import (
    CLEAR_FRAME,
    HOLD_PICTURE,
    LET_GO,
    LOCK_OFF,
    LOCK_ON,
    NEXT,
    PREV,
    RELOAD_PLAYLIST,
    SET_PACE,
    SHOW_FRAME,
    TRASH,
    play_file,
)
from funestra.playlist import PlaylistItem
from funestra.satellite_hud import hud_text
from funestra.status import parse_status
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.level_stepper import LevelStepper
from origenerator.gui.notice_overlay import HEARD_MARK, NOTICE, WARNING
from origenerator.gui.slideshow_map import SEED_AXIS
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_panel import slideshow_hud_model
from origenerator.gui.slideshow_pass import playlist_item, rotated_onto, slide_item
from origenerator.gui.slideshow_set import (
    LOOP_IS_A_LOCK,
    LOOP_OFF,
    SlideshowSet,
    item_note,
    looping_note,
    narrow_to_acts,
    narrow_to_the_act_on_screen,
)
from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.media import MediaType
from origenerator.osr2_driver import drive_target_for
from origenerator.slideshow import Slide, SlideshowFilters, SlideshowState

logger = logging.getLogger(__name__)

# How often the Funestra is asked what it is showing.  It publishes its status
# five times a second; this is near enough that the map follows the slide
# rather than trailing it, and idle ticks cost a read and a comparison.
_POLL_MS = 200

READER_HOLD_BUDGET_S = 1.0
_RETRY_SPACING_S = 0.005


class FunestraSlideshow(QObject):
    """A slideshow driving one of the session's Funestras."""

    # Enter on an item, and a lock: the gallery lands on that generation.  Only
    # the lock reaches it here — a Funestra has no Enter to press.
    open_requested = pyqtSignal(str)
    # The slideshow is over: the side has nothing of this app's on it now.
    closed = pyqtSignal()
    # A different item is on screen.
    media_changed = pyqtSignal()

    def __init__(self, items, *, side: str, channel, frames: FrameFiles, actions=None,
                 hud=None, pace=None, image_dwell_ms=None, start=None, shuffle=None,
                 say=None, shown=None, parent=None):
        super().__init__(parent)
        self._side = side
        self.channel = channel
        self.shown = shown if shown is not None else OnASessionsFunestra(self, side, channel, say)
        self._frames = frames
        self._request_holds_it = False
        self._held_short = False
        self._frame_on_funestra: Path | None = None
        # What a press here asks the gallery to do on its behalf — the half of
        # each gesture that lands on the generation rather than on the slide.
        self._actions = actions if actions is not None else SlideshowActions()
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        self._pace.changed.connect(self._on_pace_changed)
        self._take_set(items, image_dwell_ms=image_dwell_ms, start=start,
                       shuffle=shuffle, hud=hud)
        self._open = True
        # What the Funestra last said it was showing: a picture that has moved on
        # by itself is news that arrives this way and no other.
        self._showing = ""
        self._locked = False
        self._keep_told: bool | None = None
        self._refusal_checked = False
        self._loads_seen: str | None = None
        self._levels = LevelStepper()
        opened_on_a_slide = start is not None
        if opened_on_a_slide:
            self._showing = self._funestra_status().video
        self._hand_over(land=opened_on_a_slide)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        self.tick()

    # --- handing the Funestra what to play ------------------------------------

    def _take_set(self, items, *, image_dwell_ms, start, shuffle, hud) -> None:
        if image_dwell_ms is None:
            image_dwell_ms = self._pace.dwell_ms
        self._dwell_s = image_dwell_ms // 1000
        self._following = None
        self._set = SlideshowSet(items, actions=self._actions,
                                 shuffle=shuffle, start=start, hud=hud,
                                 on_pass_change=self._pass_changed)

    def play(self, items, *, image_dwell_ms=None, start=None, shuffle=None,
             hud=None, actions=None) -> None:
        if actions is not None:
            self._actions = actions
        self._unlock()
        self._take_set(items, image_dwell_ms=image_dwell_ms, start=start,
                       shuffle=shuffle, hud=hud)
        self._hand_over(land=True)
        self._publish()

    def _hand_over(self, *, land: bool = False) -> None:
        """Give the Funestra this pass to play, written rotated onto the slide
        this slideshow stands on: a Funestra showing nothing of it opens there, and a
        reload keeps the item a Funestra is on wherever that item survived."""
        current = self._set.playlist.current()
        rotated = rotated_onto(self._set.playlist.in_play_order(), current)
        self.channel.write_playlist([self._funestra_item(item) for item in rotated])
        lands = land and current is not None and self._file_of(current) != self._showing
        if lands:
            self._levels.restart()
        self._tell_the_pace()  # ahead of the file it opens, which reads it
        self._tell_the_keep()
        if lands:
            # Before the reload, which then keeps it: after, it would load twice.
            self._send(play_file(self._funestra_item(current)))
        self._send(RELOAD_PLAYLIST)

    def _tell_the_pace(self) -> None:
        self._send(f"{SET_PACE} {self._dwell_s}")
        self._hold_what_is_being_made_for_half()

    def _tell_the_keep(self) -> None:
        keeps = self._keeps()
        if keeps != self._keep_told:
            self._keep_told = keeps
            self._send(LOCK_ON if keeps else LOCK_OFF)

    def _keeps(self) -> bool:
        return (self._locked or self._request_holds_it or self._on_the_run()
                or self._levels.stepping)

    def _on_the_run(self) -> bool:
        current = self._set.playlist.current()
        return (current is not None and current.is_live
                and current.prompt_id == self._following)

    def _file_of(self, slide) -> str:
        if slide.is_live:
            return str(self._frames.first_of(slide.prompt_id))
        return str(slide.path)

    def _funestra_item(self, slide) -> PlaylistItem:
        if slide.is_live:
            return PlaylistItem(Path(self._file_of(slide)))
        return slide_item(slide, self._levels.points_of_interest(self._file_of(slide)))

    def _send(self, verb: str) -> None:
        if not self.channel.send(verb):
            logger.warning("Dropped %s for the %s Funestra (command file locked)",
                           verb, self._side)

    # --- the pace ----------------------------------------------------------

    @property
    def dwell_s(self) -> int:
        """The seconds an unlocked picture holds the Funestra's screen."""
        return self._dwell_s

    def set_dwell_s(self, seconds: int) -> None:
        """Take a new pace, and hand it on: the number is app-wide, so a pace
        set over this slideshow is what the next one opens at."""
        self._pace.set_seconds(seconds)  # fires _on_pace_changed if it moved
        self._apply_dwell(self._pace.seconds)  # and take it even if it didn't

    def _on_pace_changed(self, seconds: int) -> None:
        self._apply_dwell(seconds)

    def _apply_dwell(self, seconds: int) -> None:
        """Tell the Funestra how long to hold a picture, when the number moved.

        The pace is the Funestra's to keep from there: it holds the frame that
        long and then ends the file, which is how a picture moves on at all.
        """
        seconds = max(0, int(seconds))
        if seconds == self._dwell_s:
            return
        self._dwell_s = seconds
        self._tell_the_pace()

    def _pass_changed(self, kept: bool) -> None:
        """A fresh pass was dealt: the Funestra is playing the old one, so it is
        handed the new one — keeping the slide on screen when the pass kept it,
        and sent to this slideshow's own when it did not.  The panel follows at
        once, so a loop lights its button on the press rather than a tick
        later."""
        if self._set.loop is not None:
            self._unlock()
        self._hand_over(land=not kept)
        self._publish()

    # --- what the Funestra says it is showing ---------------------------------

    def tick(self) -> None:
        """Read the Funestra's status, follow it, and publish the panel."""
        if not self._open:
            return
        fields = self.channel.status()
        if fields:  # a Funestra not open yet, or not read just now, says nothing
            self._follow_the_funestra(fields)
        self._publish()

    def _follow_the_funestra(self, fields: dict) -> None:
        status = parse_status(fields)
        if status.video and status.video != self._showing:
            self._showing = status.video
            self._follow(status.video)
            self._held_short = False
            self._hold_what_is_being_made_for_half()
            self._frame_on_funestra = None
            self._show_what_is_being_made()
        self._step_past_a_file_that_would_not_open(fields, status)
        self._tell_the_keep()

    def _hold_what_is_being_made_for_half(self) -> None:
        """An item something better is being made of holds the Funestra for
        half the pace, its move still made at the whole: the Funestra moves on
        from it early, and its scrubber counts that half down.  Any other, and
        one under the lock, holds for the pace."""
        current, pace = self._set.playlist.current(), self._dwell_s
        held_for = self._set.pace_for(current, pace) if current is not None and pace else pace
        if pace and held_for < pace and not self._keeps():
            self._send(f"{HOLD_PICTURE} {held_for:g}")
            self._held_short = True
        elif self._held_short:
            self._send(f"{HOLD_PICTURE} 0")
            self._held_short = False

    def _step_past_a_file_that_would_not_open(self, fields: dict, status) -> None:
        if fields.get("loads") != self._loads_seen:
            self._loads_seen, self._refusal_checked = fields.get("loads"), False
        if self._refusal_checked or fields.get("idle") != "1" or status.paused:
            return
        self._refusal_checked = True
        logger.warning("The %s Funestra would not open a file; stepping past it", self._side)
        self._unlock()
        self._send(NEXT)

    def _show_what_is_being_made(self) -> None:
        current = self._set.playlist.current()
        frame = None
        if current is not None and self._file_of(current) == self._showing:
            frame = self._set.frame_being_made_of(current)
        path = None if frame is None else self._frames.write(current.prompt_id, frame)
        if path == self._frame_on_funestra:
            return
        self._frame_on_funestra = path
        self._send(CLEAR_FRAME if path is None else f"{SHOW_FRAME} {path}")

    def _funestra_status(self):
        return parse_status(self.channel.status())

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm the versions button and the shifted step keys for this set.

        ``levels_by_path`` maps the file the set shows an item under to that
        item's versions, newest first, as ``(path, media_type, label)``.
        """
        if self._levels.arm(levels_by_path):
            self._hand_over()
        self._publish()

    def add_levels(self, levels_by_path: dict) -> None:
        if self._levels.add(levels_by_path):
            self._hand_over()
        self._publish()

    @property
    def has_other_versions(self) -> bool:
        """Whether the item on screen was filed more than once — what draws
        the band's versions button live rather than faded."""
        return len(self._levels.levels(base=self._current_base())) > 1

    def slideshow_step_version(self, delta: int) -> None:
        """Put another version of the item on screen up: an image's enhancement
        levels, or a video's Evolver upscale and the video itself.

        An item filed once is left alone rather than paged, since the shift was
        the whole point of the press.  The Funestra is told which file to play
        rather than asked to step its own way through them, because the place
        within the versions is held here, ahead of the status the Funestra is
        still publishing.
        """
        version = self._levels.step(delta, base=self._current_base())
        if version is None:
            return
        self._tell_the_keep()
        self._send(play_file(playlist_item(version.path, version.media_type,
                                           version.points_of_interest)))
        self.media_changed.emit()

    def _leave_the_versions(self) -> None:
        stepped = self._levels.stepping
        self._levels.restart()
        if stepped:
            # The version stepped to was spliced into the Funestra's list after its
            # item; the set's own list stands it back on the item before it moves.
            self._hand_over()
        self._tell_the_keep()

    def _current_base(self) -> str:
        """The file the set lists the item on screen under — what its versions
        are keyed by."""
        item = self._set.playlist.current()
        return "" if item is None else self._file_of(item)

    def _follow(self, video: str) -> None:
        """Stand the pass on the item the Funestra just moved to.

        The Funestra walks the list by itself — a picture's pace runs out, a clip
        ends — so this is how the map, the star and every word about "this one"
        find out which item that is.
        """
        for index, item in enumerate(self._set.playlist.items):
            if self._file_of(item) == video:
                if item is not self._set.playlist.current():
                    self._levels.restart()  # a new item, so its own versions from the top
                self._set.playlist.jump_to(index)
                self.media_changed.emit()
                return

    def _publish(self) -> None:
        self.shown.panel_changed()

    # --- the transport: a button on the panel, a word, a session's hotkey ----

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def locked_on(self) -> str | None:
        return self._set.current_prompt_id() if self.locked else None

    def slideshow_step(self, delta: int) -> None:
        """Step the Funestra either way.  Moving off a locked slide releases the
        lock, the way the Funestras' own prev/next cancel a lock — and a loop
        down to the picture on screen is ended first, so what the Funestra is
        handed to step into is the set rather than a list of one."""
        self._unlock()
        if delta > 0:
            self._set.end_a_loop_of_one()
        self._leave_the_versions()
        self._send(NEXT if delta > 0 else PREV)

    def slideshow_toggle_lock(self) -> None:
        """Lock what is on screen, or let it go — the whole of the gesture."""
        self.set_locked(not self.locked)

    def set_locked(self, locked: bool) -> bool:
        """Lock the item on screen or let it go, saying which way rather than
        flipping; ``True`` when that moved it.

        Locking is the whole gesture it is in a window: the Funestra repeats the
        item, and the slideshow favorites it, asks for a better version of it, and — in
        a session — hands it to the gallery to open.
        """
        if locked == self.locked:
            return False
        self._lock(locked)
        if not locked:
            return True
        self.favorite()
        self._enhance_current()
        prompt_id = self._set.current_prompt_id()
        if self._actions.lock is not None and prompt_id is not None:
            self._actions.lock(prompt_id)
        return True

    def _lock(self, on: bool) -> None:
        self._locked = on
        self._tell_the_keep()
        self._publish()

    def _unlock(self) -> None:
        if self.locked:
            self._lock(False)

    def slideshow_cull(self) -> None:
        """The Funestras' "weird": a favorite loses its star and the Funestra moves
        on; anything else is taken away and the Funestra moves on.

        The Funestra is told to drop a condemned item before the generation is:
        it is playing that very file, and Windows will not move a file a
        process still has open — the recovery bin's own retries cover the
        moment the Funestra takes to let go.
        """
        item = self._set.playlist.current()
        if item is None:
            return
        self._leave_the_versions()
        self._lock(False)  # the locked slide is the one being culled
        if self._set.unfavorite_current(self._actions.unfavorite):
            self._flash("Unfavorited")
            self._send(NEXT)
            return
        self._send(TRASH)
        # Letting go already, so the delete's own release must not ask it to
        # move on a second time and skip the item after this one as well.
        self._showing = ""
        self._set.forget(item)
        self._set.playlist.remove_current()
        self._frames.forget(item.prompt_id)
        if self._set.playlist.is_empty():
            # A slideshow culled empty is over, and the side goes back to its base
            # state — which hands the Funestra another list to move on to.
            self.close()
        elif self._set.end_a_loop_of_one():
            self._lock_what_the_cull_left()  # its pass change hands the set over
        else:
            self._hand_over()
        if item.prompt_id is not None and not item.is_live and self._actions.delete is not None:
            self._condemn(item.prompt_id)

    def _lock_what_the_cull_left(self) -> None:
        """A row worn down to one picture plays that picture over and over,
        which is the lock — so the cull that wore it down ends the loop and
        tells the Funestra to lock what is left.  The lock is the state and
        nothing else: none of what a pressed lock also does — the star, the
        better version, the gallery — happened, because nobody pressed one."""
        self._lock(True)
        self._flash("Locked")

    def _condemn(self, prompt_id: str) -> None:
        """Delete the generation, saying so where it could not be.

        A Funestra is another process, and one with nothing else to move on to
        keeps the file open for good; that is a delete refused, not a fault to
        take the app down over.
        """
        try:
            self._actions.delete(prompt_id)
        except OSError:
            logger.exception("The %s Funestra kept a condemned generation open", self._side)
            self._flash("couldn't delete that one — the Funestra still has it open",
                        kind=WARNING, mark="trash")

    def cull(self) -> None:
        self.slideshow_cull()

    def favorite(self) -> bool:
        """Bookmark the item on screen; ``False`` when there is nothing to
        bookmark."""
        prompt_id = self._set.current_prompt_id()
        if self._actions.favorite is None or prompt_id is None:
            return False
        self._actions.favorite(prompt_id)
        self._set.favorite_ids.add(prompt_id)  # the star readout and F-mode follow it
        return True

    def slideshow_reset(self) -> None:
        """Put the side back how it started — the region's base state, which
        the gallery owns, else this set from the top."""
        if self._actions.reset is not None:
            self._actions.reset(self)
            return
        self.reset_in_place()

    def slideshow_order(self, *, latest: bool) -> None:
        if self._actions.reorder is not None:
            self._actions.reorder(self, latest)

    def reset_in_place(self) -> None:
        """This slideshow's own reset: both switches dropped, the lock released, and
        the set it is already playing started over."""
        self._lock(False)
        if self._set.drop_the_filters():
            return  # the Funestra has the fresh pass already (see _pass_changed)
        self._set.playlist.restart()
        self._hand_over(land=True)

    def retune(self, items, *, enhanced_ids=None) -> None:
        """Point this slideshow at the region's base set instead — what a hosted
        reset does, with both switches off and a fresh pass."""
        self._unlock()
        self._set.retune(items, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=(),
                keep_slide: bool = False) -> None:
        self._unlock()
        self._set.reorder(items, latest=latest, enhanced_ids=enhanced_ids,
                          keep_slide=keep_slide)

    def show_item(self, path, *, lock: bool = False) -> None:
        """Play the item the HUD map named — a thumbnail click, the same jump
        it makes on a Funestra's own map; *lock* keeps it there."""
        slide = self._set.slide_for_path(path)
        if slide is None:
            return
        self._jump_to(slide)
        self._lock(lock)

    def _jump_to(self, slide) -> None:
        """Stand the pass on *slide* and send the Funestra there.

        One verb either way: the Funestra jumps to a file already in its list
        and splices one that is not in after what it is showing — which is
        exactly where the pass put a cell it never held.  A jump that ends a
        loop re-deals the pass, and that hands the Funestra the browse first
        (see :meth:`_pass_changed`).
        """
        self._set.jump_to(slide)
        self._leave_the_versions()
        self._send(play_file(self._funestra_item(slide)))
        self._publish()

    # --- the map, and the loops along it -----------------------------------

    def hud_map(self):
        return self._set.map()

    def pass_size(self) -> int:
        return len(self._set.playlist)

    def slideshow_loop(self, axis: str) -> None:
        """Loop the map's *axis* around the item on screen, or end the loop
        for "".  The Funestra is handed the row or the column to play, and the
        set it was browsing when the loop ends (see :meth:`_pass_changed`)."""
        if not axis:
            if self._set.end_loop(self._browse_it_all):
                self._flash("Loop off")
            return
        if self._set.start_loop(axis):
            self._flash(looping_note(self._set))
        else:
            self._lock_instead_of_looping()

    def _lock_instead_of_looping(self) -> None:
        """Tell the Funestra to lock what it is showing: the answer a loop asked
        of a row of one gets on a Funestra of its own, where the loop button of a
        group holding one clip locks that clip.  A row that size is the picture
        itself, so the press means "this one" rather than nothing; and a lock is
        not a loop, so a loop that was running is dropped."""
        self._set.end_loop()
        self.set_locked(True)
        self._flash("Locked")

    def _browse_it_all(self) -> bool:
        if self._actions.browse_all is None:
            return False
        return bool(self._actions.browse_all(self))

    def slideshow_loop_cycle(self) -> None:
        """The loop key: seeds, then actions, then off — and the lock when
        there is nothing on either axis to loop."""
        stepped = self._set.step_loop(self._browse_it_all)
        if stepped == LOOP_IS_A_LOCK:
            self.set_locked(not self.locked)
            self._flash("Locked" if self.locked else "Unlocked")
        elif stepped == LOOP_OFF:
            self._flash("Loop off")
        else:
            self._flash(looping_note(self._set))

    def slideshow_more_seeds(self) -> None:
        if self._set.more_seeds():
            self._flash("More seeds")
        else:
            self._flash("Widening net failed", kind=WARNING)

    def slideshow_filter(self, query: str) -> None:
        """The button at the head of a map row, and the session's spoken acts.

        A configuration's row is gone to and its seeds looped, the way it was
        before the acts joined the column; an act's narrows the slideshow to it.
        """
        row = self._set.configuration_row(query)
        if row is not None:
            if row is not self._set.playlist.current():
                self._unlock()
                self._jump_to(row)
            self.slideshow_loop(SEED_AXIS)
            return
        said, narrowed = narrow_to_acts(self._set, query)
        self._flash(said, kind=NOTICE if narrowed else WARNING)

    def slideshow_filter_to_the_act_on_screen(self) -> None:
        said, narrowed = narrow_to_the_act_on_screen(self._set)
        self._flash(said, kind=NOTICE if narrowed else WARNING)

    def slideshow_nav(self, direction: str) -> None:
        target = self._set.nav_target(direction)
        if target is None:
            self._flash("Nothing that way", kind=WARNING)
            return
        self._unlock()
        self._jump_to(target)

    # --- the two switches, and what the panel reads off the set --------------

    @property
    def hud_prompt_id(self) -> str:
        """The generation on screen, by id — what names it on the panel."""
        return self._set.current_prompt_id() or ""

    @property
    def hud_is_favorite(self) -> bool:
        return self._set.is_favorite

    @property
    def hud_item_note(self) -> str:
        return item_note(self._set, levels=self._levels.levels(base=self._current_base()),
                         level_index=self._levels.index)

    @property
    def hud_favorites_filter(self) -> bool:
        return self._set.filters.favorites

    @property
    def hud_enhanced_mode(self) -> bool:
        return self._set.filters.enhanced

    @property
    def hud_act_filter(self) -> str:
        return self._set.filters.act

    @property
    def hud_order_label(self) -> str:
        return self._set.order_label

    def toggle_favorites_filter(self) -> bool:
        return self.set_favorites_filter(not self._set.filters.favorites)

    def set_favorites_filter(self, on: bool) -> bool:
        return self._set.set_filters(replace(self._set.filters, favorites=bool(on)))

    def toggle_enhanced_mode(self) -> bool:
        return self.set_enhanced_mode(not self._set.filters.enhanced)

    def set_enhanced_mode(self, on: bool) -> bool:
        return self._set.set_filters(replace(self._set.filters, enhanced=bool(on)))

    def clear_modes(self) -> bool:
        return self._set.set_filters(SlideshowFilters())

    def voice_target(self):
        """The generation a spoken order is about: the item on screen."""
        return self._set.current_prompt_id()

    # --- keeping the set current --------------------------------------------

    def holds(self, prompt_id: str) -> bool:
        return self._set.playlist.holds(prompt_id)

    def note_added(self, path, media_type: str, prompt_id: str, still=None, *,
                   favorite: bool = False, enhanced: bool = False) -> None:
        """A generation that belongs to what this slideshow plays has landed: it
        joins the set, queued to come up next, and the Funestra is handed the
        list again so it can reach it."""
        if favorite:
            self._set.favorite_ids.add(prompt_id)
        if enhanced:
            self._set.enhanced_ids.add(prompt_id)
        slide = Slide(path, media_type, prompt_id, still)
        self._set.remember(slide)
        if self._set.playlist.replace_live(prompt_id, path, media_type, still):
            self._hand_over(land=True)
            self._frames.forget(prompt_id)
        elif self._set.passes(slide) and self._set.playlist.add(slide):
            self._hand_over()

    def note_enhanced(self, prompt_id: str, path, media_type: str = MediaType.IMAGE,
                      still=None) -> None:
        """An enhancement of one of these items landed: the slideshow plays the
        better version from here on, wherever that item sits in the pass."""
        self._set.note_enhancement_landed(prompt_id)
        upgraded = self._set.upgrade(prompt_id, path, media_type, still)
        if self._set.playlist.replace_item(prompt_id, path, media_type, still):
            if self._set.current_prompt_id() == prompt_id:
                self._levels.back_to_the_top()
                self._frame_on_funestra = None
                self._send(f"{SHOW_FRAME} {path}")
                self._take_the_whole_pace_unless_being_made()
            self._hand_over()
        elif upgraded is not None and self._set.passes(upgraded) and self._set.playlist.add(upgraded):
            # Kept out of an enhanced-only pass until now, being unenhanced; the
            # better version is exactly what that pass plays, so in it goes.
            self._hand_over()
        self._publish()

    def _enhance_current(self) -> None:
        """Ask the gallery for a better version of the item on screen, if it
        wants one, and first — locking a slide is how that is asked for here
        too."""
        current = self._set.playlist.current()
        if self._actions.enhance is None or current is None or current.is_live:
            return
        prompt_id = current.prompt_id
        if prompt_id is None:
            return
        if self._actions.enhance(prompt_id):
            self._set.note_enhancement_asked(prompt_id)
            self._publish()

    # --- what is being made ------------------------------------------------

    def note_generating(self, prompt_id: str, frame: bytes) -> None:
        if self._set.playlist.update_live(prompt_id, frame):
            self._show_what_is_being_made()
        elif (self._set.first_offer_of(prompt_id) and self._frames.write(prompt_id, frame)
              and self._set.join_live(prompt_id, frame)):
            self._hand_over()

    def note_in_flight(self, prompt_ids) -> None:
        gone = [prompt_id for prompt_id in self._set.live_ids()
                if prompt_id not in prompt_ids]
        if not gone:
            return
        for prompt_id in gone:
            self._set.playlist.drop(prompt_id)
            self._set.forget_id(prompt_id)
        if self._set.playlist.is_empty():
            self.close()
        else:
            self._hand_over(land=True)
        for prompt_id in gone:
            self._frames.forget(prompt_id)

    def note_enhancing(self, statuses: dict, frames=None) -> None:
        self._set.note_enhancing(statuses, frames)
        self._show_what_is_being_made()
        self._take_the_whole_pace_unless_being_made()
        self._publish()

    def _take_the_whole_pace_unless_being_made(self) -> None:
        current = self._set.playlist.current()
        if self._held_short and current is not None and not self._set.being_made(current):
            self._send(f"{HOLD_PICTURE} 0")
            self._held_short = False

    def lead_with_what_is_being_made(self) -> None:
        if not self.locked and self._set.lead_with_what_is_being_made():
            self._hand_over(land=True)
            self._publish()

    def follow_what_is_being_made(self) -> None:
        """Opened over a run being made: lead with it, and hold the Funestra on it
        until it lands as the file it is frames of."""
        self._set.lead_with_what_is_being_made()
        self._following = self._set.current_prompt_id()
        self._hand_over(land=True)
        self._publish()

    def osr2_drive_target(self):
        """What the one device switch follows here: the clip on screen, where this
        app drives the OSR2 -- its own window -- and nothing on a session's
        Funestra, where the OSR2 is the Main Funestra's alone."""
        player = self.shown.player
        return None if player is None else drive_target_for(self._clip_on_screen(), player)

    def video_on_screen(self) -> str | None:
        """The clip on screen, by id, where this app plays it."""
        if self.shown.player is None or self._clip_on_screen() is None:
            return None
        return self._set.current_prompt_id()

    def _clip_on_screen(self) -> str | None:
        current = self._set.playlist.current()
        if current is None or current.is_live or self._frame_on_funestra is not None:
            return None
        versions = self._levels.levels(base=self._current_base())
        shown = versions[self._levels.index] if self._levels.stepping and versions else current
        return str(shown.path) if shown.media_type == MediaType.VIDEO else None

    # --- the room's and a speaker's hands on the slideshow --------------------

    def set_paused(self, paused: bool) -> None:
        """The room's OmniPause.  A session freezes its own Funestras through their
        paused flag; the window freezes the one it holds."""
        self.shown.room_paused(paused)

    def pause_for_request(self, paused: bool, note: str = "") -> None:
        self._request_holds_it = paused
        self._tell_the_keep()
        self.shown.dictating(note if paused else "")

    def note_request(self, message: str, request=None, *, working: bool = False,
                     kind: str = NOTICE) -> None:
        self.shown.request_line(message, request, working=working, kind=kind)

    def note_voice_command(self, message: str, *, kind: str = NOTICE) -> None:
        self.shown.flash(message, kind=kind, ms=2500, mark=HEARD_MARK)

    def note_voice_run(self, prompt_id, message: str, *, kind: str = NOTICE) -> None:
        if prompt_id is not None:
            self._set.note_enhancement_asked(prompt_id)
            self._publish()
        self.note_voice_command(message, kind=kind)

    def _flash(self, message: str, *, kind: str = NOTICE, mark: str = "") -> None:
        self.shown.flash(message, kind=kind, mark=mark)

    def release_media(self, paths) -> None:
        """Let go of any of *paths* on screen — a file about to be moved.

        The Funestra is what holds it open, so the way to let go is to move on;
        it lands back on the file only if it is the last one this slideshow has.
        """
        if not self._showing or not any(str(path) == self._showing for path in paths):
            return
        self._leave_the_versions()
        if len(self._set.playlist) > 1:
            self._send(NEXT)
            return
        self._refusal_checked = True  # nothing up because it was let go, not because it would not open
        self._send(LET_GO)

    # --- picking a slideshow back up, and giving it back --------------------

    def state(self) -> SlideshowState:
        """Where this slideshow is, in the terms a later one can be opened at."""
        return self._set.state(locked=self.locked, level_index=self._levels.index)

    def resume(self, state: SlideshowState, *, opened_on_it: bool = False) -> bool:
        """Open where a closed slideshow left off rather than at the top of a fresh
        pass.  Returns whether the place carried."""
        if not self._set.resume(state, lead=not opened_on_it):
            return False
        self._hand_over(land=not opened_on_it)
        if state.level_index and self._set.current_prompt_id() == state.current:
            self.slideshow_step_version(state.level_index)
        if state.locked:
            self._lock(True)
        return True

    def whole_set(self) -> list[Slide]:
        return self._set.whole_set()

    @property
    def filters(self) -> SlideshowFilters:
        return self._set.filters

    def take_up(self, filters: SlideshowFilters, *, keep_the_slide: bool = False) -> None:
        self._set.take_up(filters, keep_the_slide=keep_the_slide)

    def is_showing(self) -> bool:
        """Whether this slideshow still holds its side."""
        return self._open

    def close(self) -> None:
        """Give the side back, handing the gallery the slide that was on it.

        The panel goes with it, so the session draws its own again; the Funestra
        keeps playing this list until the session hands it its own, which is
        what leaving origenerator mode does.
        """
        if not self._open:
            return
        self._open = False
        slide = self._set.playlist.current()
        self._timer.stop()
        self.shown.gone()
        self._frames.forget_all()
        self.closed.emit()
        if slide is not None:
            self.open_requested.emit(slide[2])


class OnASessionsFunestra:
    """Where a slideshow on one of a session's Funestras is seen: the panel it
    publishes for the session to draw over that Funestra, and the gallery's caption,
    which is on screen beside the Funestras, for the lines it says.  The session
    pauses its Funestras itself, and drives the OSR2 from its Main Funestra."""

    player = None

    def __init__(self, slideshow, side: str, channel, say=None) -> None:
        self._slideshow = slideshow
        self._side = side
        self._channel = channel
        self._say = say
        self._published = ""

    def panel_changed(self) -> None:
        model = slideshow_hud_model(self._side, self._slideshow, hosted=True, own_window=False)
        text = hud_text(model) if model is not None else ""
        if text != self._published and publish_whole(self._channel.hud_file, text):
            self._published = text

    def flash(self, text: str, *, kind: str = NOTICE, ms: int = 0, mark: str = "") -> None:
        if self._say is not None:
            self._say(text, mark=mark)

    def request_line(self, message: str, request=None, *, working: bool = False,
                     kind: str = NOTICE) -> None:
        self.flash(message, kind=kind, mark=HEARD_MARK)

    def dictating(self, note: str) -> None:
        if note:
            self.flash(note, mark=HEARD_MARK)

    def room_paused(self, paused: bool) -> None:
        pass

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        pass

    def gone(self) -> None:
        publish_whole(self._channel.hud_file, "",
                      attempts=round(READER_HOLD_BUDGET_S / _RETRY_SPACING_S),
                      delay_s=_RETRY_SPACING_S)

