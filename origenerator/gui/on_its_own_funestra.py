from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from funestra.dashboard import ALREADY_DONE
from funestra.funestra_verbs import SET_VOLUME, SHOW, SPEED_DOWN, SPEED_UP
from funestra.genau_buttons import NEXT_FLICK, PREV_FLICK, TRASH_FLICK
from funestra.hud_kinds import MODE_BUTTONS, minimize_funestra_button
from funestra.hud_placement import HudCorner
from funestra.modes import MainMode
from funestra.pointer import OMNIPAUSE_TOGGLE, PRESSED_AGAIN
from funestra.program.asks import FOCUSED, KEY
from funestra.session_quit import SESSION_QUIT
from funestra.status import parse_status
from funestra.volume import VolumeHud
from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget
from shared_ui.message_shape import HEARD_MARK, INFO, time_to_read_ms
from shared_ui.message_window import MessageWindow

from origenerator.fun_time_mode import Rect
from origenerator.genau_flicks import AS_GENAU_STARTS, GenauLeft
from origenerator.gui.hud_queue import QueueFoot
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.on_a_sessions_funestra import HudOnFile
from origenerator.gui.request_promise import RequestPromise
from origenerator.gui.slideshow_hud import (
    COLLAPSES,
    OPENS_IN,
    THE_SLIDESHOWS_OWN,
    HudPlacement,
)
from origenerator.osr2_controls_commands import shape_press
from origenerator.slideshow_buttons import (
    PRESSES_ABOUT_THE_SLIDE,
    PRESSES_ON_THE_QUEUE,
    answer,
)

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
_MODES_PICKED = {command: mode for command, _label, mode in MODE_BUTTONS}
_NAV_MAP_STEPS = {Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_Up: "up",
                  Qt.Key.Key_Down: "down"}
_SHIFTED_STEPS = {Qt.Key.Key_Left: "prev_fix", Qt.Key.Key_Right: "next_fix",
                  Qt.Key.Key_Up: "cycle_version", Qt.Key.Key_Down: "cycle_version_back"}
_GENAUS_KEYS = {
    Qt.Key.Key_Left: PREV_FLICK,
    Qt.Key.Key_Right: NEXT_FLICK,
    Qt.Key.Key_Up: TRASH_FLICK,
    Qt.Key.Key_Down: "lock",
}
_KEYS_BY_THE_NAME_A_FUNESTRA_GIVES = {
    "left": Qt.Key.Key_Left, "right": Qt.Key.Key_Right, "up": Qt.Key.Key_Up,
    "down": Qt.Key.Key_Down, "escape": Qt.Key.Key_Escape, "return": Qt.Key.Key_Return,
    "enter": Qt.Key.Key_Enter, "home": Qt.Key.Key_Home, "space": Qt.Key.Key_Space,
    ";": Qt.Key.Key_Semicolon,
    **{letter: Qt.Key(ord(letter.upper())) for letter in "abcdefghijklmnopqrstuvwxyz"},
    **{digit: Qt.Key(ord(digit)) for digit in "0123456789"},
}


@dataclass(frozen=True)
class OwnWiring:
    motion: object = None
    radio: object = None
    volume: VolumeHud | None = None
    clock: Callable[[], float] = time.monotonic


USUAL_WIRING = OwnWiring()


@dataclass(frozen=True)
class HudWear:
    corner: HudCorner = HudCorner.UPPER_LEFT
    minimized: bool = False
    collapse: object = None
    open_in: object = None


NO_WEAR = HudWear()


def device_rect_of(screen) -> Rect:
    # Qt 6 on Windows: a screen's top-left is in device pixels and its size is in logical ones.
    area, scale = screen.geometry(), screen.devicePixelRatio()
    return Rect(area.x(), area.y(), round(area.width() * scale), round(area.height() * scale))


class _WhereTheFunestraPlays:
    def __init__(self, position_ms: float, read_at: float, rate: float) -> None:
        self._position_ms, self._read_at, self._rate = position_ms, read_at, rate

    def at(self, now: float) -> int:
        return int(self._position_ms + (now - self._read_at) * 1000 * self._rate)


class PlayerOnItsOwnFunestra:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._plays = _WhereTheFunestraPlays(0, 0.0, 0.0)

    def heard(self, fields: dict) -> None:
        status = parse_status(fields)
        self._plays = _WhereTheFunestraPlays(
            status.position_ms, status.read_at or self._clock(),
            0.0 if status.paused else status.speed)

    def position(self) -> int:
        return self._plays.at(self._clock())


