from __future__ import annotations

import logging
from typing import Protocol

from funestra.on_screen_history import OnScreenHistory
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget
from shared_ui.message_shape import ERROR, INFO, WARNING, answering_what_he_said

from origenerator import gallery, request_settings
from origenerator.animate_command import AnimateRequest
from origenerator.gallery.collection import collection
from origenerator.gallery.voice_commands import said_in
from origenerator.generation_config import filled_params
from origenerator.gui.inflight_items import requested_of
from origenerator.gui.open_setters import ForTheSetter, OpenSetters
from origenerator.gui.picking import Picks
from origenerator.gui.request_answering import RequestAnswerer
from origenerator.gui.voice_wiring import VoiceSources, VoiceSwitches
from origenerator.setter_voice import setter_phrases
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
    POPULATE_SWITCH as _POPULATE,
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
    GoToCollection,
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
from origenerator.voice.dictation import (
    CANCEL_WORD,
    CANCELED,
    COMPLETED,
    RETRY_WORD,
    SUBMIT_WORD,
    RequestDictation,
)
from origenerator.voice.listener import CommandAndRequestListener, Phrases
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


_ENHANCED_SAID = {AppCommand.ENHANCED_ON: True, AppCommand.ENHANCED_OFF: False}

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

_ABOUT_THE_PICKED_TILE = frozenset({AppCommand.CULL, AppCommand.FAVORITE})

_ABOUT_THE_SLIDE = frozenset({
    AppCommand.BACK, AppCommand.FORWARD, AppCommand.CULL,
    AppCommand.LOCK, AppCommand.UNLOCK, AppCommand.FAVORITE,
})


class VoiceHost(Protocol):
    def selected_generation(self) -> str | None: ...

    def queue_request(self, row, workflow, params, spoken, revision) -> tuple[str, str]: ...


def _named(picks: Picks) -> str:
    return "|".join(sorted(map(str, picks.picked))) + f"#{picks.anchor}"


