"""What a bare spoken word asks of the app — a shelf, a button, the picture.

Fun Time's players answer single words: "weird" condemns the clip, "lock" holds
it, "next" walks on. The same words work here, and beside them the rest of what
the toolbar does and the names of the shelves that lead the tree — so
"experiments" stands you in the Experiments shelf exactly as clicking its row
does, and "undo" takes back the last delete without reaching for the mouse.

Every phrase is matched against the WHOLE utterance, and that is the only thing
making a one-word vocabulary safe on a mic that is also dictating prompts. The
looser matchers can afford filler words because each carries a word no prompt
says — a fix leads with "fix", a show command names the slideshow — but a bare
"lock" carries nothing, so it gets no slack at all: "lock" is the command and "a
lock of hair over her eye" is a prompt.

**Where a command lands is the surface in front of the speaker**, not a fixed
target. A fullscreen show has the floor while one is up and the gallery has it
otherwise, which is Fun Time's active-side idea with two sides: "back" steps a
slide over a show and walks the history in the gallery, because in both places
it means the one before. The app-wide switches (the mic, the audio bed, the
OSR2) and the stroke's own knobs belong to no surface and answer from either.

One word is deliberately missing. The Requests shelf answers to the plural
"requests" and never to the singular, because "request" is what opens a spoken
request (:mod:`origenerator.voice.dictation`) and a word cannot both open a
sentence and navigate away from it. :class:`~origenerator.voice.steering.
VoiceSteering` gives this vocabulary its say before a request can open, which is
what lets the plural through; a bare singular still opens the dictation.
"""

import re
from enum import Enum


class AppCommand(Enum):
    """One thing a bare spoken word asks the app for."""

    # The shelves that lead the tree, each reached by its own name.
    RECENTS = "recents"
    STARRED = "starred"
    EXPERIMENTS = "experiments"
    REQUESTS = "requests"
    TRASH = "trash"

    # The transport, aimed at whichever surface has the floor: a slide either
    # way over a show, a step through the history in the gallery.
    BACK = "back"
    FORWARD = "forward"

    # What you do to what is in front of you.
    CULL = "cull"        # Fun Time's "weird": take this one away
    LOCK = "lock"        # hold the slide (which stars it and asks for the better version)
    UNLOCK = "unlock"    # let it go again
    STAR = "star"
    UNDO = "undo"
    REDO = "redo"
    GROUP = "group"      # the picked folders into a folder of their own

    # The app-wide switches. Each takes a bare toggle and an explicit on/off,
    # so a speaker who knows which way they want it never has to look first.
    AUTO = "auto"
    AUTO_ON = "auto_on"
    AUTO_OFF = "auto_off"
    AUDIO = "audio"
    AUDIO_ON = "audio_on"
    AUDIO_OFF = "audio_off"
    DRIVE = "drive"
    DRIVE_ON = "drive_on"
    DRIVE_OFF = "drive_off"
    # No "mic on": a muted recognizer hears nothing, so there is no spoken way
    # back — the toolbar's switch is it. Fun Time's mic works the same way.
    MIC_OFF = "mic_off"

    # The OSR2 stroke's knobs, in Fun Time's own words. The driver is app-wide,
    # so these answer from the gallery and from a show alike.
    SPEED_UP = "speed_up"
    SPEED_DOWN = "speed_down"
    AMP_UP = "amp_up"
    AMP_DOWN = "amp_down"
    CENTER_UP = "center_up"
    CENTER_DOWN = "center_down"
    NEXT_SHAPE = "next_shape"
    PREVIOUS_SHAPE = "previous_shape"
    CRUISE = "cruise"
    OFFSET = "offset"


# phrase -> command. Every key is a whole utterance, lowercased, its punctuation
# already dropped: what :func:`match_app_command` reduces a transcription to.
_PHRASES: dict[str, AppCommand] = {}


def _say(command: AppCommand, *phrases: str) -> None:
    """Teach the vocabulary that each of ``phrases`` asks for ``command``.

    A phrase already spoken for is a programming error rather than a preference
    between two meanings — one of them would silently never happen — so it
    raises here, where the module is imported, instead of at the mic.
    """
    for phrase in phrases:
        taken = _PHRASES.get(phrase)
        if taken is not None and taken is not command:
            raise RuntimeError(
                f"“{phrase}” already means {taken.value}, cannot also mean {command.value}"
            )
        _PHRASES[phrase] = command


