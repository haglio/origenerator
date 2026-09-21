"""One show, handed to a session's player instead of drawn in a window.

Inside a Fun Time session the satellite players are what shows the pictures.
The session hands this app each player's channel — the list it plays, the verbs
it drains, the status it publishes, the panel it draws — and a show on that
side becomes exactly that: a playlist written for the player, a few verbs, and
the panel this app publishes for the session to put on it.  The player owns
what is on screen from there: it holds a picture for the pace, plays a clip to
its end and rolls onto the next, repeats the one it is locked onto, and freezes
with the room.

So this is a show with no surface of its own.  The set, the pass and the two
switches are the same ones a window show keeps
(:class:`~origenerator.gui.show_set.ShowSet`), it answers every word and button
the way the window does (:class:`~origenerator.gui.show_host.ShowHost`), and
what is on screen is read back from the player rather than rendered here.

Three things a window show has are the player's to learn next: the frames of a
generation still being made, the queue plate in the corner, and the lines this
app flashes over a show — which go to the gallery's own caption instead, where
the speaker can still see them.
"""
from __future__ import annotations

import logging
from pathlib import Path

from player_core.file_channel import append_command, publish_whole
from player_core.player_verbs import (
    LOCK_OFF,
    LOCK_ON,
    NEXT,
    PREV,
    RELOAD_PLAYLIST,
    SET_PACE,
    TRASH,
    play_file,
)
from player_core.playlist import PlaylistItem, write_playlist
from player_core.satellite_hud import hud_text
from player_core.status import parse_status
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator.gui.level_stepper import LevelStepper
from origenerator.gui.notice_overlay import NOTICE, WARNING
from origenerator.gui.show_hud import show_hud_model
from origenerator.gui.show_map import SEED_AXIS
from origenerator.gui.show_set import (
    LOOP_IS_A_LOCK,
    LOOP_OFF,
    ShowSet,
    looping_note,
    narrow_to_acts,
)
from origenerator.gui.show_wiring import ShowActions
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.media import MediaType
from origenerator.slideshow import ShowState, Slide

logger = logging.getLogger(__name__)

# How often the player is asked what it is showing.  It publishes its status
# five times a second; this is near enough that the map follows the slide
# rather than trailing it, and idle ticks cost a read and a comparison.
_POLL_MS = 200


