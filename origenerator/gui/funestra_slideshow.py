from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

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
from funestra.hud_title import SHUFFLE_LABEL
from funestra.loop_cycle import LOCK, SEED
from funestra.on_screen_history import OnScreenHistory
from funestra.playlist import PlaylistItem
from funestra.status import parse_status
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator.gui.funestra_transport import FunestraTransport
from origenerator.gui.message import HEARD_MARK, INFO, WARNING
from origenerator.gui.on_a_sessions_funestra import OnASessionsFunestra
from origenerator.gui.slideshow_pace import STEP_S as PACE_STEP_S
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_pass import playlist_item, rotated_onto, slide_item
from origenerator.gui.slideshow_playing import NO_HOSTING, Hosting, Playing, Seat
from origenerator.gui.slideshow_set import (
    SetDeal,
    SlideshowSet,
    item_note,
    looping_note,
    narrow_to_actions,
    narrow_to_the_action_on_screen,
)
from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.gui.version_stepper import VersionStepper
from origenerator.media import MediaType
from origenerator.osr2_driver import drive_target_for
from origenerator.slideshow import Slide, SlideshowFilters, SlideshowState

logger = logging.getLogger(__name__)

_POLL_MS = 200


class FunestraSlideshow(QObject):
    open_requested = pyqtSignal(str)
    closed = pyqtSignal()
    media_changed = pyqtSignal()

    def __init__(self, playing: Playing, seat: Seat, hosting: Hosting = NO_HOSTING, parent=None):
        super().__init__(parent)
        start, versions, opening = playing.start, playing.versions, playing.opening
        self._clock = hosting.clock or time.monotonic
        self._on_screen = OnScreenHistory()
        self._shape, self._frames, self.channel = seat.shape, seat.frames, seat.channel
        self._actions = playing.actions if playing.actions is not None else SlideshowActions()
        self.shown = hosting.shown if hosting.shown is not None else OnASessionsFunestra(
            self, seat.shape, seat.channel, hosting.say, actions=self._actions)
        self._scripts_on_opening = opening.scripts if opening is not None else {}
        self._request_holds_it = False
        self._held_short = False
        self._frame_on_funestra: Path | None = None
        self._pace = hosting.pace if hosting.pace is not None else SlideshowPace(parent=self)
        self._pace.changed.connect(self._on_pace_changed)
        self._take_set(playing)
        self._open = True
        self._showing = ""
        def at_defaults() -> bool:
            at_base = self._actions.at_base
            return (not self.locked and self._set.filters == SlideshowFilters()
                    and self._set.order_label == SHUFFLE_LABEL
                    and (at_base is None or at_base(self)))

        self.transport = FunestraTransport(send=self._send, publish=self._publish,
                                           at_defaults=at_defaults)
        self._funestra_locked = False
        self._locked = False
        self._keep_told: bool | None = None
        self._gesture_owed = False
        self._refusal_checked = False
        self._loads_seen: str | None = None
        self._versions_stepper = VersionStepper()
        self._versions_stepper.arm(versions or {})
        opened_on_a_slide = start is not None
        if opened_on_a_slide:
            self._showing = self._funestra_status().video
        self._publish()
        self._hand_over(land=opened_on_a_slide)
        QTimer.singleShot(0, self._look_for_scripts_from_now_on)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        self.tick()

    def _look_for_scripts_from_now_on(self) -> None:
        self._scripts_on_opening = {}

    def _take_set(self, playing: Playing) -> None:
        self._following = None
        self._set = SlideshowSet(playing.items, actions=self._actions,
                                 deal=SetDeal(shuffle=playing.shuffle, start=playing.start, opening=playing.opening),
                                 hud=playing.hud, on_pass_change=self._pass_changed)

    def play(self, playing: Playing) -> None:
        if playing.actions is not None:
            self._actions = playing.actions
        self._unlock()
        self._take_set(replace(playing, opening=None))
        self._versions_stepper.arm(playing.versions or {})
        self._hand_over(land=True)
        self._publish()

    def _hand_over(self, *, land: bool = False) -> None:
        current = self._set.playlist.current()
        rotated = rotated_onto(self._set.playlist.in_play_order(), current)
        self.channel.write_playlist([self._funestra_item(item) for item in rotated])
        lands = land and current is not None and self._file_of(current) != self._showing
        if lands:
            self._versions_stepper.restart()
        self._tell_the_pace()
        self._tell_the_keep()
        if lands:
            self._send(play_file(self._funestra_item(current)))
        self._send(RELOAD_PLAYLIST)

    def _tell_the_pace(self) -> None:
        self._send(f"{SET_PACE} {self._funestra_pace()}")
        self._hold_what_is_being_made_for_half()

    def _funestra_pace(self) -> int:
        return self._versions_stepper.pace(self._pace.seconds)

    def _tell_the_keep(self) -> None:
        keeps = self._keeps()
        if keeps != self._keep_told:
            self._keep_told = keeps
            self._send(LOCK_ON if keeps else LOCK_OFF)

    def _keeps(self) -> bool:
        return self._locked or self._request_holds_it or self._on_the_run()

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
        return slide_item(slide, self._versions_stepper.points_of_interest(self._file_of(slide)),
                          scripts=self._scripts_on_opening)

    def _send(self, verb: str) -> None:
        if not self.channel.send(verb):
            logger.warning("Dropped %s for the %s Funestra (command file locked)",
                           verb, self._shape)

    @property
    def dwell_s(self) -> int:
        return self._pace.seconds

    def step_dwell(self, steps: int) -> None:
        self._pace.step(steps * PACE_STEP_S)

    def press_the_queue(self, verb: str, payload: str) -> None:
        self.shown.press_the_queue(verb, payload)

    def _on_pace_changed(self, _seconds: int) -> None:
        self._tell_the_pace()
        self._publish()

    def _pass_changed(self, kept: bool) -> None:
        if self._set.loop is not None:
            self._unlock()
        self._hand_over(land=not kept)
        self._publish()

    def tick(self) -> None:
        if not self._open:
            return
        fields = self.channel.status()
        if fields:
            self._follow_the_funestra(fields)
        self._publish()

    def _follow_the_funestra(self, fields: dict) -> None:
        status = parse_status(fields)
        self.transport.heard(status, fields)
        self._funestra_locked = status.locked
        self._on_screen.observe(status.video, now=self._clock())
        if status.video and status.video != self._showing:
            self._showing = status.video
            self._follow(status.video)
            self._held_short = False
            self._hold_what_is_being_made_for_half()
            self._frame_on_funestra = None
            self._show_what_is_being_made()
        self._step_past_a_file_that_would_not_open(fields, status)
        self._tell_the_keep()
        self._give_the_lock_its_gesture()

    def _hold_what_is_being_made_for_half(self) -> None:
        current, pace = self._set.playlist.current(), self._funestra_pace()
        held_for = self._set.pace_for(current, pace) if current is not None else pace
        if held_for < pace and not self._keeps():
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
        logger.warning("The %s Funestra would not open a file; stepping past it", self._shape)
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

    def set_versions(self, versions_by_path: dict) -> None:
        if self._versions_stepper.arm(versions_by_path):
            self._hand_over()
        self._publish()

    def add_versions(self, versions_by_path: dict) -> None:
        if self._versions_stepper.add(versions_by_path):
            self._hand_over()
        self._publish()

    @property
    def has_other_versions(self) -> bool:
        return len(self._versions_stepper.versions(base=self._current_base())) > 1

    def slideshow_step_version(self, delta: int) -> None:
        comparing = self._versions_stepper.stepping
        version = self._versions_stepper.step(delta, base=self._current_base())
        if version is None:
            return
        if not comparing:
            self._tell_the_pace()
        self._send(play_file(playlist_item(version.path, version.media_type,
                                           version.points_of_interest)))
        self.media_changed.emit()

    def _leave_the_versions(self) -> None:
        stepped = self._versions_stepper.stepping
        self._versions_stepper.restart()
        if stepped:
            self._hand_over()

    def _current_base(self) -> str:
        item = self._set.playlist.current()
        return "" if item is None else self._file_of(item)

    def _follow(self, video: str) -> None:
        showing = self._item_showing(video)
        if showing is None:
            return
        index, item = showing
        if item is not self._set.playlist.current():
            self._versions_stepper.restart()
        self._set.playlist.jump_to(index)
        self.media_changed.emit()

    def _item_showing(self, video: str):
        return next(((index, item) for index, item in enumerate(self._set.playlist.items)
                     if video and self._file_of(item) == video), None)

    def _publish(self) -> None:
        self.shown.hud_changed()

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def locked_on(self) -> str | None:
        return self._set.current_prompt_id() if self.locked else None

    def slideshow_step(self, delta: int, *, verb: str | None = None) -> None:
        self._unlock()
        if delta > 0:
            self._set.end_a_loop_of_one()
        self._leave_the_versions()
        self._send(verb or (NEXT if delta > 0 else PREV))

    def slideshow_toggle_lock(self) -> None:
        self.set_locked(not self.locked)

    def set_locked(self, locked: bool) -> bool:
        if locked == self.locked:
            return False
        self._lock(locked)
        if locked:
            self._gesture_owed = True
            self._give_the_lock_its_gesture()
        return True

    def _give_the_lock_its_gesture(self) -> None:
        if not (self._gesture_owed and self._funestra_locked):
            return
        self._gesture_owed = False
        self.favorite()
        self._enhance_current()
        prompt_id = self._set.current_prompt_id()
        if self._actions.lock is not None and prompt_id is not None:
            self._actions.lock(prompt_id)

    def _lock(self, on: bool) -> None:
        self._locked = on
        if not on:
            self._gesture_owed = False
        self._tell_the_keep()
        self._publish()

    def _unlock(self) -> None:
        if self.locked:
            self._lock(False)

    def slideshow_cull(self) -> None:
        """Windows will not move a file a process still has open, so the Funestra is told to drop a condemned item before the generation is."""
        item = self._set.playlist.current()
        if item is None:
            return
        self._leave_the_versions()
        self._lock(False)
        if self._set.unfavorite_current(self._actions.unfavorite):
            self._flash("Unfavorited")
            self._send(NEXT)
            return
        self._send(TRASH)
        self._showing = ""
        self._set.forget(item)
        self._set.playlist.remove_current()
        self._frames.forget(item.prompt_id)
        if self._set.playlist.is_empty():
            self.close()
        elif self._set.end_a_loop_of_one():
            self._lock_what_the_cull_left()
        else:
            self._hand_over()
        if item.prompt_id is not None and not item.is_live and self._actions.delete is not None:
            self._condemn(item.prompt_id)

    def _lock_what_the_cull_left(self) -> None:
        self._lock(True)
        self._flash("Locked")

    def _condemn(self, prompt_id: str) -> None:
        try:
            self._actions.delete(prompt_id)
        except OSError:
            logger.exception("The %s Funestra kept a condemned generation open", self._shape)
            self._flash("couldn't delete that one — the Funestra still has it open",
                        kind=WARNING, mark="trash")

    def cull(self) -> None:
        self.slideshow_cull()

    def favorite(self) -> bool:
        prompt_id = self._set.current_prompt_id()
        if self._actions.favorite is None or prompt_id is None:
            return False
        self._actions.favorite(prompt_id)
        self._set.favorite_ids.add(prompt_id)
        return True

    def slideshow_reset(self) -> None:
        if self._actions.reset is not None:
            self._actions.reset(self)
            return
        self.reset_in_place()

    def slideshow_order(self, *, latest: bool) -> None:
        if self._actions.reorder is not None:
            self._actions.reorder(self, latest)

    def reset_in_place(self) -> None:
        self._lock(False)
        if self._set.drop_the_filters():
            return
        self._set.playlist.restart()
        self._hand_over(land=True)

    def retune(self, items, *, enhanced_ids=None) -> None:
        self._unlock()
        self._set.retune(items, enhanced_ids=enhanced_ids)

    def reorder(self, items, *, latest: bool, enhanced_ids=(),
                keep_slide: bool = False) -> None:
        self._unlock()
        self._set.reorder(items, latest=latest, enhanced_ids=enhanced_ids,
                          keep_slide=keep_slide)

    def show_item(self, path, *, lock: bool = False) -> None:
        slide = self._set.slide_for_path(path)
        if slide is None:
            return
        self._jump_to(slide)
        if lock:
            self.set_locked(True)

    def show_locked(self, path) -> None:
        self.show_item(path, lock=True)

    def _jump_to(self, slide) -> None:
        self._unlock()
        self._set.jump_to(slide)
        self._leave_the_versions()
        self._send(play_file(self._funestra_item(slide)))
        self._publish()

    def hud_map(self):
        return self._set.map()

    def pass_size(self) -> int:
        return len(self._set.playlist)

    def slideshow_loop(self, axis: str) -> None:
        if not axis:
            if self._set.end_loop(self._browse_it_all):
                self._flash("Loop off")
            return
        if self._set.start_loop(axis):
            self._flash(looping_note(self._set))
        else:
            self._lock_instead_of_looping()

    def _lock_instead_of_looping(self) -> None:
        self._set.end_loop()
        self.set_locked(True)
        self._flash("Locked")

    def _browse_it_all(self) -> bool:
        if self._actions.browse_all is None:
            return False
        return bool(self._actions.browse_all(self))

    def slideshow_loop_cycle(self) -> None:
        looping = self._set.loop is not None
        stop = self._set.step_loop(self.locked, self._browse_it_all)
        if stop == LOCK:
            self.set_locked(True)
            self._flash("Locked")
        elif stop:
            self._flash(looping_note(self._set))
        else:
            self._unlock()
            self._flash("Loop off" if looping else "Unlocked")

    def slideshow_more_seeds(self) -> None:
        if self._set.more_seeds():
            self._flash("More seeds")
        else:
            self._flash("Widening net failed", kind=WARNING)

    def slideshow_filter(self, query: str) -> None:
        row = self._set.configuration_row(query)
        if row is not None:
            if row is not self._set.playlist.current():
                self._jump_to(row)
            self.slideshow_loop(SEED)
            return
        said, narrowed = narrow_to_actions(self._set, query)
        self._flash(said, kind=INFO if narrowed else WARNING)

    def slideshow_filter_to_the_action_on_screen(self) -> None:
        said, narrowed = narrow_to_the_action_on_screen(self._set)
        self._flash(said, kind=INFO if narrowed else WARNING)

    def slideshow_nav(self, direction: str) -> None:
        target = self._set.nav_target(direction)
        if target is None:
            self._flash("Nothing that way", kind=WARNING)
            return
        self._jump_to(target)

    @property
    def hud_prompt_id(self) -> str:
        return self._set.current_prompt_id() or ""

    @property
    def hud_is_favorite(self) -> bool:
        return self._set.is_favorite

    @property
    def hud_item_note(self) -> str:
        return item_note(self._set, versions=self._versions_stepper.versions(base=self._current_base()),
                         version_index=self._versions_stepper.index)

    @property
    def hud_favorites_filter(self) -> bool:
        return self._set.filters.favorites

    @property
    def hud_enhanced_mode(self) -> bool:
        return self._set.filters.enhanced

    @property
    def hud_action_filter(self) -> str:
        return self._set.filters.action

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
        return self._set.current_prompt_id()

    def back_to_what_was_said_over(self, said_at: float | None) -> str | None:
        said_over = self._said_over(said_at)
        if said_over is None:
            return self.voice_target()
        if said_over is not self._set.playlist.current():
            self._jump_to(said_over)
        return said_over.prompt_id

    def _said_over(self, said_at: float | None):
        showing = (self._item_showing(self._on_screen.path_at(said_at))
                   if said_at is not None else None)
        return showing[1] if showing else None

    def holds(self, prompt_id: str) -> bool:
        return self._set.playlist.holds(prompt_id)

    def note_added(self, slide: Slide, *, favorite: bool = False, enhanced: bool = False) -> None:
        prompt_id = slide.prompt_id
        if favorite:
            self._set.favorite_ids.add(prompt_id)
        if enhanced:
            self._set.enhanced_ids.add(prompt_id)
        self._set.remember(slide)
        if self._set.playlist.replace_live(prompt_id, slide.path, slide.media_type, slide.still):
            self._hand_over(land=True)
            self._frames.forget(prompt_id)
        elif self._set.passes(slide) and self._set.playlist.add(slide):
            self._hand_over()

    def note_enhanced(self, prompt_id: str, path, media_type: str = MediaType.IMAGE,
                      still=None) -> None:
        self._set.note_enhancement_landed(prompt_id)
        upgraded = self._set.upgrade(prompt_id, path, media_type, still)
        if self._set.playlist.replace_item(prompt_id, path, media_type, still):
            if self._set.current_prompt_id() == prompt_id:
                self._versions_stepper.back_to_the_top()
                self._frame_on_funestra = None
                self._send(f"{SHOW_FRAME} {path}")
                self._take_the_whole_pace_unless_being_made()
            self._hand_over()
        elif upgraded is not None and self._set.passes(upgraded) and self._set.playlist.add(upgraded):
            self._hand_over()
        self._publish()

    def _enhance_current(self) -> None:
        current = self._set.playlist.current()
        if self._actions.enhance is None or current is None or current.is_live:
            return
        prompt_id = current.prompt_id
        if prompt_id is None:
            return
        if self._actions.enhance(prompt_id):
            self._set.note_enhancement_asked(prompt_id)
            self._publish()

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
        self._set.lead_with_what_is_being_made()
        self._following = self._set.current_prompt_id()
        self._hand_over(land=True)
        self._publish()

    def osr2_drive_target(self):
        player = self.shown.player
        return None if player is None else drive_target_for(self._video_on_screen(), player)

    def video_on_screen(self) -> str | None:
        if self.shown.player is None or self._video_on_screen() is None:
            return None
        return self._set.current_prompt_id()

    def _video_on_screen(self) -> str | None:
        current = self._set.playlist.current()
        if current is None or current.is_live or self._frame_on_funestra is not None:
            return None
        versions = self._versions_stepper.versions(base=self._current_base())
        shown = versions[self._versions_stepper.index] if self._versions_stepper.stepping and versions else current
        return str(shown.path) if shown.media_type == MediaType.VIDEO else None

    def set_paused(self, paused: bool) -> None:
        self.shown.room_paused(paused)

    def pause_for_request(self, paused: bool, note: str = "") -> None:
        self._request_holds_it = paused
        self._tell_the_keep()
        self.shown.dictating(note if paused else "")

    def note_request(self, message: str, request=None, *, working: bool = False,
                     kind: str = INFO) -> None:
        self.shown.request_line(message, request, working=working, kind=kind)

    def note_voice_command(self, message: str, *, kind: str = INFO) -> None:
        self.shown.flash(message, kind=kind, ms=2500, mark=HEARD_MARK)

    def note_voice_run(self, prompt_id, message: str, *, kind: str = INFO) -> None:
        if prompt_id is not None:
            self._set.note_enhancement_asked(prompt_id)
            self._publish()
        self.note_voice_command(message, kind=kind)

    def _flash(self, message: str, *, kind: str = INFO, mark: str = "") -> None:
        self.shown.flash(message, kind=kind, mark=mark)

    def release_media(self, paths) -> None:
        if not self._showing or not any(str(path) == self._showing for path in paths):
            return
        self._leave_the_versions()
        if len(self._set.playlist) > 1:
            self._send(NEXT)
            return
        self._refusal_checked = True
        self._send(LET_GO)

    def state(self) -> SlideshowState:
        return self._set.state(locked=self.locked, version_index=self._versions_stepper.index)

    def resume(self, state: SlideshowState, *, opened_on_it: bool = False) -> bool:
        if not self._set.resume(state, lead=not opened_on_it):
            return False
        self._hand_over(land=not opened_on_it)
        if state.version_index and self._set.current_prompt_id() == state.current:
            self.slideshow_step_version(state.version_index)
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
        return self._open

    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        if self._versions_stepper.stepping:
            self._send(f"{SET_PACE} {self._pace.seconds}")
        if self._keep_told and not self._locked:
            self._send(LOCK_OFF)
        slide = self._set.playlist.current()
        self._timer.stop()
        self.shown.gone()
        self._frames.forget_all()
        self.closed.emit()
        if slide is not None:
            self.open_requested.emit(slide[2])
