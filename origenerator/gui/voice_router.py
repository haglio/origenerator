"""What is spoken, and where it lands.

The fourth of the gallery's screen concerns to come out of the view that used to
hold all of them, and the one that had no object of its own at all: five module
tables and twenty-five methods on a 7,000-line widget, reachable only by building
one.

What lives here is the whole path an utterance takes. The microphone and what it
is listening for. The caption that says what was heard and what it did, with the
one promise it holds while a request is still being worked out. The matching of
an utterance to a shelf, a switch, a dial, a bank button, an order about the
picture on screen, or a request said over several breaths -- and, for a hosted
app, the same matching of words the session's own microphone heard and posted on
this app's channel.

What it does NOT hold is the doing. A show's own words went to the shows when
they came out (:mod:`origenerator.gui.show_director`); a bank button's press is
the button's own click; and the three orders about a picture -- enhance it, fix a
part of it, make a Genau clip of it -- stay with the seams that run them.
:class:`VoiceHost` names each of those.
"""
from __future__ import annotations

import logging
from functools import partial
from typing import Protocol

from PyQt6.QtCore import QObject, QThreadPool, QTimer
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator import gallery, prompt_edit
from origenerator.config import (
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    VOICE_REQUEST_MATCH_SYSTEM_PROMPT,
)
from origenerator.generation_config import filled_params
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY as _EXPERIMENTS_KEY,
)
from origenerator.gui.gallery_tree import (
    RECENTS_KEY as _RECENTS_KEY,
)
from origenerator.gui.gallery_tree import (
    REQUESTS_KEY as _REQUESTS_KEY,
)
from origenerator.gui.gallery_tree import (
    STARRED_KEY as _STARRED_KEY,
)
from origenerator.gui.gallery_tree import (
    TRASH_KEY as _TRASH_KEY,
)
from origenerator.gui.request_worker import ReviseTask, RevisionWorker
from origenerator.prompt_edit import apply_request
from origenerator.voice.app_commands import AppCommand, DialSetting, app_command_bias
from origenerator.voice.commands import (
    ShelfCommand,
    ShowControl,
    SurfaceCommand,
    match_voice_command,
    sided_app_command,
    split_side,
    voice_command_bias,
)
from origenerator.voice.dictation import COMPLETED, RequestDictation, request_bias
from origenerator.voice.steering import VoiceSteering
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import name_parts

logger = logging.getLogger(__name__)

# How long a flashed line stays up before the caption goes back to what it was
# saying: long enough to read one, short enough that it is gone by the next.
_FLASH_MS = 4000

# What each order about the picture is called in a refusal, where the parts
# themselves do not already name it.
_WANTS = {
    gallery.GENAU_COMMAND: "a Genau clip",
}

# The shelf each spoken shelf name stands you in. What to call it back is the
# host's answer, so a row renamed is renamed in one place.
_SHELVES = {
    AppCommand.RECENTS: _RECENTS_KEY,
    AppCommand.STARRED: _STARRED_KEY,
    AppCommand.EXPERIMENTS: _EXPERIMENTS_KEY,
    AppCommand.REQUESTS: _REQUESTS_KEY,
    AppCommand.TRASH: _TRASH_KEY,
}

# The motion dial each spoken word turns, as (the driver's method, its argument
# or ``None`` for a method that takes none) — the very moves the keys make (see
# :mod:`origenerator.gui.motion_hud`), said out loud instead of pressed. Bound
# against the driver at construction, so a method renamed there is an error at
# launch rather than a spoken word that quietly does nothing.
_MOTION = {
    AppCommand.SPEED_UP: ("adjust_speed", 5),
    AppCommand.SPEED_DOWN: ("adjust_speed", -5),
    AppCommand.AMP_UP: ("adjust_amplitude", 10),
    AppCommand.AMP_DOWN: ("adjust_amplitude", -10),
    AppCommand.CENTER_UP: ("adjust_center", 5),
    AppCommand.CENTER_DOWN: ("adjust_center", -5),
    AppCommand.NEXT_SHAPE: ("cycle_shape", 1),
    AppCommand.PREVIOUS_SHAPE: ("cycle_shape", -1),
    AppCommand.CRUISE: ("toggle_cruise", None),
    AppCommand.CRUISE_ON: ("set_cruise", True),
    AppCommand.CRUISE_OFF: ("set_cruise", False),
    AppCommand.OFFSET: ("quarter_offset", None),
}

