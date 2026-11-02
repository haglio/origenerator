from __future__ import annotations

import logging
from typing import Protocol

from PyQt6.QtCore import QObject, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget
from shared_ui import colors
from shared_ui.palette import BG_PRIMARY, WHITE, as_hex, as_rgba
from shared_ui.spacing import BUTTON_RADIUS, MARGIN_STANDARD

from origenerator import gallery, prompt_edit
from origenerator.animate_command import AnimateRequest
from origenerator.gallery.collection import (
    EXPERIMENTS_KEY as _EXPERIMENTS_KEY,
)
from origenerator.gallery.collection import (
    FAVORITES_KEY as _FAVORITES_KEY,
)
from origenerator.gallery.collection import (
    LATEST_KEY as _LATEST_KEY,
)
from origenerator.gallery.voice_commands import said_in
from origenerator.generation_config import filled_params
from origenerator.gui.inflight_items import requested_of
from origenerator.gui.message import ERROR, HEARD_MARK, INFO, WARNING, set_marked_text
from origenerator.gui.request_worker import ReviseTask, RevisionWorker
from origenerator.gui.starting_rows import StartingRows
from origenerator.voice.app_commands import (
    AUTO_SWITCH as _AUTO,
)
from origenerator.voice.app_commands import (
    DRIVE_SWITCH as _DRIVE,
)
from origenerator.voice.app_commands import (
    MIC_SWITCH as _MIC,
)
from origenerator.voice.app_commands import (
    MOTION_MOVES as _MOTION,
)
from origenerator.voice.app_commands import (
    RADIO_SWITCH as _RADIO,
)
from origenerator.voice.app_commands import (
    SWITCHES as _SWITCHES,
)
from origenerator.voice.app_commands import (
    SWITCHES_A_HOST_HOLDS,
    AppCommand,
    BarSetting,
    phrases_heard_only_outright,
)
from origenerator.voice.commands import (
    CollectionCommand,
    SlideshowControl,
    SurfaceCommand,
    match_voice_command,
    shaped_app_command,
    split_shape,
    spoken_phrases,
)
from origenerator.voice.dictation import COMPLETED, RequestDictation
from origenerator.voice.listener import CommandAndRequestListener, Phrases
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import name_parts

logger = logging.getLogger(__name__)

_FLASH_MS = 4000

_WANTS_ANIMATING = "an animation"

_COLLECTIONS = {
    AppCommand.LATEST: _LATEST_KEY,
    AppCommand.FAVORITES: _FAVORITES_KEY,
    AppCommand.EXPERIMENTS: _EXPERIMENTS_KEY,
}

_BARS = {
    "speed": "set_speed",
    "amp": "set_amplitude",
    "center": "set_center",
}

_BUTTON_REFUSALS = {
    AppCommand.BACK: "nowhere back",
    AppCommand.FORWARD: "nowhere forward",
    AppCommand.CULL: None,
    AppCommand.FAVORITE: None,
    AppCommand.UNDO: None,
    AppCommand.REDO: None,
    AppCommand.GROUP: "pick some folders first",
}

_FILTERS = {
    AppCommand.FILTER_ENHANCED: True,
    AppCommand.FILTER_OFF: False,
}

_ABOUT_THE_SLIDE = frozenset({
    AppCommand.BACK, AppCommand.FORWARD, AppCommand.CULL,
    AppCommand.LOCK, AppCommand.UNLOCK, AppCommand.FAVORITE,
})


class VoiceHost(Protocol):
    def collection_label(self, key: str) -> str: ...

    def stand_in_collection(self, key: str, shape: str | None) -> bool: ...

    def selected_generation(self) -> str | None: ...

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str, str]: ...

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str, str]: ...

    def animate_it(self, image_id: str | None,
                   asked) -> tuple[str | None, str, str]: ...

    def queue_request(self, row, workflow, params, spoken, revision) -> tuple[str, str]: ...


