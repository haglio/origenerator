"""The full-screen slideshow window -- the one way this app fills the screen with an item.

The slideshow in it is the one every Funestra runs
(:class:`~origenerator.gui.funestra_slideshow.FunestraSlideshow`), driving the
Funestra in this window's pane through the pane's channel exactly as it drives
one of a session's through its files.  What the window answers for is what
only a window has: the screen it fills, the keys pressed on it, the HUD's
place and the block at its foot, the OSR2 this app drives standalone, the lines
it flashes over the slide, and the room's pause.

What every key does, what the lock takes with it, what a filter narrows and
where a closing slideshow leaves you are `tests/test_slideshow_view.py`'s to state:
each is a test named for the claim.
"""
from __future__ import annotations

import time
from dataclasses import replace

from funestra.console import ModeHud
from funestra.file_channel import append_command
from funestra.funestra_verbs import SPEED_DOWN, SPEED_UP
from funestra.hud_placement import HudCorner
from funestra.pointer import OMNIPAUSE_TOGGLE
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from shared_ui.colors import BLACK

from origenerator import osr2 as osr2_device
from origenerator.config import FRAMES_BEING_MADE_DIR
from origenerator.console_commands import side_press, spelled_for
from origenerator.gui.console import (
    REPAINT_MS,
    post_device_action,
    slideshow_device,
)
from origenerator.gui.deferred import defer
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_pane import FunestraPane, PaneChannel
from origenerator.gui.funestra_slideshow import FunestraSlideshow
from origenerator.gui.hud_queue import QueueFoot
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.notice_overlay import HEARD_MARK, NOTICE, NoticeOverlay
from origenerator.gui.slideshow_hud import (
    COLLAPSES,
    OPENS_IN,
    THE_SLIDESHOWS_OWN,
    slideshow_hud_model,
)
from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.slideshow_buttons import PRESSES_ON_THE_QUEUE, answer

# How often the HUD is rebuilt: on its own beat, and faster while something
# on it is moving -- the drive's trace.
_REFRESH_MS = 300
_RATE_STEPS = {"speed_up": SPEED_UP, "speed_down": SPEED_DOWN}

_HUD_MOVES = {
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
}
_WASD_AS_ARROWS = {
    Qt.Key.Key_W: Qt.Key.Key_Up,
    Qt.Key.Key_A: Qt.Key.Key_Left,
    Qt.Key.Key_S: Qt.Key.Key_Down,
    Qt.Key.Key_D: Qt.Key.Key_Right,
}