class PlayerShow(QObject):
    """A show driving one of the session's players."""

    # Enter on an item, and a lock: the gallery lands on that generation.  Only
    # the lock reaches it here — a player has no Enter to press.
    open_requested = pyqtSignal(str)
    # The show is over: the side has nothing of this app's on it now.
    closed = pyqtSignal()
    # A different item is on screen.
    media_changed = pyqtSignal()

    def __init__(self, items, *, side: str, channel, actions=None, hud=None,
                 pace=None, image_dwell_ms=None, start=None, shuffle=None,
                 say=None, parent=None):
        super().__init__(parent)
        self._side = side
        self.channel = channel
        # What a press here asks the gallery to do on its behalf — the half of
        # each gesture that lands on the generation rather than on the slide.
        self._actions = actions if actions is not None else ShowActions()
        # Where a line about this show goes.  A window show flashes it in its
        # own corner; this one has none, so it goes to the gallery's caption,
        # which is on screen beside the players in a session.
        self._say = say
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        self._pace.changed.connect(self._on_pace_changed)
        self._take_set(items, image_dwell_ms=image_dwell_ms, start=start,
                       shuffle=shuffle, hud=hud)
        self._open = True
        # What the player last said it was showing, and whether it has locked
        # it: the player's answer, not this app's — a picture that has moved on
        # by itself is news that arrives this way and no other.
        self._showing = ""
        self._locked = False
        self._published = ""
        self._levels = LevelStepper()
        # Locking a slide is also how you ask for it: a lock asks for a better
        # version of what is on screen, unless the gallery wired none.
        self._enhancing: set[str] = set()  # prompt_ids with a run in flight
        opened_on_a_slide = start is not None
        if opened_on_a_slide:
            self._showing = self._player_status().video
        self._hand_over(land=opened_on_a_slide)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        self.tick()

    # --- handing the player what to play ------------------------------------

    def _take_set(self, items, *, image_dwell_ms, start, shuffle, hud) -> None:
        if image_dwell_ms is None:
            image_dwell_ms = self._pace.dwell_ms
        self._dwell_s = image_dwell_ms // 1000
        self._set = ShowSet(items, image_dwell_ms=image_dwell_ms, shuffle=shuffle,
                            start=start, hud=hud, on_pass_change=self._pass_changed,
                            neighbors=self._actions.neighbors, widen=self._actions.widen,
                            acts=self._actions.acts)

    def play(self, items, *, image_dwell_ms=None, start=None, shuffle=None,
             hud=None) -> None:
        self._take_set(items, image_dwell_ms=image_dwell_ms, start=start,
                       shuffle=shuffle, hud=hud)
        self._unlock()
        self._hand_over(land=True)
        self._publish()

    def _hand_over(self, *, land: bool = False) -> None:
        """Give the player this pass to play, written rotated onto the slide
        this show stands on: a player showing nothing of it opens there, and a
        reload keeps the item a player is on wherever that item survived."""
        items = [item for item in self._set.playlist.in_play_order() if not item.is_live]
        current = self._set.playlist.current()
        rotated = _rotated_onto(items, current)
        write_playlist(self.channel.playlist,
                       [_playlist_item(item) for item in rotated])
        if land and current is not None and str(current.path) != self._showing:
            # Before the reload, which then keeps it: after, it would load twice.
            self._send(play_file(_playlist_item(current)))
        self._send(RELOAD_PLAYLIST)
        self._send(f"{SET_PACE} {self._dwell_s}")

    def _send(self, verb: str) -> None:
        if not append_command(self.channel.command_file, verb):
            logger.warning("Dropped %s for the %s player (command file locked)",
                           verb, self._side)

    # --- the pace ----------------------------------------------------------

    @property
    def dwell_s(self) -> int:
        """The seconds an unlocked picture holds the player's screen."""
        return self._dwell_s

    def set_dwell_s(self, seconds: int) -> None:
        """Take a new pace, and hand it on: the number is app-wide, so a pace
        set over this show is what the next one opens at."""
        self._pace.set_seconds(seconds)  # fires _on_pace_changed if it moved
        self._apply_dwell(self._pace.seconds)  # and take it even if it didn't

    def _on_pace_changed(self, seconds: int) -> None:
        self._apply_dwell(seconds)

    def _apply_dwell(self, seconds: int) -> None:
        """Tell the player how long to hold a picture, when the number moved.

        The pace is the player's to keep from there: it holds the frame that
        long and then ends the file, which is how a picture moves on at all.
        """
        seconds = max(0, int(seconds))
        if seconds == self._dwell_s:
            return
        self._dwell_s = seconds
        self._set.playlist.image_dwell_ms = seconds * 1000
        self._send(f"{SET_PACE} {seconds}")

    def _pass_changed(self, kept: bool) -> None:
        """A fresh pass was dealt: the player is playing the old one, so it is
        handed the new one — keeping the slide on screen when the pass kept it,
        and sent to this show's own when it did not.  The panel follows at
        once, so a loop lights its button on the press rather than a tick
        later."""
        if self._set.loop is not None:
            self._unlock()
        self._hand_over(land=not kept)
        self._publish()

    # --- what the player says it is showing ---------------------------------

    def tick(self) -> None:
        """Read the player's status, follow it, and publish the panel."""
        status = self._player_status()
        self._locked = status.locked
        if status.video and status.video != self._showing:
            self._showing = status.video
            self._follow(status.video)
        self._publish()

    def _player_status(self):
        return parse_status(_read_fields(self.channel.status_file))

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm the versions button and the shifted step keys for this set.

        ``levels_by_path`` maps the file the set shows an item under to that
        item's versions, newest first, as ``(path, media_type, label)`` — the
        same map a window show is armed with, from the same gallery.
        """
        self._levels.arm(levels_by_path)
        self._publish()

    @property
    def has_other_versions(self) -> bool:
        """Whether the item on screen was filed more than once — what draws
        the band's versions button live rather than faded."""
        return len(self._levels.levels(base=self._current_base())) > 1

    def show_step_version(self, delta: int) -> None:
        """Put another copy of the item on screen up: an image's enhancement
        levels, or a video's Evolver upscale and the video itself.

        An item filed once is left alone rather than paged, since the shift was
        the whole point of the press.  The player is told which file to play
        rather than asked to step its own way through them, because the place
        within the versions is held here, ahead of the status the player is
        still publishing.
        """
        level = self._levels.step(delta, base=self._current_base())
        if level is None:
            return
        self._send(play_file(PlaylistItem(Path(str(level[0])))))

    def _current_base(self) -> str:
        """The file the set lists the item on screen under — what its versions
        are keyed by."""
        item = self._set.playlist.current()
        return "" if item is None else str(item.path)

    def _follow(self, video: str) -> None:
        """Stand the pass on the item the player just moved to.

        The player walks the list by itself — a picture's pace runs out, a clip
        ends — so this is how the map, the star and every word about "this one"
        find out which item that is.
        """
        for index, item in enumerate(self._set.playlist.items):
            if str(item.path) == video:
                self._set.playlist.jump_to(index)
                self._levels.restart()  # a new item, so its own versions from the top
                self.media_changed.emit()
                return

    def _publish(self) -> None:
        """Publish this side's panel for the session to draw on the player."""
        model = show_hud_model(self._side, self, hosted=True, own_window=False)
        text = hud_text(model) if model is not None else ""
        if text != self._published and publish_whole(self.channel.hud_file, text):
            self._published = text

    # --- the transport: a button on the panel, a word, a session's hotkey ----

    @property
    def locked(self) -> bool:
        """Whether the player has locked what is on screen — its own answer,
        which is what the panel's padlock and its lock ring are drawn from."""
        return self._locked

    def show_step(self, delta: int) -> None:
        """Step the player either way.  Moving off a locked slide releases the
        lock, the way the players' own prev/next cancel a lock — and a loop
        down to the picture on screen is ended first, so what the player is
        handed to step into is the set rather than a list of one."""
        self._unlock()
        if delta > 0:
            self._set.end_a_loop_of_one()
        self._send(NEXT if delta > 0 else PREV)

    def step(self, delta: int) -> None:
        self.show_step(delta)

    def show_toggle_lock(self) -> None:
        """Lock what is on screen, or let it go — the whole of the gesture."""
        self.set_locked(not self._locked)

    def toggle_lock(self) -> None:
        self.show_toggle_lock()

    def set_locked(self, locked: bool) -> bool:
        """Lock the item on screen or let it go, saying which way rather than
        flipping; ``True`` when that moved it.

        Locking is the whole gesture it is in a window: the player repeats the
        item, and the show favorites it, asks for a better version of it, and — in
        a session — hands it to the gallery to open.
        """
        if locked == self._locked:
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
        # Held here as well as sent, so the panel lights on the press rather
        # than a tick later; the player's own status settles it either way.
        self._locked = on
        self._send(LOCK_ON if on else LOCK_OFF)
        self._publish()

    def _unlock(self) -> None:
        if self._locked:
            self._lock(False)

    def show_cull(self) -> None:
        """The players' "weird": a favorite loses its star and the player moves
        on; anything else is taken away and the player moves on.

        The player is told to drop a condemned item before the generation is:
        it is playing that very file, and Windows will not move a file a
        process still has open — the recovery bin's own retries cover the
        moment the player takes to let go.
        """
        item = self._set.playlist.current()
        if item is None:
            return
        self._lock(False)  # the locked slide is the one being culled
        if self._set.unfavorite_current(self._actions.unfavorite):
            self._note("Unfavorited")
            self._send(NEXT)
            return
        self._send(TRASH)
        # Letting go already, so the delete's own release must not ask it to
        # move on a second time and skip the item after this one as well.
        self._showing = ""
        self._set.forget(item)
        self._set.playlist.remove_current()
        if self._set.playlist.is_empty():
            # A show culled empty is over, and the side goes back to its base
            # state — which hands the player another list to move on to.
            self.close()
        elif self._set.end_a_loop_of_one():
            self._lock_what_the_cull_left()  # its pass change hands the set over
        else:
            self._hand_over()
        if item.prompt_id is not None and self._actions.delete is not None:
            self._condemn(item.prompt_id)

    def _lock_what_the_cull_left(self) -> None:
        """A row worn down to one picture plays that picture over and over,
        which is the lock — so the cull that wore it down ends the loop and
        tells the player to lock what is left.  No better version is asked
        for: nobody pressed for one."""
        self._lock(True)
        self.favorite()
        self._note("Locked")

    def _condemn(self, prompt_id: str) -> None:
        """Delete the generation, saying so where it could not be.

        A player is another process, and one with nothing else to move on to
        keeps the file open for good; that is a delete refused, not a fault to
        take the app down over.
        """
        try:
            self._actions.delete(prompt_id)
        except OSError:
            logger.exception("The %s player kept a condemned generation open", self._side)
            self._note("🗑 couldn't delete that one — the player still has it open",
                       kind=WARNING)

    def cull(self) -> None:
        self.show_cull()

    def favorite(self) -> bool:
        """Bookmark the item on screen; ``False`` when there is nothing to
        bookmark."""
        prompt_id = self._set.current_prompt_id()
        if self._actions.favorite is None or prompt_id is None:
            return False
        self._actions.favorite(prompt_id)
        self._set.favorite_ids.add(prompt_id)  # the star readout and F-mode follow it
        return True

    def show_reset(self) -> None:
        """Put the side back how it started — the region's base state, which
        the gallery owns, else this set from the top."""
        if self._actions.reset is not None:
            self._actions.reset(self)
            return
        self.reset_in_place()

    def show_order(self, *, latest: bool) -> None:
        if self._actions.reorder is not None:
            self._actions.reorder(self, latest)

    def reset_in_place(self) -> None:
        """This show's own reset: both switches dropped, the lock released, and
        the set it is already playing started over."""
        self._lock(False)
        if self._set.drop_the_switches():
            return  # the player has the fresh pass already (see _pass_changed)
        self._set.playlist.restart()
        self._hand_over(land=True)

    def retune(self, items, *, enhanced_ids=None) -> None:
        """Point this show at the region's base set instead — what a hosted
        reset does, with both switches off and a fresh pass."""
        self._unlock()
        self._set.retune(items, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=()) -> None:
        self._unlock()
        self._set.reorder(items, latest=latest, enhanced_ids=enhanced_ids)

    def show_item(self, path, *, lock: bool = False) -> None:
        """Play the item the HUD map named — a thumbnail click, the same jump
        it makes on a player's own map; *lock* keeps it there."""
        slide = self._set.slide_for_path(path)
        if slide is None:
            return
        self._jump_to(slide)
        self._lock(lock)

    def _jump_to(self, slide) -> None:
        """Stand the pass on *slide* and send the player there.

        One verb either way: the player jumps to a file already in its list
        and splices one that is not in after what it is showing — which is
        exactly where the pass put a cell it never held.  A jump that ends a
        loop re-deals the pass, and that hands the player the browse first
        (see :meth:`_pass_changed`).
        """
        self._set.jump_to(slide)
        self._send(play_file(_playlist_item(slide)))
        self._publish()

    # --- the map, and the loops along it -----------------------------------

    def hud_map(self):
        return self._set.map()

    def pass_size(self) -> int:
        return len(self._set.playlist)

    def show_loop(self, axis: str) -> None:
        """Loop the map's *axis* around the item on screen, or end the loop
        for "".  The player is handed the row or the column to play, and the
        set it was browsing when the loop ends (see :meth:`_pass_changed`)."""
        if not axis:
            if self._set.end_loop():
                self._note("Loop off")
            return
        if self._set.start_loop(axis):
            self._note(looping_note(self._set))
        else:
            self._lock_instead_of_looping()

    def _lock_instead_of_looping(self) -> None:
        """Tell the player to lock what it is showing: the answer a loop asked
        of a row of one gets on a player of its own, where the loop button of a
        group holding one clip locks that clip.  A row that size is the picture
        itself, so the press means "this one" rather than nothing; and a lock is
        not a loop, so a loop that was running is dropped."""
        self._set.end_loop()
        self.set_locked(True)
        self._note("Locked")

    def show_loop_cycle(self) -> None:
        """The loop key: seeds, then actions, then off — and the lock when
        there is nothing on either axis to loop."""
        stepped = self._set.step_loop()
        if stepped == LOOP_IS_A_LOCK:
            self.set_locked(not self._locked)
            self._note("Locked" if self._locked else "Unlocked")
        elif stepped == LOOP_OFF:
            self._note("Loop off")
        else:
            self._note(looping_note(self._set))

    def show_more_seeds(self) -> None:
        if self._set.more_seeds():
            self._note("More seeds")
        else:
            self._note("Widening net failed", kind=WARNING)

    def show_filter(self, query: str) -> None:
        """The button at the head of a map row, and the session's spoken acts.

        A configuration's row is gone to and its seeds looped, the way it was
        before the acts joined the column; an act's narrows the show to it.
        """
        row = self._set.configuration_row(query)
        if row is not None:
            if row is not self._set.playlist.current():
                self._unlock()
                self._jump_to(row)
            self.show_loop(SEED_AXIS)
            return
        said, narrowed = narrow_to_acts(self._set, query)
        self._note(said, kind=NOTICE if narrowed else WARNING)

    def show_nav(self, direction: str) -> None:
        target = self._set.nav_target(direction)
        if target is None:
            self._note("Nothing that way", kind=WARNING)
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
    def hud_favorites_filter(self) -> bool:
        return self._set.favorites_filter

    @property
    def hud_enhanced_mode(self) -> bool:
        return self._set.enhanced_mode

    @property
    def hud_act_filter(self) -> str:
        return self._set.act_filter

    @property
    def hud_order_label(self) -> str:
        return self._set.order_label

    @property
    def hud_device(self):
        """Nothing: the panel this show publishes is drawn on a session's own
        player, and the device half of it is on that session's main console."""
        return None

    def press_console(self, _action: str) -> bool:
        return False

    def toggle_favorites_filter(self) -> bool:
        return self.set_favorites_filter(not self._set.favorites_filter)

    def set_favorites_filter(self, on: bool) -> bool:
        return self._set.set_modes(favorites_filter=bool(on), enhanced=self._set.enhanced_mode)

    def toggle_enhanced_mode(self) -> bool:
        return self.set_enhanced_mode(not self._set.enhanced_mode)

    def set_enhanced_mode(self, on: bool) -> bool:
        return self._set.set_modes(favorites_filter=self._set.favorites_filter, enhanced=bool(on))

    def clear_modes(self) -> bool:
        return self._set.set_modes(favorites_filter=False, enhanced=False, act_filter="")

    def current_media_path(self) -> str:
        """The file on screen — the player's own answer, which is what the
        session's status file says about this side."""
        return self._showing

    def voice_target(self):
        """The generation a spoken order is about: the item on screen."""
        return self._set.current_prompt_id()

    # --- keeping the set current --------------------------------------------

    def holds(self, prompt_id: str) -> bool:
        return self._set.playlist.holds(prompt_id)

    def note_added(self, path, media_type: str, prompt_id: str, still=None, *,
                   favorite: bool = False, enhanced: bool = False) -> None:
        """A generation that belongs to what this show plays has landed: it
        joins the set, queued to come up next, and the player is handed the
        list again so it can reach it."""
        if favorite:
            self._set.favorite_ids.add(prompt_id)
        if enhanced:
            self._set.enhanced_ids.add(prompt_id)
        slide = Slide(path, media_type, prompt_id, still)
        self._set.remember(slide)
        if self._set.passes(slide) and self._set.playlist.add(slide):
            self._hand_over()

    def note_enhanced(self, prompt_id: str, path, media_type: str = MediaType.IMAGE,
                      still=None) -> None:
        """An enhancement of one of these items landed: the show plays the
        better version from here on, wherever that item sits in the pass."""
        self._enhancing.discard(prompt_id)
        self._set.enhanced_ids.add(prompt_id)
        upgraded = self._set.upgrade(prompt_id, path, media_type, still)
        if self._set.playlist.replace_item(prompt_id, path, media_type, still):
            self._hand_over()
        elif upgraded is not None and self._set.passes(upgraded) and self._set.playlist.add(upgraded):
            # Kept out of an enhanced-only pass until now, being unenhanced; the
            # better version is exactly what that pass plays, so in it goes.
            self._hand_over()

    def _enhance_current(self) -> None:
        """Ask the gallery for a better version of the item on screen, if it
        wants one — locking a slide is how that is asked for here too."""
        if self._actions.enhance is None:
            return
        prompt_id = self._set.current_prompt_id()
        if prompt_id is None or prompt_id in self._enhancing:
            return
        if self._actions.enhance(prompt_id):
            self._enhancing.add(prompt_id)

    # --- what a player cannot do yet ----------------------------------------
    # Each of these is a window show's, and the last step of this move is what
    # gives them to a player.  Answered rather than left off, because a show is
    # a show to everything that drives one.

    def is_live(self) -> bool:
        """Whether this show is following a generation still being made.  Never
        — a player has no way to be handed a frame yet, so a run joins this set
        when it lands (:meth:`note_added`) and not before."""
        return False

    def note_generating(self, prompt_id: str, frame: bytes) -> None:
        """A run streamed a frame.  Nothing to do with it here: a playlist
        names files, and this one has none yet."""

    def note_in_flight(self, prompt_ids) -> None:
        """Which runs are still being made — about the frames this show does
        not play, so nothing to drop."""

    def note_enhancing(self, statuses: dict) -> None:
        """How the enhancements in flight are going, for a corner this show
        has not got."""

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        """What is in flight, for the queue plate a window floats in its
        corner."""

    def osr2_drive_target(self):
        """What the one device switch would follow here.  Nothing: inside a
        session the OSR2 is the main player's alone, and the clip is the
        satellite's to play."""

    # --- the session's own hands on the show --------------------------------

    def set_paused(self, paused: bool) -> None:
        """The room's OmniPause.  The session freezes its own players through
        their paused flag, so there is nothing to do here — a frozen player
        holds the picture, and nothing advances until it is let go."""

    def pause_for_request(self, paused: bool, note: str = "") -> None:
        """Stop the advance while a request is being spoken: the pace goes to
        nought, which is how anything is kept still on a player, and back after.

        A request is about what is on screen, and a set that pages on every few
        seconds would hand the words to whatever came up next.
        """
        self._send(f"{SET_PACE} {0 if paused else self._dwell_s}")
        if note:
            self._note(note)

    def note_request(self, message: str, request=None, *, working: bool = False,
                     kind: str = NOTICE) -> None:
        self._note(message, kind=kind)

    def note_voice_command(self, message: str, *, kind: str = NOTICE) -> None:
        self._note(message, kind=kind)

    def note_voice_run(self, prompt_id, message: str, *, kind: str = NOTICE) -> None:
        if prompt_id is not None:
            self._enhancing.add(prompt_id)
        self._note(message, kind=kind)

    def _note(self, message: str, *, kind: str = NOTICE) -> None:
        """Say a line where the speaker can see it.  A window show flashes it
        over the picture; this one has no corner of its own, so it goes to the
        gallery's caption — which is on screen beside the players."""
        if self._say is not None:
            self._say(message)

    def release_media(self, paths) -> None:
        """Let go of any of *paths* on screen — a file about to be moved.

        The player is what holds it open, so the way to let go is to move on;
        it lands back on the file only if it is the last one this show has.
        """
        if self._showing and any(str(path) == self._showing for path in paths):
            self._send(NEXT)

    # --- picking a show back up, and giving it back -------------------------

    def state(self) -> ShowState:
        """Where this show is, in the terms a later one can be opened at."""
        return ShowState(
            order=tuple(self._set.playlist.order_ids()),
            current=self._set.current_prompt_id(),
            locked=self._locked,
        )

    def resume(self, state: ShowState) -> bool:
        """Open where a closed show left off rather than at the top of a fresh
        pass.  Returns whether the place carried."""
        if not self._set.playlist.resume(state.order, state.current):
            return False
        self._hand_over(land=True)
        return True

    def is_showing(self) -> bool:
        """Whether this show still holds its side."""
        return self._open

    def close(self) -> None:
        """Give the side back: nothing of this app's is on it now.

        The panel goes with it, so the session draws its own again; the player
        keeps playing this list until the session hands it its own, which is
        what leaving origenerator mode does.
        """
        if not self._open:
            return
        self._open = False
        self._timer.stop()
        publish_whole(self.channel.hud_file, "")
        self.closed.emit()


def _playlist_item(slide) -> PlaylistItem:
    return PlaylistItem(Path(str(slide.path)))


def _rotated_onto(items: list, current) -> list:
    """*items* turned so *current* leads, leaving the order otherwise alone."""
    if current is None:
        return items
    for index, item in enumerate(items):
        if item is current or (item.prompt_id is not None
                               and item.prompt_id == current.prompt_id):
            return items[index:] + items[:index]
    return items


def _read_fields(path: Path) -> dict[str, str]:
    """A player's status file as its ``key=value`` pairs — empty while it has
    published none, or while a read loses the race with its own rewrite."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    fields = {}
    for line in text.splitlines():
        key, marker, value = line.partition("=")
        if marker:
            fields[key.strip()] = value.strip()
    return fields