# The shelves, by name. Each answers bare — which is the whole point, since the
# name is what the row says — and to a verb in front of it or the word "shelf"
# behind, for a speaker who would rather say a sentence.
_SHELF_NAMES: dict[AppCommand, tuple[str, ...]] = {
    AppCommand.RECENTS: ("recents", "recent"),
    AppCommand.STARRED: ("starred",),
    AppCommand.EXPERIMENTS: ("experiments", "experiment"),
    # The singular is the request dictation's opening word — see the module
    # docstring. Only the plural, which is also what the row is labeled.
    AppCommand.REQUESTS: ("requests",),
    AppCommand.TRASH: ("trash",),
}
_SHELF_VERBS = ("go to", "open", "show")
for _shelf, _names in _SHELF_NAMES.items():
    for _name in _names:
        _say(_shelf, _name, f"{_name} shelf",
             *(f"{_verb} {_name}" for _verb in _SHELF_VERBS))

# The transport. Fun Time's "next"/"previous"/"skip"/"back" all land here,
# because in both rooms they mean the one after and the one before.
_say(AppCommand.BACK, "back", "go back", "previous", "previous slide")
_say(AppCommand.FORWARD, "forward", "go forward", "next", "next slide", "skip")

# What you do to what is in front of you. "weird" is Fun Time's word for a clip
# that has to go, and it means the same here; "delete" says it plainly for
# anyone who never learned the other one.
_say(AppCommand.CULL, "weird", "delete", "delete it")
_say(AppCommand.LOCK, "lock", "hold")
_say(AppCommand.UNLOCK, "unlock", "release")
_say(AppCommand.STAR, "star", "star it", "star this")
_say(AppCommand.UNDO, "undo")
_say(AppCommand.REDO, "redo")
_say(AppCommand.GROUP, "group", "group folders")

# The app-wide switches: "<name>" flips it, "<name> on" and "<name> off" say
# which way — the same three shapes Fun Time gives its own toggles.
for _words, (_toggle, _on, _off) in (
    (("auto", "auto generate"), (AppCommand.AUTO, AppCommand.AUTO_ON, AppCommand.AUTO_OFF)),
    (("audio", "ambient"), (AppCommand.AUDIO, AppCommand.AUDIO_ON, AppCommand.AUDIO_OFF)),
    (("drive", "stroke"), (AppCommand.DRIVE, AppCommand.DRIVE_ON, AppCommand.DRIVE_OFF)),
):
    for _word in _words:
        _say(_toggle, _word)
        _say(_on, f"{_word} on")
        _say(_off, f"{_word} off")
_say(AppCommand.MIC_OFF, "mic off", "voice off")

# The stroke's knobs, said the way Fun Time says them, so the muscle memory
# carries between the two apps the way the keys already do.
_say(AppCommand.SPEED_UP, "speed up")
_say(AppCommand.SPEED_DOWN, "speed down", "slow down")
_say(AppCommand.AMP_UP, "amp up")
_say(AppCommand.AMP_DOWN, "amp down")
_say(AppCommand.CENTER_UP, "center up")
_say(AppCommand.CENTER_DOWN, "center down")
_say(AppCommand.NEXT_SHAPE, "next shape")
_say(AppCommand.PREVIOUS_SHAPE, "previous shape")
_say(AppCommand.CRUISE, "cruise", "cruise control")
_say(AppCommand.OFFSET, "offset")


def match_app_command(text: str) -> AppCommand | None:
    """The command an utterance is, or ``None`` when it is not one of them.

    The whole utterance has to be the phrase. Whisper's punctuation and case are
    its own invention and go; nothing else does, so a sentence that happens to
    contain a command word is left alone to steer the prompt.
    """
    return _PHRASES.get(" ".join(re.findall(r"[a-z]+", (text or "").lower())))


def app_command_bias() -> str:
    """Every word the vocabulary uses, as part of whisper's initial prompt.

    Derived from the phrases rather than listed again, so a command added above
    reaches the transcriber without a second list to keep in step — the same
    reason the fix vocabulary derives its bias from the parts.
    """
    words: dict[str, None] = {}  # an ordered set: first-said order reads best
    for phrase in _PHRASES:
        for word in phrase.split():
            words.setdefault(word, None)
    return "App commands: " + ", ".join(words) + "."