# The driver's setter for each dial the numeric grid names
# (:class:`~origenerator.voice.app_commands.DialSetting`), so "amp fifty" puts
# the dial at fifty rather than walking it there ten at a time.
_DIALS = {
    "speed": "set_speed",
    "amp": "set_amplitude",
    "center": "set_center",
}

# The app-wide switch each spoken word flips, as (which of the four switches, the
# state asked for — ``None`` flips whichever way it is standing — and what the
# answer calls it). Set through the button rather than around it, so a spoken
# switch and a clicked one are the same event and the bank shows both. The
# buttons themselves arrive in :meth:`VoiceRouter.bind_the_bank`, by keyword, so
# a rename is a TypeError at launch rather than a word that quietly does nothing.
_AUTO, _AUDIO, _DRIVE, _MIC = "auto", "audio", "drive", "mic"
_SWITCHES = {
    AppCommand.AUTO: (_AUTO, None, "auto-generate"),
    AppCommand.AUTO_ON: (_AUTO, True, "auto-generate"),
    AppCommand.AUTO_OFF: (_AUTO, False, "auto-generate"),
    AppCommand.AUDIO: (_AUDIO, None, "the audio bed"),
    AppCommand.AUDIO_ON: (_AUDIO, True, "the audio bed"),
    AppCommand.AUDIO_OFF: (_AUDIO, False, "the audio bed"),
    AppCommand.DRIVE: (_DRIVE, None, "the OSR2"),
    AppCommand.DRIVE_ON: (_DRIVE, True, "the OSR2"),
    AppCommand.DRIVE_OFF: (_DRIVE, False, "the OSR2"),
    AppCommand.MIC_OFF: (_MIC, False, "the mic"),
}

# The refusal each bank word carries when its button cannot run — ``None`` to use
# the button's own tooltip, which for most of them already says why ("Nothing to
# undo", "Nothing here to star"). Only the two whose tips are bare labels, and
# Group, whose tip explains the button rather than refusing it, carry their own
# words.
_BANK_REFUSALS = {
    AppCommand.BACK: "nowhere back",
    AppCommand.FORWARD: "nowhere forward",
    AppCommand.CULL: None,
    AppCommand.STAR: None,
    AppCommand.UNDO: None,
    AppCommand.REDO: None,
    AppCommand.GROUP: "pick some folders first",
}

# What a spoken word does to a show's enhanced-only switch — the one beside
# F-mode on its HUD. Both ways round rather than one toggle (see
# AppCommand.FILTER_ENHANCED); off takes F-mode with it, "clear filter" being
# the way out of all of the narrowing on every satellite in this family.
_FILTERS = {
    AppCommand.FILTER_ENHANCED: True,
    AppCommand.FILTER_OFF: False,
}

# The words that are about the slide on screen when there is one. The rest of
# the bank (undo, redo, group) is the gallery's whether or not a show covers it:
# undoing a cull you regret is exactly a thing to do mid-show.
_ABOUT_THE_SLIDE = frozenset({
    AppCommand.BACK, AppCommand.FORWARD, AppCommand.CULL,
    AppCommand.LOCK, AppCommand.UNLOCK, AppCommand.STAR,
})