class VoiceRouter(QObject):
    def __init__(self, host: VoiceHost, sources: VoiceSources, *, parent: QObject, motion):
        super().__init__(parent)
        self._host = host
        self._db = sources.db
        self._slideshows = sources.slideshows
        self._client = sources.client
        self._starting = sources.starting
        self._toc = sources.toc
        self._pane = sources.pane
        self._enhancing = sources.enhance
        self._combine = sources.combine
        self._setters = sources.setters if sources.setters is not None else OpenSetters()
        self.listener = CommandAndRequestListener(
            command_matcher=match_voice_command,
            bare_matcher=self._bare_command,
            dictation=RequestDictation(),
            phrases=Phrases(spoken_phrases() | setter_phrases(), phrases_heard_only_outright(),
                            said_in),
        )
        self.listener.heard.connect(self._on_heard)
        self.listener.error.connect(self._on_error)
        self.listener.request.connect(self.on_spoken_request)
        self.requests = sources.requests or RequestAnswerer(
            sources.db, sources.jobs, sources.client, parent=self)
        self._request_target: str | None = None
        self._switches: dict[str, QWidget | None] = {}
        self._buttons: dict = {}
        self._picks_over_time = OnScreenHistory()
        self._picks_named: dict[str, Picks] = {}
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

    def bind_the_buttons(self, switches: VoiceSwitches, *, actions, enhance) -> None:
        self._switches = {_POPULATE: switches.populate, _RADIO: switches.radio,
                          _DRIVE: switches.drive, _MIC: switches.mic}
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

    def shut_the_mic(self) -> None:
        self.listener.stop_commands()

    def close(self) -> None:
        self.shut_the_mic()
        self.listener.close()

    def _on_heard(self, text: str) -> None:
        if any(char.isalpha() for char in text):
            self._slideshows.note_voice_command(
                f"heard: “{gallery.recognized_spelling(text) or text}”")

    def _on_error(self, message: str) -> None:
        self._slideshows.note_voice_command(message, kind=ERROR)

    def _bare_command(self, text: str):
        return ForTheSetter(text) if self._setters.knows(text) else shaped_app_command(text)

    def run_spoken_command(self, text: str, said_at: float | None = None) -> bool:
        with answering_what_he_said():
            return self._run_what_he_said(text, said_at)

    def _run_what_he_said(self, text: str, said_at: float | None) -> bool:
        shape, rest = split_shape(text)
        spoken = self.listener.push_dictation(rest, spoken_at=said_at)
        if spoken is not None:
            self.on_spoken_request(spoken, shape=shape)
            return True
        if self._setters.hear(text):
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
        with answering_what_he_said():
            self._answer(matched, said_at)

    def _answer(self, matched, said_at: float | None) -> None:
        if isinstance(matched, ForTheSetter):
            self._setters.hear(matched.text)
        elif isinstance(matched, CollectionCommand):
            self._slideshows.play_collection(matched)
        elif isinstance(matched, SlideshowControl):
            self._slideshows.run_slideshow_command(matched.command, matched.shape)
        elif isinstance(matched, SurfaceCommand):
            if isinstance(matched.command, (AppCommand, GoToCollection)):
                self._run_app_command(matched.command, matched.shape, said_at)
            else:
                self._on_image_command(matched, said_at)
        elif isinstance(matched, (AppCommand, GoToCollection)):
            self._run_app_command(matched, said_at=said_at)
        elif isinstance(matched, BarSetting):
            self._set_motion_bar(matched)
        else:
            logger.warning("Voice: no arm for a matched %s", type(matched).__name__)

    def _run_app_command(self, command: AppCommand | GoToCollection, shape: str | None = None,
                         said_at: float | None = None) -> None:
        if isinstance(command, GoToCollection):
            self._go_to_collection(command.key, shape)
        elif command in _ENHANCED_SAID:
            self._slideshows.set_enhanced_filter(shape, _ENHANCED_SAID[command])
        elif command is AppCommand.FAVORITES_OFF:
            self._slideshows.set_favorites_filter(shape, False)
        elif command is AppCommand.FILTER_OFF:
            self._slideshows.clear_action_filter(shape)
        elif command in _SWITCHES:
            self._flip_switch(command)
        elif command is AppCommand.SWITCH:
            self._slideshows.switch_sides()
        elif command in _MOTION:
            self._move_the_motion(command)
        elif self._slideshows.showing is not None and command in _ABOUT_THE_SLIDE:
            self._slideshows.run_on_slide(command, said_at)
        else:
            self._run_in_gallery(command, said_at)

    def note_picks(self, picks: Picks, *, now: float) -> None:
        name = _named(picks)
        self._picks_named[name] = picks
        self._picks_over_time.observe(name, now=now, playing_for=0.0)

    def _go_to_collection(self, key: str, shape: str | None = None) -> None:
        label = collection(key).label
        if not self._toc.stand_in_collection(key, shape):
            self._slideshows.note_voice_command(f"no {label} collection yet", kind=WARNING)
            return
        self._slideshows.note_voice_command(label)

    def _flip_switch(self, command: AppCommand) -> None:
        switch, want, name = _SWITCHES[command]
        button = self._switches[switch]
        if button is None:
            self._slideshows.note_voice_command(f"{name} is the session's here", kind=WARNING)
            return
        if not button.isEnabled():
            self._slideshows.note_voice_command(f"{name} can't be switched here", kind=WARNING)
            return
        on = (not button.isChecked()) if want is None else want
        button.setChecked(on)
        self._slideshows.note_voice_command(f"{name} {'on' if on else 'off'}")

    def _move_the_motion(self, command: AppCommand) -> None:
        move, argument = self._motion_moves[command]
        if move is None:
            self._say_the_motion_is_the_sessions()
            return
        move() if argument is None else move(argument)
        self._slideshows.note_voice_command(self._motion.status_text())

    def _say_the_motion_is_the_sessions(self) -> None:
        self._slideshows.note_voice_command("the motion is the session's here", kind=WARNING)

    def _set_motion_bar(self, setting: BarSetting) -> None:
        set_the_bar = self._bar_setters[setting.bar]
        if set_the_bar is None:
            self._say_the_motion_is_the_sessions()
            return
        set_the_bar(setting.value)
        self._slideshows.note_voice_command(self._motion.status_text())

    def _run_in_gallery(self, command: AppCommand, said_at: float | None = None) -> None:
        if command in (AppCommand.LOCK, AppCommand.UNLOCK):
            self._slideshows.note_voice_command(f"No slideshow to {command.value}",
                                    kind=WARNING)
            return
        if command in _ABOUT_THE_PICKED_TILE:
            self._pick_again_what_was_picked_at(said_at)
        button, press = self._buttons[command]
        self._press_gallery_pane_button(button, press, _BUTTON_REFUSALS[command])

    def _pick_again_what_was_picked_at(self, said_at: float | None) -> None:
        if said_at is None:
            return
        picks = self._picks_named.get(self._picks_over_time.path_at(said_at))
        if picks is not None and picks.picked and picks != self._pane.picks():
            self._pane.pick_again(picks)

    def _press_gallery_pane_button(self, button, press, refusal: str | None = None) -> None:
        if button.isHidden() or not button.isEnabled():
            self._slideshows.note_voice_command(refusal or button.toolTip(), kind=WARNING)
            return
        said = button.toolTip()
        press()
        self._slideshows.note_voice_command(said)

    def _on_image_command(self, command, said_at: float | None = None) -> None:
        slideshow = self._slideshows.surface_for(command.shape)
        if slideshow is None:
            if command.command == gallery.ENHANCE_COMMAND:
                self._press_gallery_pane_button(*self._enhance)
            return
        target = slideshow.back_to_what_was_said_over(said_at)
        if isinstance(command.command, AnimateRequest):
            prompt_id, message, kind = self._combine.animate_it(target, command.command)
        elif command.command == gallery.ENHANCE_COMMAND:
            prompt_id, message, kind = self._enhancing.enhance_it(target)
        else:
            prompt_id, message, kind = self._enhancing.fix_parts(target, command.command)
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
        if spoken.state is CANCELED:
            self._answer_request(slideshow, "request canceled", spoken)
            return
        if spoken.state != COMPLETED:
            self._answer_request(slideshow, f"request dropped — never heard “{SUBMIT_WORD}”",
                                 spoken)
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
        if slideshow is None:
            return
        note = (f"Request: {spoken.text}… — or say "
                f"“{SUBMIT_WORD}”/“{RETRY_WORD}”/“{CANCEL_WORD}”"
                if spoken.listening else "")
        slideshow.pause_for_request(spoken.listening, note)

    def _answer_request(self, slideshow, message: str, spoken, *,
                        working: bool = False, kind: str = INFO) -> None:
        if slideshow is not None:
            slideshow.note_request(message, spoken, working=working, kind=kind)

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
        self.requests.ask(
            row["prompt_id"], (params.get("positive_prompt", ""), params.get("negative_prompt", "")),
            spoken.text,
            settings=request_settings.settings_to_tell(workflow.param_definitions(), params),
            in_scenes=workflow.tells_a_story(), weights=workflow.prompts_take_weights,
            owner=self,
            then=lambda revision, context=(row, workflow, params, spoken, shape, standing):
                self._on_revised(context, revision))

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
                slideshow, revision.answer or f"“{revision.term}” is already how you asked for it",
                spoken, kind=INFO if revision.answer else WARNING)
            return
        message, kind = self._host.queue_request(*asked, spoken, revision)
        self._answer_request(slideshow, message, spoken, kind=kind)