class VoiceRouter(QObject):
    caption_shown = pyqtSignal(bool)

    def __init__(self, host: VoiceHost, *, parent: QObject, db, slideshows, client,
                 motion, starting: StartingRows):
        super().__init__(parent)
        self._host = host
        self._db = db
        self._slideshows = slideshows
        self._client = client
        self._starting = starting
        self.listener = CommandAndRequestListener(
            command_matcher=match_voice_command,
            bare_matcher=shaped_app_command,
            dictation=RequestDictation(),
            phrases=Phrases(spoken_phrases(), phrases_heard_only_outright(), said_in),
        )
        self.listener.error.connect(lambda msg: logger.warning("Voice: %s", msg))
        self.listener.heard.connect(self._on_heard)
        self.listener.error.connect(self._on_error)
        self.listener.request.connect(self.on_spoken_request)
        self._revision = RevisionWorker(prompt_edit.work_out, parent=self)
        self._revision.revised.connect(self._on_revised)
        self._request_target: str | None = None
        self.status = QLabel()
        self.status.setObjectName("voiceStatus")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"#voiceStatus {{ color: {as_hex(WHITE)}; background: {as_rgba(BG_PRIMARY, 0.88)};"
            f" padding: {MARGIN_STANDARD}px; border-radius: {BUTTON_RADIUS}px; }}"
        )
        self.status.hide()
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._revert)
        self._working_status = ""
        self._working_request = None
        self._switches: dict[str, QWidget | None] = {}
        self._buttons: dict = {}
        self._enhance = None
        self._hold_the_motion(motion)

    def _hold_the_motion(self, motion) -> None:
        self._motion = motion
        self._motion_moves = {
            command: (getattr(motion, method) if motion else None, argument)
            for command, (method, argument) in _MOTION.items()
        }
        self._bar_setters = {
            bar: getattr(motion, setter) if motion else None
            for bar, setter in _BARS.items()
        }

    def become_hosted(self) -> None:
        self._hold_the_motion(None)
        self._switches.update(dict.fromkeys(SWITCHES_A_HOST_HOLDS))

    def become_standalone(self, motion, *, radio, drive, mic) -> None:
        self._hold_the_motion(motion)
        self._switches.update({_RADIO: radio, _DRIVE: drive, _MIC: mic})

    def bind_the_buttons(self, *, auto, radio, drive, mic, actions, enhance) -> None:
        self._switches = {_AUTO: auto, _RADIO: radio, _DRIVE: drive, _MIC: mic}
        self._buttons = dict(actions)
        self._enhance = enhance

    def listening(self) -> bool:
        button = self._switches.get(_MIC)
        return button is not None and button.isChecked()

    def mic_toggled(self, _on: bool) -> None:
        self.sync()

    def sync(self) -> None:
        if not self.listening():
            self.shut_the_mic()
            return
        self.listener.start_commands(self.on_command)
        self._show("Listening…", transient=False)

    def shut_the_mic(self) -> None:
        self.listener.stop_commands()
        self._flash_timer.stop()
        self._set_caption(None)

    def say(self, message: str, *, mark: str = HEARD_MARK) -> None:
        self._show(message, transient=True, mark=mark)

    def _set_caption(self, text: str | None, mark: str = HEARD_MARK) -> None:
        if text is None:
            self.status.hide()
        else:
            set_marked_text(self.status, text, mark=mark, color=colors.WHITE)
            self.status.show()
        self.caption_shown.emit(text is not None)

    def _show(self, text: str, *, transient: bool, mark: str = HEARD_MARK) -> None:
        self._set_caption(text, mark)
        if transient:
            self._flash_timer.start(_FLASH_MS)
        else:
            self._flash_timer.stop()

    def _revert(self) -> None:
        if self._working_status:
            self._show(self._working_status, transient=False)
        elif self.listening():
            self._show("Listening…", transient=False)
        else:
            self._set_caption(None)

    def _on_heard(self, text: str) -> None:
        if any(char.isalpha() for char in text):
            self._say_both(
                f"heard: “{gallery.recognized_spelling(text) or text}”")

    def _on_error(self, message: str) -> None:
        self._say_both(message, kind=ERROR)

    def _say_both(self, message: str, *, kind: str = INFO) -> None:
        self._show(message, transient=True)
        self._slideshows.note_voice_command(message, kind=kind)

    def run_spoken_command(self, text: str, said_at: float | None = None) -> bool:
        shape, rest = split_shape(text)
        spoken = self.listener.push_dictation(rest, spoken_at=said_at)
        if spoken is not None:
            self.on_spoken_request(spoken, shape=shape)
            return True
        bare = self.listener.bare_command(text)
        if bare is not None:
            self.on_command(bare, said_at)
            return True
        matched = match_voice_command(text)
        if matched is None:
            logger.info("Voice (from the session): a %d-word utterance matched no command",
                        len(text.split()))
            return False
        self.on_command(matched, said_at)
        return True

    def on_command(self, matched, said_at: float | None = None) -> None:
        if isinstance(matched, CollectionCommand):
            self._slideshows.play_collection(matched)
        elif isinstance(matched, SlideshowControl):
            self._slideshows.run_slideshow_command(matched.command, matched.shape)
        elif isinstance(matched, SurfaceCommand):
            if isinstance(matched.command, AppCommand):
                self._run_app_command(matched.command, matched.shape, said_at)
            else:
                self._on_image_command(matched, said_at)
        elif isinstance(matched, AppCommand):
            self._run_app_command(matched, said_at=said_at)
        elif isinstance(matched, BarSetting):
            self._set_motion_bar(matched)
        else:
            logger.warning("Voice: no arm for a matched %s", type(matched).__name__)

    def _run_app_command(self, command: AppCommand, shape: str | None = None,
                         said_at: float | None = None) -> None:
        if command in _COLLECTIONS:
            self._go_to_collection(command, shape)
        elif command in _FILTERS:
            self._slideshows.filter_enhanced(_FILTERS[command], shape)
        elif command in _SWITCHES:
            self._flip_switch(command)
        elif command in _MOTION:
            self._move_the_motion(command)
        elif self._slideshows.showing is not None and command in _ABOUT_THE_SLIDE:
            self._slideshows.run_on_slide(command, said_at)
        else:
            self._run_in_gallery(command)

    def _go_to_collection(self, command: AppCommand, shape: str | None = None) -> None:
        key = _COLLECTIONS[command]
        label = self._host.collection_label(key)
        if not self._host.stand_in_collection(key, shape):
            self._slideshows.answer(f"no {label} collection yet", kind=WARNING)
            return
        self._slideshows.answer(label)

    def _flip_switch(self, command: AppCommand) -> None:
        switch, want, name = _SWITCHES[command]
        button = self._switches[switch]
        if button is None:
            self._slideshows.answer(f"{name} is the session's here", kind=WARNING)
            return
        if not button.isEnabled():
            self._slideshows.answer(f"{name} can't be switched here", kind=WARNING)
            return
        on = (not button.isChecked()) if want is None else want
        button.setChecked(on)
        self._slideshows.answer(f"{name} {'on' if on else 'off'}")

    def _move_the_motion(self, command: AppCommand) -> None:
        move, argument = self._motion_moves[command]
        if move is None:
            self._say_the_motion_is_the_sessions()
            return
        move() if argument is None else move(argument)
        self._slideshows.answer(self._motion.status_text())

    def _say_the_motion_is_the_sessions(self) -> None:
        self._slideshows.answer("the motion is the session's here", kind=WARNING)

    def _set_motion_bar(self, setting: BarSetting) -> None:
        set_the_bar = self._bar_setters[setting.bar]
        if set_the_bar is None:
            self._say_the_motion_is_the_sessions()
            return
        set_the_bar(setting.value)
        self._slideshows.answer(self._motion.status_text())

    def _run_in_gallery(self, command: AppCommand) -> None:
        if command in (AppCommand.LOCK, AppCommand.UNLOCK):
            self._slideshows.answer(f"No slideshow to {command.value}",
                                    kind=WARNING)
            return
        button, press = self._buttons[command]
        self._press_gallery_pane_button(button, press, _BUTTON_REFUSALS[command])

    def _press_gallery_pane_button(self, button, press, refusal: str | None = None) -> None:
        if button.isHidden() or not button.isEnabled():
            self._slideshows.answer(refusal or button.toolTip(), kind=WARNING)
            return
        said = button.toolTip()
        press()
        self._slideshows.answer(said)

    def _on_image_command(self, command, said_at: float | None = None) -> None:
        slideshow = self._slideshows.surface_for(command.shape)
        if slideshow is None:
            if command.command == gallery.ENHANCE_COMMAND:
                self._press_gallery_pane_button(*self._enhance)
                return
            wants = (_WANTS_ANIMATING
                     if isinstance(command.command, AnimateRequest)
                     else f"a {name_parts(command.command)} fix")
            self._show(f"{wants} needs an image on screen", transient=True)
            return
        target = slideshow.back_to_what_was_said_over(said_at)
        if isinstance(command.command, AnimateRequest):
            prompt_id, message, kind = self._host.animate_it(target, command.command)
        elif command.command == gallery.ENHANCE_COMMAND:
            prompt_id, message, kind = self._host.enhance_it(target)
        else:
            prompt_id, message, kind = self._host.fix_parts(target, command.command)
        slideshow.note_voice_run(prompt_id, message, kind=kind)

    def on_spoken_request(self, spoken, shape: str | None = None) -> None:
        slideshow = self._slideshows.surface_for(shape)
        if self._request_target is None:
            self._request_target = self._target_of(slideshow, spoken.opened_at)
        if spoken.listening:
            self._pause_for_request(slideshow, spoken)
            return
        target = self._request_target
        self._request_target = None
        self._pause_for_request(slideshow, spoken)
        if spoken.state != COMPLETED:
            self._answer_request(slideshow, "request dropped — never heard “over”", spoken)
            return
        self._begin_request(target, spoken, shape)

    def drop_the_request(self) -> None:
        self.listener.drop_the_request()
        self._request_target = None

    def _target_of(self, slideshow, said_at: float | None) -> str | None:
        if slideshow is not None:
            return slideshow.back_to_what_was_said_over(said_at)
        return self._host.selected_generation()

    def _pause_for_request(self, slideshow, spoken) -> None:
        note = (f"Request: {spoken.text}… — say “over” to submit"
                if spoken.listening else "")
        if slideshow is not None:
            slideshow.pause_for_request(spoken.listening, note)
        elif spoken.listening:
            self._show(note, transient=False)

    def _answer_request(self, slideshow, message: str, spoken, *,
                        working: bool = False, kind: str = INFO) -> None:
        if working:
            self._working_status = "" if slideshow is not None else message
            self._working_request = spoken
        elif spoken is self._working_request:
            promised, self._working_status = self._working_status, ""
            self._working_request = None
            if promised and self.status.text() == promised:
                self._revert()
        if slideshow is not None:
            slideshow.note_request(message, spoken, working=working, kind=kind)
        else:
            self._show(message, transient=not working)

    def _begin_request(self, prompt_id: str | None, spoken,
                       shape: str | None = None) -> None:
        row = self._db.get_generation(prompt_id) if prompt_id else None
        slideshow = self._slideshows.surface_for(shape)
        if row is None:
            self._answer_request(
                slideshow, "nothing on screen to request a change to", spoken)
            return
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or self._client is None:
            self._answer_request(
                slideshow, "this one can't be re-made, so there's nothing to revise",
                spoken)
            return
        params = filled_params(row, workflow)
        self._answer_request(slideshow, f"working out “{spoken.text}”…", spoken,
                             working=True)
        standing = self._starting.show(**requested_of(row, workflow, params))
        QThreadPool.globalInstance().start(ReviseTask(
            self._revision, (row, workflow, params, spoken, shape, standing),
            params.get("positive_prompt", ""), params.get("negative_prompt", ""),
            spoken.text, in_scenes=workflow.tells_a_story(),
        ))

    def _on_revised(self, context, revision) -> None:
        row, workflow, params, spoken, shape, standing = context
        try:
            self._answer_the_revision((row, workflow, params), spoken, shape, revision)
        finally:
            self._starting.drop(standing)

    def _answer_the_revision(self, asked: tuple, spoken, shape, revision) -> None:
        slideshow = self._slideshows.surface_for(shape)
        if revision is None:
            self._answer_request(
                slideshow, f"didn't catch what to change in “{spoken.text}”", spoken,
                kind=WARNING)
            return
        if not revision.changed:
            self._answer_request(
                slideshow, f"“{revision.term}” is already how you asked for it", spoken,
                kind=WARNING)
            return
        message, kind = self._host.queue_request(*asked, spoken, revision)
        self._answer_request(slideshow, message, spoken, kind=kind)
