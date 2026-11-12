from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from funestra.file_channel import append_command
from funestra.funestra_verbs import SPEED_DOWN, SPEED_UP
from funestra.hud_placement import HudCorner
from funestra.main_hud import ModeHud
from funestra.pointer import OMNIPAUSE_TOGGLE
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QVBoxLayout, QWidget
from shared_ui.colors import BLACK

from origenerator import osr2 as osr2_device
from origenerator.config import FRAMES_BEING_MADE_DIR
from origenerator.gui.deferred import defer
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_pane import FunestraPane, PaneAudio, PaneChannel
from origenerator.gui.funestra_slideshow import FunestraSlideshow, Hosting, Playing, Seat
from origenerator.gui.hud_queue import QueueFoot
from origenerator.gui.message import HEARD_MARK, INFO, Message, time_to_read_ms
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.osr2_controls_state import (
    REPAINT_MS,
    Osr2Situation,
    osr2_controls_state,
    post_device_action,
)
from origenerator.gui.request_promise import RequestPromise
from origenerator.gui.slideshow_hud import (
    COLLAPSES,
    OPENS_IN,
    THE_SLIDESHOWS_OWN,
    HudPlacement,
    slideshow_hud_model,
)
from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.osr2_controls_commands import shape_press, spelled_for
from origenerator.slideshow_buttons import PRESSES_ON_THE_QUEUE, answer

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


def _sent_to_the_dashboard(shape: str) -> tuple[str, ...]:
    return tuple(spelled_for(shape, verb)
                 for verb in ("prev", "nudge_prev", "nudge_next", "next", "funscript_jump", "lock", "trash"))


@dataclass(frozen=True)
class ViewShow:
    shape: str = ""
    start: int | None = None
    shuffle: object = None
    actions: SlideshowActions | None = None
    hud: object = None
    versions: object = None
    pace: object = None
    frames: object = None
    locked: bool = False


@dataclass(frozen=True)
class ViewWiring:
    engine: object = None
    motion: object = None
    radio: object = None
    volume: object = None
    clock: Callable[[], float] = time.monotonic


NOTHING_TO_SHOW = ViewShow()
USUAL_WIRING = ViewWiring()


@dataclass(frozen=True)
class HudWear:
    dashboard_cmd_file: object = None
    corner: HudCorner = HudCorner.UPPER_LEFT
    minimized: bool = False
    collapse: object = None
    open_in: object = None


NO_WEAR = HudWear()