class SlideshowView(QWidget):
    def __init__(self, items, *, side: str = "", start=None,
                 shuffle=None, actions=None, hud=None, engine=None, motion=None,
                 pace=None, frames=None, radio=None, volume=None,
                 clock=time.monotonic, parent=None):
        super().__init__(parent)
        # The half of each press that is a window's rather than a slideshow's: the
        # queue's three, the room's pause, the HUD's place and the OSR2 switch.
        self._actions = actions if actions is not None else SlideshowActions()
        self._motion = motion  # the gallery's app-global motion driver, or None
        self._clock = clock
        self._hud_side = side
        self._dashboard_cmd_file = None
        self._label_for = None
        self._corner = HudCorner.UPPER_LEFT
        self._minimized = False
        self._collapse = None
        self._open_in = None
        self._last_hud_model = None
        self._hud_built_at = float("-inf")
        self._hud_stale = True
        self.queue_foot = QueueFoot(
            self._actions, beside=lambda: self if self._dashboard_cmd_file is None else None)
        self._paused = False
        self._closing = False
        self.setWindowTitle("Slideshow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)  # a solid black surround under the media
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, BLACK)
        self.setPalette(palette)

        # A Fun Time notice, at the top center where Fun Time flashes the same
        # kind of line over a Funestra.
        self._note = NoticeOverlay(self)
        # What the notice reads while a spoken request pauses the slideshow, and
        # afterwards while the request said is still being worked out -- held
        # rather than flashed, and cleared by that request's own answer.
        self._request_note = ""
        self._working_note = ""
        self._working_request = None
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)

        channel = PaneChannel()
        self.slideshow = FunestraSlideshow(
            items, side=side, channel=channel, shown=self,
            frames=frames if frames is not None else FrameFiles(FRAMES_BEING_MADE_DIR / "fullscreen"),
            actions=self._actions, hud=hud, pace=pace,
            start=start, shuffle=shuffle, parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pane = FunestraPane(
            self, channel=channel, user=lambda _playback: _TheWindowsPresses(self),
            hud=self._hud_model,
            engine_for=None if engine is None else (lambda _window_id: engine),
            radio=radio, volume=volume, on_volume_moved=self._volume_moved)
        layout.addWidget(self._pane, 1)
        self.slideshow.tick()  # a Funestra that opened with the pane is followed from the first

    # --- the HUD this slideshow wears -------------------------------------

    def wear_the_hud(self, side: str, *, dashboard_cmd_file=None, label_for=None,
                     corner: HudCorner = HudCorner.UPPER_LEFT, minimized: bool = False,
                     collapse=None, open_in=None) -> None:
        """Put the Funestras' own HUD on this slideshow, drawn by the Funestra.

        *side* is whose HUD it is, which spells its verbs; *dashboard_cmd_file*
        is the session's command channel, or ``None`` standalone -- which is also
        how a press knows which of the two it is on (see :meth:`press`);
        *label_for* names the item on screen in this app's own vocabulary, and
        *collapse* is what parks the HUD in its corner where there is no
        session to ask.
        """
        self._hud_side = side
        self._dashboard_cmd_file = dashboard_cmd_file
        self._label_for = label_for
        self._corner, self._minimized = corner, minimized
        self._collapse = collapse
        self._open_in = open_in
        self.refresh_hud()

    @property
    def hud_side(self) -> str:
        return self._hud_side

    def set_hud_place(self, corner, minimized: bool) -> None:
        if (corner, minimized) == (self._corner, self._minimized):
            return
        self._corner, self._minimized = corner, minimized
        self.refresh_hud()

    def refresh_hud(self) -> None:
        """The HUD's answer may have changed under a press that redraws on
        no signal of its own: the next frame rebuilds it rather than the beat."""
        self._hud_stale = True

    def hud_changed(self) -> None:
        self.refresh_hud()

    def _hud_model(self):
        """The HUD as the Funestra draws it, rebuilt on its own beat -- and
        faster while the drive's trace is moving across it."""
        if not self._hud_side:
            return None
        now = self._clock()
        beat = REPAINT_MS if self._hud_moving() else _REFRESH_MS
        if not self._hud_stale and (now - self._hud_built_at) * 1000 < beat:
            return self._last_hud_model
        self._hud_stale = False
        self._hud_built_at = now
        model = slideshow_hud_model(self._hud_side, self.slideshow,
                                    hosted=self._dashboard_cmd_file is not None,
                                    device=self.hud_device, foot=self.queue_foot.section())
        if model is not None:
            model = replace(model, hud_corner=self._corner, hud_minimized=self._minimized)
        self._last_hud_model = model
        return model

    def _hud_moving(self) -> bool:
        drive = self._last_hud_model.drive if self._last_hud_model is not None else None
        return drive is not None and drive.live

    def item_label(self) -> str:
        """The muted line under the status: what is on screen right now, by the
        name its tile and its tab wear, not "image / ComfyUI_00123_" off the path."""
        prompt_id = self.slideshow.hud_prompt_id
        if not prompt_id or self._label_for is None:
            return ""
        try:
            return self._label_for(prompt_id) or ""
        except Exception:  # naming is decoration; it never costs the HUD
            return ""

    def press(self, command: str) -> bool:
        """Route one press on the HUD, as the Funestra hands it over: the
        block at the foot takes the pointer, what the slideshow answers for itself
        lands on it, the session's transport goes out on the dashboard channel
        — or, with no session under this slideshow, onto the slideshow as well —
        and the device's own verbs land on this window either way, the OSR2
        being this app's to drive wherever the slideshow is drawn.  A press on
        the slide asks for the pause, and a double-click there leaves.
        """
        if not self._route(command):
            return False
        self._answered()
        return True

    def _route(self, command: str) -> bool:
        verb, _, payload = command.partition("|")
        if verb in PRESSES_ON_THE_QUEUE:
            self.queue_foot.press(verb, payload)
            return True
        if verb == OMNIPAUSE_TOGGLE:
            self._press_on_the_slide()
            return True
        action, path = side_press(self._hud_side, verb, payload)
        if action in COLLAPSES or action == OPENS_IN:
            self._place_here_or_out_there(command, action, path)
            return True
        if action in THE_SLIDESHOWS_OWN:
            answer(self.slideshow, action, path)
            return True
        if self.press_console(verb):
            return True
        if action in _RATE_STEPS:
            self._pane.channel.send(_RATE_STEPS[action])
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

    def _place_here_or_out_there(self, command: str, action: str, corner: str) -> None:
        if self._dashboard_cmd_file is not None:
            append_command(self._dashboard_cmd_file, command)
        elif action == OPENS_IN:
            if self._open_in is not None and corner in HudCorner:
                self._open_in(HudCorner(corner))
        elif self._collapse is not None:
            self._collapse(COLLAPSES[action])

    def _act_here(self, action: str) -> bool:
        """A press with no session under it: the slideshow answers it itself,
        through the same answers a session's round trip would have ended at."""
        if answer(self.slideshow, action):
            self.refresh_hud()  # the readout answers the press without waiting for the beat
            return True
        return False

    # --- the queue block at the HUD's foot ---------------------------------

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        """Take what is in flight — the same list, in the same order, the Job Queue this view is covering would be showing."""
        self.queue_foot.set(items, foreign_queued)
        self.refresh_hud()

    # --- the OSR2, which this app drives standalone --------------------------

    @property
    def hud_device(self):
        """What this window is doing to the OSR2, for the one HUD to draw —
        None with no motion wired, and so no device half at all."""
        if self._motion is None:
            return None
        control = self._actions.osr2_control
        return slideshow_device(
            self._motion, device=osr2_device.device_mode(),
            trouble=osr2_device.device_trouble(),
            control=control.state() if control is not None else "",
            script=control.script if control is not None else None,
            broker_running=osr2_device.broker_running())

    def press_console(self, action: str) -> bool:
        """Take a press off the device rows of that HUD — the motion, the
        four control states, a level dragged on the readout."""
        if self._motion is None:
            return False
        return post_device_action(action, motion=self._motion,
                                  control=self._actions.osr2_control)

    @property
    def player(self):
        return self._pane

    def _volume_moved(self, volume) -> None:
        if self._actions.volume_moved is not None:
            self._actions.volume_moved(volume)

    def set_audio_muted(self, muted: bool) -> None:
        """Silence (or voice) this slideshow outright — what a hosting session does
        to a slideshow landing on a satellite region."""
        self._pane.set_audio_muted(muted)

    # --- the room's pause ----------------------------------------------------

    def room_paused(self, paused: bool) -> None:
        """Freeze or resume the Funestra here whole, with the room: a frozen
        image stops counting down its pace, a frozen clip stops, and a slide
        stepped to while frozen arrives frozen too."""
        self._paused = paused
        self._pane.set_paused(paused)

    def _press_on_the_slide(self) -> None:
        self._toggle_pause()
        if self._pane.pressing_again:
            defer(self, self.close)

    def _toggle_pause(self) -> None:
        if self._actions.omnipause is not None:
            self._actions.omnipause()
        else:
            self.room_paused(not self._paused)

    # --- the lines it flashes over the slide --------------------------------

    def flash(self, text: str, *, kind: str = NOTICE, ms: int = 1500, mark: str = "") -> None:
        """Say something for a moment, then fall back to whatever the note would
        otherwise be saying."""
        self._note.say(text, kind=kind, mark=mark)
        self._note_timer.start(ms)

    def dictating(self, note: str) -> None:
        """Hold *note* while a spoken request pauses the slideshow, or let it go for
        nothing -- the only sign, in a view with no HUDs, that the mic is
        taking a sentence."""
        if note:
            self._note_timer.stop()  # it holds, rather than fading after a beat
        self._request_note = note
        self._refresh_note()

    def request_line(self, message: str, request=None, *, working: bool = False,
                     kind: str = NOTICE) -> None:
        """Say what the spoken *request* did, where the speaker is looking.

        *working* means it has not done it yet, so the notice holds that line
        rather than flashing it, and it comes down only for the request that
        put it up -- a second request said over the first would otherwise blank
        the notice while that one is still out.
        """
        if working:
            self._working_note, self._working_request = message, request
            self._note_timer.stop()
            self._refresh_note()
            return
        if request is self._working_request:
            self._working_note, self._working_request = "", None
        self.flash(message, ms=3000, kind=kind, mark=HEARD_MARK)

    def _refresh_note(self):
        if self._request_note:
            self._note.say(self._request_note, kind=NOTICE, mark=HEARD_MARK)
        elif self._working_note:
            self._note.say(self._working_note, kind=NOTICE, mark=HEARD_MARK)
        else:
            self._note.hide()

    # --- keys -----------------------------------------------------------------

    def _move_the_hud(self, key) -> None:
        direction = _HUD_MOVES.get(key)
        if direction is not None and self._actions.move_hud is not None:
            self._actions.move_hud(direction)

    def keyPressEvent(self, event):
        key = _WASD_AS_ARROWS.get(event.key(), event.key())
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        slideshow = self.slideshow
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._move_the_hud(key)
        elif key == Qt.Key.Key_Escape:
            self._toggle_pause()
        elif key == Qt.Key.Key_Left:
            answer(slideshow, "cycle_version_back") if shifted else slideshow.slideshow_step(-1)
        elif key == Qt.Key.Key_Right:
            answer(slideshow, "cycle_version") if shifted else slideshow.slideshow_step(1)
        elif key == Qt.Key.Key_Up:
            slideshow.slideshow_nav("up") if shifted else slideshow.slideshow_cull()
        elif key == Qt.Key.Key_Down:
            slideshow.slideshow_nav("down") if shifted else slideshow.slideshow_toggle_lock()
        elif key in (Qt.Key.Key_E, Qt.Key.Key_Home):
            # The loop key, on both of the keys a session gives its two
            # satellites: seeds, then actions, then off.
            slideshow.slideshow_loop_cycle()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.close()    # out of the slideshow, into the folder of what is on screen
        elif apply_motion_key(self._motion, key,
                              on_drive_toggle=self._actions.drive_toggle):
            pass
        else:
            super().keyPressEvent(event)
            return
        self._answered()

    def _answered(self) -> None:
        """A key or a press was taken: the Funestra here has already answered it,
        so the slideshow reads it now rather than at its next look, and the HUD
        is drawn afresh rather than on its beat."""
        self.slideshow.tick()
        self.refresh_hud()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._note.reposition()

    # --- leaving ---------------------------------------------------------------

    def gone(self) -> None:
        """The slideshow is over: the window goes with it."""
        if not self._closing:
            self.close()

    def closeEvent(self, event):
        """Leave, handing the gallery the slide that was on screen.

        However the slideshow is left — a double-click, Enter, the spoken
        "close", or ending on a locked slide — the item you were looking at is
        the one you want to find afterwards, so the gallery picks it where the
        slideshow was playing.
        """
        self._closing = True
        self.hide()
        self._pane.close_engine()  # lets go of every held file, so it can be deleted
        self.slideshow.close()
        super().closeEvent(event)


class _TheWindowsPresses:
    """The window as the Funestra sees it: what a press on the HUD it wears is
    asked of, and what heads that HUD.  The window is the slideshow's own, so
    closing the Funestra closes nothing here."""

    def __init__(self, window: SlideshowView) -> None:
        self._window = window

    def apply_command(self, command: str) -> bool:
        return self._window.press(command)

    def tick(self) -> None:
        pass

    def status_fields(self) -> dict[str, str]:
        return {}

    def top_block(self) -> ModeHud:
        return ModeHud(video=self._window.item_label())

    def set_showing(self, showing: bool) -> None:
        pass

    def own_frame(self) -> None:
        return None

    def close(self) -> None:
        pass