class _FollowedChannel(QObject):
    heard = Signal(dict, dict)

    def __init__(self, channel, parent: QObject, genau=None) -> None:
        super().__init__(parent)
        self._channel = channel
        self._genau = genau
        self.waits_on_the_disk = channel.waits_on_the_disk
        self.write_playlist = channel.write_playlist
        self.send = channel.send
        self.send_all = channel.send_all

    def status(self) -> dict[str, str]:
        fields = self._channel.status()
        self.heard.emit(fields, {} if self._genau is None else self._genau.read_status())
        return fields


class _WhereTheFunestraIs(QWidget):
    # Qt asks a question or opens a menu over a QWidget, and the Funestra is another program's
    # window; this one is never shown and only stands where the Funestra is.
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setGeometry(QRect())


class OnItsOwnFunestra(QObject):
    def __init__(self, program, shape: str, actions, wiring: OwnWiring = USUAL_WIRING, *,
                 asks=None, message=None, genau=None, parent=None) -> None:
        super().__init__(parent)
        self._program = program
        self._genau = genau
        self._mode = MainMode.KINO
        self._actions = actions
        self._motion = wiring.motion
        self._clock = wiring.clock
        self._hud_shape = shape
        self._corner, self._minimized = HudCorner.UPPER_LEFT, False
        self._collapse = self._open_in = None
        self._slideshow = None
        self._paused = False
        self._up = True
        self._over: QRect | None = None
        self.over_the_funestra = _WhereTheFunestraIs()
        self.queue_foot = QueueFoot(actions, beside=lambda: self.over_the_funestra)
        self._hud = HudOnFile(program.channel.hud_file, shape, self.queue_foot)
        self._player = PlayerOnItsOwnFunestra(wiring.clock)
        self.channel = _FollowedChannel(program.channel, self, genau)
        self.channel.heard.connect(self._heard_from_the_funestra)
        self._tuner = None if wiring.radio is None else wiring.radio.held_by_a_slideshow()
        opens_at = wiring.volume if wiring.volume is not None else VolumeHud()
        self._volume_told: VolumeHud | None = opens_at
        self._volume_heard: VolumeHud | None = None
        program.channel.send(f"{SET_VOLUME} {opens_at.volume} {int(opens_at.muted)}")
        self._note = message if message is not None else MessageWindow()
        self._request_note = ""
        self._promise = RequestPromise()
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)
        self._asks = asks
        if asks is not None:
            asks.asked.connect(self.asked)

    def shown_for(self, slideshow) -> OnItsOwnFunestra:
        self._slideshow = slideshow
        return self

    def show_on(self, screen) -> None:
        place = device_rect_of(screen)
        if place == self._program.place and not self._program.minimized:
            return
        self._over = QRect(screen.geometry())
        self.over_the_funestra.setGeometry(self._over)
        self._program.show_on(place)
        self._note.reposition_over(self._over)

    def wear_the_hud(self, shape: str, wear: HudWear = NO_WEAR) -> None:
        self._hud_shape = shape
        self._hud.wear(shape)
        self._corner, self._minimized = wear.corner, wear.minimized
        self._collapse, self._open_in = wear.collapse, wear.open_in
        self.hud_changed()

    @property
    def hud_shape(self) -> str:
        return self._hud_shape

    def set_hud_place(self, corner, minimized: bool) -> None:
        if (corner, minimized) != (self._corner, self._minimized):
            self._corner, self._minimized = corner, minimized
            self.hud_changed()

    @property
    def mode(self) -> MainMode:
        return self._mode

    def genau_left(self) -> GenauLeft:
        if self._genau is None:
            return AS_GENAU_STARTS
        return self._genau.left(showing=self._mode is MainMode.GENAU)

    @property
    def player(self) -> PlayerOnItsOwnFunestra | None:
        return self._player if self._mode is MainMode.KINO else None

    def show_kino(self) -> None:
        self._show(MainMode.KINO)

    def show_genau(self, path=None) -> bool:
        if self._genau is None:
            return False
        self._genau.show(path)
        self._show(MainMode.GENAU)
        return True

    def _show(self, mode: MainMode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        self._program.channel.send(f"{SHOW} {mode}")
        self._pause_what_does_not_show()
        self.hud_changed()
        self._slideshow.media_changed.emit()

    def _pick(self, mode: MainMode) -> None:
        if mode is MainMode.GENAU:
            self.show_genau()
            return
        self.show_kino()
        start = self._actions.start_slideshow
        if start is not None and not self._slideshow.whole_set():
            start()

    def _pause_what_does_not_show(self) -> None:
        genau_shows = self._mode is MainMode.GENAU
        self._program.set_paused(self._paused or genau_shows)
        if self._genau is not None:
            self._genau.set_paused(self._paused or not genau_shows)

    def hud_changed(self) -> None:
        if self._slideshow is None or not self._up or not self._hud_shape:
            return
        if self._mode is MainMode.GENAU:
            self._hud.publish_built(partial(self._genau.hud_model, self._hud_shape),
                                    hud_corner=self._corner, hud_minimized=self._minimized)
            return
        self._hud.publish(
            self._slideshow,
            HudPlacement(hosted=False, drives_the_osr2=self._motion is not None),
            hud_corner=self._corner, hud_minimized=self._minimized)

    def asked(self, line: str, at: float) -> None:
        if not self._up:
            return
        command, done, _pressed_at = line.partition(ALREADY_DONE)
        verb, _, rest = command.partition("|")
        if verb == KEY:
            name, _, held = rest.partition("|")
            self._key_by_name(name, held.split("+"), at)
        elif command == SESSION_QUIT:
            self._slideshow.close()
        elif command == PRESSED_AGAIN:
            self._leave()
        elif command != FOCUSED and not done:
            self.press(command, at)

    def press(self, command: str, said_at: float | None = None) -> bool:
        if not self._route(command, said_at):
            return False
        self._answered()
        return True

    def _route(self, command: str, said_at: float | None) -> bool:
        verb, _, payload = command.partition("|")
        action, path = shape_press(self._hud_shape, verb, payload)
        if action in PRESSES_ON_THE_QUEUE:
            self.queue_foot.press(action, path)
        elif action in _MODES_PICKED:
            self._pick(_MODES_PICKED[action])
        elif self._mode is MainMode.GENAU and self._genau.press(action):
            pass
        elif verb == OMNIPAUSE_TOGGLE:
            self._toggle_pause()
        elif action in COLLAPSES or action == OPENS_IN:
            self._place_the_hud(action, path)
        elif action in THE_SLIDESHOWS_OWN:
            self._about_the_slide(action, said_at)
            answer(self._slideshow, action, path)
        elif action in _RATE_STEPS:
            self.channel.send(_RATE_STEPS[action])
        elif command == minimize_funestra_button(self._hud_shape).command:
            self._program.minimize()
        else:
            self._about_the_slide(action, said_at)
            return answer(self._slideshow, action)
        return True

    def _about_the_slide(self, action: str, said_at: float | None) -> None:
        if said_at is not None and action in PRESSES_ABOUT_THE_SLIDE:
            self._slideshow.back_to_what_was_said_over(said_at)

    def _place_the_hud(self, action: str, corner: str) -> None:
        if action == OPENS_IN:
            if self._open_in is not None and corner in HudCorner:
                self._open_in(HudCorner(corner))
        elif self._collapse is not None:
            self._collapse(COLLAPSES[action])

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        self.queue_foot.set(items, foreign_queued)
        self.hud_changed()

    def press_the_queue(self, verb: str, payload: str) -> None:
        self.queue_foot.press(verb, payload)
        self.hud_changed()

    def _heard_from_the_funestra(self, fields: dict, genaus: dict) -> None:
        if self._genau is not None:
            self._hear_genau(genaus)
        if not fields:
            return
        self._player.heard(fields)
        if fields.get("window"):
            self._note.stay_above(int(fields["window"]))
        status = parse_status(fields)
        volume = VolumeHud(volume=int(fields.get("volume") or 0), muted=fields.get("muted") == "1")
        if self._tuner is not None:
            video = bool(status.video) and fields.get("idle") != "1"
            self._tuner.tick(image=True if status.image else (False if video else None),
                             level=None if volume.muted else volume.volume, paused=status.paused)
        self._mind_the_volume(volume)

    def _hear_genau(self, fields: dict) -> None:
        genau_shows = self._mode is MainMode.GENAU
        self._genau.follow_the_beat(showing=genau_shows)
        if self._genau.heard_from(fields) and genau_shows:
            self.hud_changed()

    def loop_came_round(self) -> None:
        if self._genau is not None:
            self._genau.loop_came_round()

    def _mind_the_volume(self, volume: VolumeHud) -> None:
        heard, self._volume_heard = self._volume_heard, volume
        if self._volume_told is not None:
            if volume == self._volume_told:
                self._volume_told = None
            return
        if heard is not None and volume != heard and self._actions.volume_moved is not None:
            self._actions.volume_moved(volume)

    def room_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pause_what_does_not_show()

    def _toggle_pause(self) -> None:
        if self._actions.omnipause is not None:
            self._actions.omnipause()
        else:
            self.room_paused(not self._paused)

    def _leave(self) -> None:
        leave_for_core = self._actions.leave_for_core
        on_screen = (self._genau.prompt_id_on_screen() if self._mode is MainMode.GENAU
                     else self._slideshow.hud_prompt_id)
        if leave_for_core is None or not leave_for_core(on_screen):
            self._slideshow.close()

    def flash(self, text: str, *, kind: str = INFO, mark: str = "") -> None:
        self._say(text, kind=kind, mark=mark)
        self._note_timer.start(time_to_read_ms(text))

    def dictating(self, note: str) -> None:
        if note:
            self._note_timer.stop()
        self._request_note = note
        self._refresh_note()

    def request_message(self, message: str, request=None, *, working: bool = False,
                     kind: str = INFO) -> None:
        if working:
            self._promise.make(message, request)
            self._note_timer.stop()
            self._refresh_note()
            return
        self._promise.keep(request)
        self.flash(message, kind=kind, mark=HEARD_MARK)

    def _say(self, text: str, *, kind: str, mark: str) -> None:
        if self._over is not None:
            self._note.say_over(self._over, text, kind=kind, mark=mark)

    def _refresh_note(self) -> None:
        if self._request_note:
            self._say(self._request_note, kind=INFO, mark=HEARD_MARK)
        elif self._promise.note:
            self._say(self._promise.note, kind=INFO, mark=HEARD_MARK)
        else:
            self._note.hide()

    def take_key(self, event) -> None:
        self._key(event.key(), shifted=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                  ctrl=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                  alt=bool(event.modifiers() & Qt.KeyboardModifier.AltModifier))

    def _key_by_name(self, name: str, held: list[str], at: float) -> None:
        key = _KEYS_BY_THE_NAME_A_FUNESTRA_GIVES.get(name)
        if key is None or not self._key(key, shifted="shift" in held, ctrl="ctrl" in held,
                                        alt="alt" in held, said_at=at):
            self._press_the_apps_own_shortcut(name, held)

    def _press_the_apps_own_shortcut(self, name: str, held: list[str]) -> None:
        core = self._actions.core_window() if self._actions.core_window is not None else None
        if core is None:
            return
        pressed = QKeySequence("+".join([*(part for part in held if part), name]))
        for shortcut in core.findChildren(QShortcut):
            if (shortcut.context() == Qt.ShortcutContext.ApplicationShortcut
                    and shortcut.isEnabled() and shortcut.key() == pressed):
                shortcut.activated.emit()
                return

    def _key(self, key, *, shifted: bool, ctrl: bool, alt: bool = False,
             said_at: float | None = None) -> bool:
        key = _WASD_AS_ARROWS.get(key, key)
        if alt:
            direction = _NAV_MAP_STEPS.get(key)
            if direction is None or self._mode is MainMode.GENAU:
                return False
            self._slideshow.slideshow_nav(direction)
        elif ctrl:
            direction = _HUD_MOVES.get(key)
            if direction is None or self._actions.move_hud is None:
                return False
            self._actions.move_hud(direction)
        elif key == Qt.Key.Key_Escape and not shifted:
            self._toggle_pause()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._leave()
        elif not (self._genaus_key(key, shifted=shifted) if self._mode is MainMode.GENAU
                  else self._kinos_key(key, shifted=shifted, said_at=said_at)):
            return False
        self._answered()
        return True

    def _kinos_key(self, key, *, shifted: bool, said_at: float | None) -> bool:
        slideshow = self._slideshow
        if shifted and key in _SHIFTED_STEPS:
            answer(slideshow, _SHIFTED_STEPS[key])
        elif key == Qt.Key.Key_Left:
            slideshow.slideshow_step(-1)
        elif key == Qt.Key.Key_Right:
            slideshow.slideshow_step(1)
        elif key == Qt.Key.Key_Up:
            self._on_the_slide_it_was_pressed_over(slideshow.slideshow_cull, said_at)
        elif key == Qt.Key.Key_Down:
            self._on_the_slide_it_was_pressed_over(slideshow.slideshow_toggle_lock, said_at)
        elif key in (Qt.Key.Key_E, Qt.Key.Key_Home):
            slideshow.slideshow_loop_cycle()
        else:
            return self._motions_key(key)
        return True

    def _genaus_key(self, key, *, shifted: bool) -> bool:
        if key in _GENAUS_KEYS and not shifted:
            return self._genau.press(_GENAUS_KEYS[key])
        return self._motions_key(key)

    def _motions_key(self, key) -> bool:
        return apply_motion_key(self._motion, key, on_drive_toggle=self._actions.drive_toggle)

    def _on_the_slide_it_was_pressed_over(self, answer_it, said_at: float | None) -> None:
        if said_at is not None:
            self._slideshow.back_to_what_was_said_over(said_at)
        answer_it()

    def _answered(self) -> None:
        if self._up:
            self._slideshow.tick()
            self.hud_changed()

    def gone(self) -> None:
        if not self._up:
            return
        self._up = False
        self._note_timer.stop()
        self._note.shutdown()
        self.over_the_funestra.deleteLater()
        if self._tuner is not None:
            self._tuner.close()
        if self._genau is not None:
            self._genau.close()
        if self._asks is not None:
            self._asks.stop()
        self._hud.blank()
        self._program.end()
        self._slideshow.deleteLater()