class SlideshowView(QWidget):
    def __init__(self, items, show: ViewShow = NOTHING_TO_SHOW,
                 wiring: ViewWiring = USUAL_WIRING, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        shape = show.shape
        self._actions = show.actions if show.actions is not None else SlideshowActions()
        self._motion = wiring.motion
        self._clock = wiring.clock
        self._hud_shape = shape
        self._dashboard_cmd_file = None
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
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, BLACK)
        self.setPalette(palette)

        self._note = Message(self)
        self._request_note = ""
        self._promise = RequestPromise()
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)

        channel = PaneChannel()
        self.slideshow = FunestraSlideshow(
            Playing(items, start=show.start, shuffle=show.shuffle, hud=show.hud, actions=self._actions,
                    versions=show.versions, locked=show.locked),
            Seat(show.shape, channel,
                 show.frames if show.frames is not None else FrameFiles(FRAMES_BEING_MADE_DIR / "fullscreen")),
            Hosting(pace=show.pace, shown=self),
            parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pane = FunestraPane(
            channel=channel, user=lambda _playback: _TheWindowsPresses(self),
            hud=self._hud_model,
            engine_for=(None if wiring.engine is None
                        else (lambda _window_id: wiring.engine)),
            audio=PaneAudio(wiring.radio, wiring.volume, self._volume_moved))
        layout.addWidget(self._pane, 1)
        self.slideshow.tick()

    def wear_the_hud(self, shape: str, wear: HudWear = NO_WEAR) -> None:
        self._hud_shape = shape
        self._dashboard_cmd_file = wear.dashboard_cmd_file
        self._corner, self._minimized = wear.corner, wear.minimized
        self._collapse = wear.collapse
        self._open_in = wear.open_in
        self.refresh_hud()

    @property
    def hud_shape(self) -> str:
        return self._hud_shape

    def set_hud_place(self, corner, minimized: bool) -> None:
        if (corner, minimized) == (self._corner, self._minimized):
            return
        self._corner, self._minimized = corner, minimized
        self.refresh_hud()

    def refresh_hud(self) -> None:
        self._hud_stale = True

    def hud_changed(self) -> None:
        self.refresh_hud()

    def _hud_model(self):
        if not self._hud_shape:
            return None
        now = self._clock()
        beat = REPAINT_MS if self._hud_moving() else _REFRESH_MS
        if not self._hud_stale and (now - self._hud_built_at) * 1000 < beat:
            return self._last_hud_model
        self._hud_stale = False
        self._hud_built_at = now
        model = slideshow_hud_model(self._hud_shape, self.slideshow,
                                    HudPlacement(hosted=self._dashboard_cmd_file is not None),
                                    device=self.hud_device, foot=self.queue_foot.section())
        if model is not None:
            model = replace(model, hud_corner=self._corner, hud_minimized=self._minimized)
        self._last_hud_model = model
        return model

    def _hud_moving(self) -> bool:
        drive = self._last_hud_model.drive if self._last_hud_model is not None else None
        return drive is not None and drive.live

    def press(self, command: str) -> bool:
        if not self._route(command):
            return False
        self._answered()
        return True

    def _route(self, command: str) -> bool:
        verb, _, payload = command.partition("|")
        action, path = shape_press(self._hud_shape, verb, payload)
        if verb in PRESSES_ON_THE_QUEUE:
            self.queue_foot.press(verb, payload)
        elif verb == OMNIPAUSE_TOGGLE:
            self._press_on_the_slide()
        elif action in COLLAPSES or action == OPENS_IN:
            self._place_here_or_out_there(command, action, path)
        elif action in THE_SLIDESHOWS_OWN:
            answer(self.slideshow, action, path)
        elif self.press_osr2_controls(verb):
            pass
        elif action in _RATE_STEPS:
            self._pane.channel.send(_RATE_STEPS[action])
        elif self._dashboard_cmd_file is None:
            return self._action_here(action)
        elif command in _sent_to_the_dashboard(self._hud_shape):
            append_command(self._dashboard_cmd_file, command)
        else:
            return False
        return True

    def _place_here_or_out_there(self, command: str, action: str, corner: str) -> None:
        if self._dashboard_cmd_file is not None:
            append_command(self._dashboard_cmd_file, command)
        elif action == OPENS_IN:
            if self._open_in is not None and corner in HudCorner:
                self._open_in(HudCorner(corner))
        elif self._collapse is not None:
            self._collapse(COLLAPSES[action])

    def _action_here(self, action: str) -> bool:
        if answer(self.slideshow, action):
            self.refresh_hud()
            return True
        return False

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        self.queue_foot.set(items, foreign_queued)
        self.refresh_hud()

    @property
    def hud_device(self):
        if self._motion is None:
            return None
        control = self._actions.osr2_control
        return osr2_controls_state(
            self._motion, Osr2Situation(device=osr2_device.device_mode(),
            trouble=osr2_device.device_trouble(),
            control=control.state() if control is not None else "",
            script=control.script if control is not None else None,
            broker_running=osr2_device.broker_running()))

    def press_osr2_controls(self, action: str) -> bool:
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
        self._pane.set_audio_muted(muted)

    def room_paused(self, paused: bool) -> None:
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

    def flash(self, text: str, *, kind: str = INFO, ms: int = 1500, mark: str = "") -> None:
        self._note.say(text, kind=kind, mark=mark)
        self._note_timer.start(ms)

    def dictating(self, note: str) -> None:
        if note:
            self._note_timer.stop()
        self._request_note = note
        self._refresh_note()

    def request_line(self, message: str, request=None, *, working: bool = False,
                     kind: str = INFO) -> None:
        if working:
            self._promise.make(message, request)
            self._note_timer.stop()
            self._refresh_note()
            return
        self._promise.keep(request)
        self.flash(message, ms=time_to_read_ms(message), kind=kind, mark=HEARD_MARK)

    def _refresh_note(self):
        if self._request_note:
            self._note.say(self._request_note, kind=INFO, mark=HEARD_MARK)
        elif self._promise.note:
            self._note.say(self._promise.note, kind=INFO, mark=HEARD_MARK)
        else:
            self._note.hide()

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
            self.close() if shifted else self._toggle_pause()
        elif key == Qt.Key.Key_Left:
            answer(slideshow, "cycle_version_back") if shifted else slideshow.slideshow_step(-1)
        elif key == Qt.Key.Key_Right:
            answer(slideshow, "cycle_version") if shifted else slideshow.slideshow_step(1)
        elif key == Qt.Key.Key_Up:
            slideshow.slideshow_nav("up") if shifted else slideshow.slideshow_cull()
        elif key == Qt.Key.Key_Down:
            slideshow.slideshow_nav("down") if shifted else slideshow.slideshow_toggle_lock()
        elif key in (Qt.Key.Key_E, Qt.Key.Key_Home):
            slideshow.slideshow_loop_cycle()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.close()
        elif apply_motion_key(self._motion, key,
                              on_drive_toggle=self._actions.drive_toggle):
            pass
        else:
            super().keyPressEvent(event)
            return
        self._answered()

    def _answered(self) -> None:
        self.slideshow.tick()
        self.refresh_hud()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._note.reposition()

    def gone(self) -> None:
        if not self._closing:
            self.close()

    def closeEvent(self, event):
        self._closing = True
        # Qt: an activation still queued reaches this hidden window, which Qt then remembers as owed the
        # focus, and it never forgets the address: the next widget allocated there takes the keyboard on show.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        self._pane.close_engine()  # Windows will not move a file the engine holds open
        self.slideshow.close()
        super().closeEvent(event)


class _TheWindowsPresses:
    def __init__(self, window: SlideshowView) -> None:
        self._window = window

    def apply_command(self, command: str) -> bool:
        return self._window.press(command)

    def tick(self) -> None:
        pass

    def status_fields(self) -> dict[str, str]:
        return {}

    def top_block(self) -> ModeHud:
        return ModeHud()

    def set_showing(self, showing: bool) -> None:
        pass

    def own_frame(self) -> None:
        return None

    def close(self) -> None:
        pass