class VoiceHost(Protocol):
    """What the spoken words need of the gallery around them, and nothing else."""

    def working_prompts(self, key: str) -> dict:
        """The prompt pair the loop on ``key`` is currently launching — what
        steering edits."""

    def steer_prompts(self, key: str, new_prompts: dict) -> None:
        """Put an edited pair back, for the loop's next launch."""

    def shelf_label(self, key: str) -> str:
        """What to call a shelf back — the plain name its row carries, without
        the waiting-work count."""

    def stand_in_shelf(self, key: str, side: str | None) -> bool:
        """Select the shelf ``key`` names on ``side`` (or on whichever side the
        tree answers with), exactly as clicking its row does. ``False`` when the
        tree has no row for it at all."""

    def selected_generation(self) -> str | None:
        """The generation picked in the gallery, for a request said with no show
        covering it."""

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str]:
        """Queue the better version of a picture: what it launched on, and the
        line to say about it."""

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str]:
        """Queue a targeted detail fix, the same way."""

    def genau_it(self, image_id: str | None) -> tuple[str | None, str]:
        """Animate a picture as a Genau clip, the same way."""

    def queue_request(self, row, workflow, params, spoken, revision) -> str:
        """Launch a revised generation, record the request under it, and answer
        with the line to say."""


class VoiceRouter(QObject):
    """The microphone, the caption, and where each spoken word lands."""

    def __init__(self, host: VoiceHost, *, parent: QObject, db, shows, client,
                 motion):
        super().__init__(parent)
        self._host = host
        self._db = db
        self._shows = shows
        self._client = client
        self._motion = motion
        # One listener over three vocabularies: the spoken commands, the prompt
        # steering, and the dictation that collects "Request … over" across as
        # many utterances as it takes. The bias teaches whisper all three,
        # without which a quiet mic's "fix <part>" — or the marker words the
        # whole request hangs on — transcribe as other words entirely.
        self.listener = VoiceSteering(
            command_matcher=match_voice_command,
            bare_matcher=sided_app_command,
            dictation=RequestDictation(),
            transcribe_bias=(f"{voice_command_bias()} {app_command_bias()} "
                             f"{request_bias()}"),
        )
        self.listener.error.connect(
            lambda msg: logger.warning("Voice steering: %s", msg))
        self.listener.heard.connect(self._on_heard)
        self.listener.edited.connect(self._on_edited)
        self.listener.error.connect(self._on_error)
        self.listener.request.connect(self.on_spoken_request)
        # A finished request is worked out on the pool: the prompt may not
        # contain the words the speaker used ("no earrings" against a prompt
        # that says "silver ear studs"), and finding out which of its own terms
        # they meant is a call to the local LLM.
        self._revision = RevisionWorker(partial(
            apply_request,
            match=partial(prompt_edit.smart_match,
                          base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                          system_prompt=VOICE_REQUEST_MATCH_SYSTEM_PROMPT),
        ), parent=self)
        self._revision.revised.connect(self._on_revised)
        # The folder whose loop an open mic is steering the prompt of, or None
        # with no loop to steer.
        self._steering: str | None = None
        # The generation an open request is about, captured the moment the
        # request opens rather than when it finishes: a show holds still for the
        # sentence, but the words take seconds and the item on screen when they
        # end is not necessarily the one they were about.
        self._request_target: str | None = None
        # A caption showing what voice heard and did, so it's visible without
        # reading the log. It rides at the top of the left pane, taking its own
        # room rather than floating over the header buttons it used to land on;
        # transient messages revert to the idle "Listening…" after a moment.
        self.status = QLabel()
        self.status.setObjectName("voiceStatus")
        self.status.setWordWrap(True)  # a long utterance grows down, not sideways
        self.status.setStyleSheet(
            "#voiceStatus { color: white; background: rgba(20, 20, 20, 225);"
            " padding: 6px 10px; border-radius: 6px; }"
        )
        self.status.hide()
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._revert)
        # What that caption goes back to saying rather than the idle line: the
        # request it is still working out, and which request that is. It has one
        # slot, so a line flashed over the promise has to know what to restore
        # — the show's corner keeps its own copy of the same pair.
        self._working_status = ""
        self._working_request = None
        # The bank the spoken words act through, bound once it exists.
        self._switches: dict[str, QWidget | None] = {}
        self._bank: dict = {}
        self._enhance = None
        self._motion_turns = {
            command: (getattr(motion, method) if motion else None, argument)
            for command, (method, argument) in _MOTION.items()
        }
        self._dial_setters = {
            dial: getattr(motion, setter) if motion else None
            for dial, setter in _DIALS.items()
        }

    def bind_the_bank(self, *, auto, audio, drive, mic, actions, enhance) -> None:
        """Bind the spoken vocabulary to the buttons it acts through, now that
        the bank exists.

        By keyword and by object, never by attribute name: spelled as strings —
        as they were — a renamed button or handler broke the microphone
        silently, with no import error, no type error, no lint warning, and a
        spoken word that simply did nothing.

        Hosted by a session, three of the switches are never built at all and
        the OSR2 driver is not either — the session's main player owns the
        device for its whole length. Those arrive as ``None``, so
        :meth:`_flip_switch` can still answer that the session owns them, and
        the dial words find nothing to turn rather than a driver that is absent.
        """
        self._switches = {_AUTO: auto, _AUDIO: audio, _DRIVE: drive, _MIC: mic}
        self._bank = dict(actions)
        self._enhance = enhance

    # --- the microphone -----------------------------------------------------

    def listening(self) -> bool:
        """Whether this app is listening on its own mic.

        Never when hosted: the session owns the microphone there, hears the
        spoken commands for both of us, and posts this app's on its channel —
        two listeners on one mic is two transcriptions of every utterance.
        """
        button = self._switches.get(_MIC)
        return button is not None and button.isChecked()

    def mic_toggled(self, _on: bool) -> None:
        """The microphone switch: the one thing that opens or closes the mic."""
        self.sync()

    def sync(self) -> None:
        """Listen, or don't, exactly as the mic button says.

        Nothing else decides. The mic used to come on with the Auto loop and
        again with a fullscreen show, which made "is it listening?" a question
        with a derivation rather than an answer — and left "start slideshow"
        unhearable in the one state it is for, with no show up.

        What is listened *for* still depends on what is running: the spoken
        commands always, and the prompt steering only while a loop has a folder
        to steer. That is not a second switch, just nothing to steer.
        """
        if not self.listening():
            self.listener.stop()           # both halves, so the listener closes
            self.listener.stop_commands()
            self._flash_timer.stop()
            self.status.hide()
            return
        self.listener.start_commands(self.on_command)
        if self._steering is not None:
            self.listener.start(
                lambda: self._host.working_prompts(self._steering),
                lambda new: self._host.steer_prompts(self._steering, new),
            )
        else:
            self.listener.stop()  # no loop to steer; the commands hold the mic open
        self._show("🎤 Listening…", transient=False)

    @property
    def steering(self) -> str | None:
        """The folder whose prompt an open mic is steering, or ``None``."""
        return self._steering

    def steer(self, key: str | None) -> None:
        """Give voice a loop's prompt to steer, or take the last one away, and
        open or close the steering half of the mic to match."""
        self._steering = key
        self.sync()

    def re_home(self, key: str, target: str) -> None:
        """The steered loop moved to another settings folder: follow it there.

        Nothing else changes — what the mic is listening for is the same, and
        the steering reads the folder at each utterance rather than closing over
        it — so this does not re-open the listener."""
        if self._steering == key:
            self._steering = target

    # --- the caption --------------------------------------------------------

    def say(self, message: str) -> None:
        """Flash a line on the caption. The shows use this when there is no show
        up to put it in the corner of."""
        self._show(message, transient=True)

    def _show(self, text: str, *, transient: bool) -> None:
        self.status.setText(text)
        self.status.show()
        if transient:
            self._flash_timer.start(_FLASH_MS)  # then revert to the idle caption
        else:
            self._flash_timer.stop()

    def _revert(self) -> None:
        if self._working_status:
            # A request is still being worked out, so the caption goes back to
            # saying so rather than to the idle line: whatever flashed over the
            # promise, the promise is still the truest thing this pane has to
            # say, and "Listening…" over an app mid-request reads as a request
            # that was dropped.
            self._show(self._working_status, transient=False)
        elif self.listening():  # still listening
            self._show("🎤 Listening…", transient=False)
        else:
            self.status.hide()

    def _on_heard(self, text: str) -> None:
        """Say what the mic heard — a command in the words the app knows it by,
        anything else as it was transcribed.

        Whisper renders a command word a dozen ways and the matcher answers to
        all of them, so the transcription of one is a misspelling of a word that
        was understood perfectly well: "gunow it" printed over a caption that
        then goes and makes a Genau clip. The spelling it was recognized as is
        the truthful thing to show
        (:func:`~origenerator.gallery.voice_commands.recognized_spelling`).
        """
        if any(char.isalpha() for char in text):
            self._say_both(
                f"🎤 heard: “{gallery.recognized_spelling(text) or text}”")

    def _on_edited(self, _new_prompt: str) -> None:
        self._say_both("🎤 ✓ prompt updated")

    def _on_error(self, message: str) -> None:
        self._say_both(f"🎤 {message}")

    def _say_both(self, message: str) -> None:
        """Put what voice heard or hit in front of whoever is listening.

        Both places, because they are different screens: this pane's caption for
        someone working in the window, and the show's own corner for someone
        watching a slideshow — who can see nothing of this window at all, and
        for whom a mic that heard nothing and one that heard the wrong words
        look exactly alike.

        A spoken line, not an answer to a request — which matters while one is
        being worked out, because both surfaces are then holding a promise about
        that work, and a line said over one has to fade back to it rather than
        take its place.
        """
        self._show(message, transient=True)
        self._shows.note_voice_command(message)

    # --- one utterance ------------------------------------------------------

    def run_spoken_command(self, text: str) -> bool:
        """Run a command the HOSTING session heard, and say whether it was one.

        Fun Time owns the microphone while this app is hosted — one mic, one
        transcription — so its recognizer hears "landscape favorites", posts the
        words on this app's channel, and they are matched here against this
        app's own vocabulary: the session cannot know which shelves this tree
        has or which detail parts have detectors installed.

        The order is this app's own mic's (``VoiceSteering._interpret``).  A
        whole-utterance word is that command first — "landscape enhanced only"
        turns the show's switch, and left to the looser picture matcher it
        would read as "enhance" with a word after it — so long as no request
        is being said.  Then the request, which has first refusal over the
        rest: "Request … over" runs to as many utterances as the speaker takes
        breaths, so a matcher that only ever saw one at a time could not hear a
        sentence said in three; while one is open the dictation swallows what
        it hears, which is what keeps the words of a request from also matching
        a command.  The side is split off for the dictation — it rides every
        utterance the session posts, and fed in it would become the first word
        of the request instead of the region the request is about.
        """
        bare = self.listener.bare_command(text)
        if bare is not None:
            self.on_command(bare)
            return True
        side, rest = split_side(text)
        spoken = self.listener.push_dictation(rest)
        if spoken is not None:
            self.on_spoken_request(spoken, side=side)
            return True
        matched = match_voice_command(text)
        if matched is None:
            logger.info("Voice (from the session): %r matched no command", text)
            return False
        self.on_command(matched)
        return True

    def on_command(self, matched) -> None:
        """One recognized utterance: a shelf to play, a show command, a bare
        word about the app or the slide in front of the speaker, or an order
        about the picture — each with the side it named, if it named one.

        An order about the picture always arrives wrapped in a
        :class:`SurfaceCommand`, whether or not a side was said: the wrapper is
        how the side travels, and the matchers put every one of them in it.
        """
        if isinstance(matched, ShelfCommand):
            self._shows.play_shelf(matched)
        elif isinstance(matched, ShowControl):
            self._shows.run_show_command(matched.command, matched.side)
        elif isinstance(matched, SurfaceCommand):
            if isinstance(matched.command, AppCommand):
                self._run_app_command(matched.command, matched.side)
            else:
                self._on_picture_command(matched)
        elif isinstance(matched, AppCommand):
            self._run_app_command(matched)
        elif isinstance(matched, DialSetting):
            self._set_motion_dial(matched)
        else:
            # The two matchers between them produce exactly the five above. A
            # sixth kind arriving is a new matcher nobody wired through to here,
            # and dropping it silently is how that goes unnoticed for a release.
            logger.warning("Voice: no arm for a matched %s", type(matched).__name__)

    # --- the bare vocabulary: a shelf, a switch, a dial, or the slide --------

    def _run_app_command(self, command: AppCommand, side: str | None = None) -> None:
        """One bare spoken word.

        Four kinds, and which it is decides where it lands: a shelf name stands
        the tree in that shelf, a switch word flips one of the app-wide
        switches, a dial word turns the motion — and everything else is about
        whatever surface is in front of the speaker, which is the fullscreen
        show while one is up and the gallery otherwise.
        """
        if command in _SHELVES:
            self._go_to_shelf(command, side)
        elif command in _FILTERS:
            self._shows.filter_enhanced(_FILTERS[command], side)
        elif command in _SWITCHES:
            self._flip_switch(command)
        elif command in _MOTION:
            self._turn_motion_dial(command)
        elif self._shows.showing is not None and command in _ABOUT_THE_SLIDE:
            self._shows.run_on_slide(command)
        else:
            self._run_in_gallery(command)

    def _go_to_shelf(self, command: AppCommand, side: str | None = None) -> None:
        """Stand in the shelf a spoken name asks for, exactly as clicking its
        row does.

        Said over a show it still moves — the tree is under the show, and the
        move is what the show leaves you standing in — so the answer says which
        shelf rather than refusing a command whose whole effect is out of sight.

        Every shelf has two rows now, one per side, so the utterance's own side
        picks which; unsided, the host takes the tree's own answer for the
        folder — the same row a click would have landed on.
        """
        key = _SHELVES[command]
        label = self._host.shelf_label(key)
        if not self._host.stand_in_shelf(key, side):
            # Recents and Starred appear only once there is one
            self._shows.answer(f"🎤 no {label} shelf yet")
            return
        self._shows.answer(f"🎤 {label}")

    def _flip_switch(self, command: AppCommand) -> None:
        """Set one of the app-wide switches, through its button rather than
        around it — a spoken switch is the same event as a clicked one, so the
        bank lights the same way and nothing has to be kept in step.

        "Mic off" is the one with no way back: a shut mic hears nothing, so the
        button is what turns it on again. Its answer is still worth saying —
        with a show up it lands in the show's corner, where the bank is not
        visible to say it instead.
        """
        switch, want, name = _SWITCHES[command]
        button = self._switches[switch]
        if button is None:  # hosted: the session owns the audio bed and the mic
            self._shows.answer(f"🎤 {name} is the session's here")
            return
        if not button.isEnabled():
            self._shows.answer(f"🎤 {name} can't be switched here")
            return
        on = (not button.isChecked()) if want is None else want
        button.setChecked(on)  # its toggled signal is what does the work
        self._shows.answer(f"🎤 {name} {'on' if on else 'off'}")

    def _turn_motion_dial(self, command: AppCommand) -> None:
        """Turn one of the motion's dials — the move its key makes.

        The driver is app-wide, so this answers from the gallery and from a show
        alike, and the dials read the same whether or not the device is running:
        a motion can be set up before it is started, exactly as the panel allows.
        """
        turn, argument = self._motion_turns[command]
        turn() if argument is None else turn(argument)
        self._shows.answer(f"🎤 {self._motion.status_text()}")

    def _set_motion_dial(self, setting: DialSetting) -> None:
        """Put one of the motion's dials where a spoken number asks for it.

        The nudges above are for a motion that is nearly right; this is for one
        that is not, and it is the same driver either way — so it answers with
        the same line, and from the gallery and a show alike. The dial does its
        own clamping, which is why "min speed" can say nought and land on the
        slowest the device actually moves at.
        """
        self._dial_setters[setting.dial](setting.value)
        self._shows.answer(f"🎤 {self._motion.status_text()}")

    def _run_in_gallery(self, command: AppCommand) -> None:
        """A word said with no show to take it: the bank button it names, aimed
        exactly as a click on it would be."""
        if command in (AppCommand.LOCK, AppCommand.UNLOCK):
            self._shows.answer(f"🎤 {command.value} is a slideshow's — none is up")
            return
        button, act = self._bank[command]
        self._press_bank_button(button, act, _BANK_REFUSALS[command])

    def _press_bank_button(self, button, act, refusal: str | None = None) -> None:
        """Do what a bank button does, and answer in that button's own words.

        Its tip already says what it will do to what is in front of you — "Star
        3 items", "Undo: delete of 2 items" — which is precisely what a speaker
        who is not looking at the bank needs told back, and it cannot drift from
        what the button does. A button that is away or dead says why instead of
        quietly doing nothing: ``refusal``, or its tip where that already reads
        as one.
        """
        if button.isHidden() or not button.isEnabled():
            self._shows.answer(f"🎤 {refusal or button.toolTip()}")
            return
        said = button.toolTip()  # read first: the action re-aims the bank
        act()
        self._shows.answer(f"🎤 {said}")

    def _on_picture_command(self, command) -> None:
        """A spoken command about the picture on screen: a targeted "fix <part>"
        (or several parts, or "fix all"), "enhance" for the better version of
        it, or "genau it" to animate it as a Genau clip.

        A named side takes that region's show — hosted, two shows run at once
        and neither is the active window, so naming one is the only way to say
        which picture is meant.  Unnamed, it goes to whichever show is up.
        Answered out of the show's own note — the speaker is looking at it, not
        at this pane. Said with no show up, "enhance" falls to the bank button of
        the same name; the other two have no "on screen" to act on, and the
        utterance has already been claimed as a command by the time it gets here,
        so the caption says so rather than letting it vanish."""
        show = self._shows.surface_for(command.side)
        if show is None:
            if command.command == gallery.ENHANCE_COMMAND:
                # The word names a bank button too, and with no picture filling
                # the screen the button is what it means — aimed the way a click
                # aims it, at the picked thumbnails else the folder's unenhanced
                # images. A refusal here would be a dead end where there is a
                # perfectly good thing to do.
                self._press_bank_button(*self._enhance)
                return
            wants = (_WANTS.get(command.command)
                     or f"a {name_parts(command.command)} fix")
            self._show(f"🎤 {wants} needs a picture on screen", transient=True)
            return
        target = show.voice_target()
        if command.command == gallery.GENAU_COMMAND:
            prompt_id, message = self._host.genau_it(target)
        elif command.command == gallery.ENHANCE_COMMAND:
            prompt_id, message = self._host.enhance_it(target)
        else:
            prompt_id, message = self._host.fix_parts(target, command.command)
        show.note_voice_run(prompt_id, message)

    # --- spoken requests: "Request … over" over whatever is on screen --------

    def on_spoken_request(self, spoken, side: str | None = None) -> None:
        """One step of a spoken request — from the mic's dictation, or from the
        hosting session's channel with the region it was said to.

        While it is still being said the show holds and the corner says so;
        finished, it queues a revision of the item it was opened over. The
        target is taken at the opening step and kept, because a request is about
        the picture that prompted it, not whatever is up when the words run out.

        Hosted, *side* is what makes "the picture" a picture at all: two shows
        run at once on the satellite regions and neither is the active window,
        so the region named is the only thing that says which one the words are
        about.
        """
        show = self._shows.surface_for(side)
        if self._request_target is None:
            # Taken at the first step of the request, whichever step that is —
            # "Request, no hat, over" is a whole one in a single breath.
            self._request_target = self._target_of(show)
        if spoken.listening:
            self._hold_for_request(show, spoken)
            return
        target = self._request_target
        self._request_target = None
        self._hold_for_request(show, spoken)
        if spoken.state != COMPLETED:  # given up on — the terminator never came
            self._answer_request(show, "🎤 request dropped — never heard “over”", spoken)
            return
        self._begin_request(target, spoken, side)

    def _target_of(self, show) -> str | None:
        """What a request just opened is about: the slide filling the screen
        when a show is up, else the generation picked in the gallery."""
        if show is not None:
            return show.voice_target()
        return self._host.selected_generation()

    def _hold_for_request(self, show, spoken) -> None:
        """Hold (or release) the show while the sentence is being said, and say
        so — in the show's own corner when one is up, since that is where the
        speaker is looking, and in this pane's voice caption otherwise."""
        note = f"🎤 Request: {spoken.text}…" if spoken.listening else ""
        if show is not None:
            show.hold_for_request(spoken.listening, note)
        elif spoken.listening:
            self._show(note or "🎤 Request…", transient=False)

    def _answer_request(self, show, message: str, spoken, *,
                        working: bool = False) -> None:
        """Say what *spoken* did, where the speaker is looking.

        *working* is the one line that is not an answer but a promise of one, so
        it is held rather than flashed: the working-out may go to the local LLM,
        and a surface that empties while the app is still at it says the request
        was dropped. Only that request's own answer takes the promise down —
        an answer to another one flashes over it and leaves it standing.

        The promise is made on the surface the speaker was looking at, and taken
        down on both: a show can open while the pool is still working, and the
        answer then lands somewhere other than where the promise was made.
        """
        if working:
            self._working_status = "" if show is not None else message
            self._working_request = spoken
        elif spoken is self._working_request:
            promised, self._working_status = self._working_status, ""
            self._working_request = None
            if promised and self.status.text() == promised:
                self._revert()  # it was still promising this pane
        if show is not None:
            show.note_request(message, spoken, working=working)
        else:
            self._show(message, transient=not working)

    def _begin_request(self, prompt_id: str | None, spoken,
                       side: str | None = None) -> None:
        """Start working out what a finished request changes.

        The working-out goes to the pool because it may have to ask the local
        LLM which of the prompt's own terms the speaker meant, and a second of
        network wait on this thread is a second of frozen slideshow — at the one
        moment the app must not stutter. Whatever can be answered without that
        (nothing on screen, a recipe this app can't rebuild) is answered here,
        so a request that was never going to run doesn't wait on a model.

        The side rides the pool's context so the answer comes back to the same
        region the request was said to — seconds later, with two shows running,
        it is the only thing that still says which.
        """
        row = self._db.get_generation(prompt_id) if prompt_id else None
        show = self._shows.surface_for(side)
        if row is None:
            self._answer_request(
                show, "🎤 nothing on screen to request a change to", spoken)
            return
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or self._client is None:
            self._answer_request(
                show, "🎤 this one can't be re-made, so there's nothing to revise",
                spoken)
            return
        params = filled_params(row, workflow)
        self._answer_request(show, f"🎤 working out “{spoken.text}”…", spoken,
                             working=True)
        QThreadPool.globalInstance().start(ReviseTask(
            self._revision, (row, workflow, params, spoken, side),
            params.get("positive_prompt", ""), params.get("negative_prompt", ""),
            spoken.text,
        ))

    def _on_revised(self, context, revision) -> None:
        """The revision came back from the pool: queue it, and say what it did.

        The show is looked up now rather than remembered, so an answer that took
        a couple of seconds still lands wherever the speaker is looking — on
        the region the request named, hosted, since two of them are up.
        """
        row, workflow, params, spoken, side = context
        show = self._shows.surface_for(side)
        if revision is None:
            self._answer_request(
                show, f"🎤 didn't catch what to change in “{spoken.text}”", spoken)
            return
        if not revision.changed:
            self._answer_request(
                show, f"🎤 “{revision.term}” is already how you asked for it", spoken)
            return
        self._answer_request(show, self._host.queue_request(
            row, workflow, params, spoken, revision), spoken)
