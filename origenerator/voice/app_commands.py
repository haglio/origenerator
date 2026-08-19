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

Most of the vocabulary is a fixed set of things to ask for, and one part of it
is not: the stroke's dials take a number said outright — "amp fifty", "max
speed" — so those phrases answer with a :class:`DialSetting` carrying the dial
and the value rather than a member each for three dozen combinations. Both come
back from the one matcher, and the caller tells them apart by type.

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
from dataclasses import dataclass
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
    CRUISE_ON = "cruise_on"
    CRUISE_OFF = "cruise_off"
    OFFSET = "offset"


@dataclass(frozen=True)
class DialSetting:
    """One of the stroke's dials, said outright rather than nudged.

    "speed up" walks a dial five at a time, which is the right shape when the
    stroke is nearly where you want it and the wrong one when it is not — from
    the far end, arriving takes a dozen utterances and every one of them has to
    be heard. Fun Time answers that with the number said plainly ("amp fifty",
    "max speed"), and this is that vocabulary: the dial, the value, and nothing
    about how far it has to travel to get there.

    ``dial`` is the driver's own word for it — ``speed``, ``amp``, ``center`` —
    and ``value`` is on the 0-100 scale all three share
    (:mod:`player_core.direct_control` clamps, so "min speed" landing under the
    dial's own floor is the dial's business, not the vocabulary's).
    """

    dial: str
    value: int


# phrase -> command. Every key is a whole utterance, lowercased, its punctuation
# already dropped: what :func:`match_app_command` reduces a transcription to.
# A value is an :class:`AppCommand` for the things there is one of, and a
# :class:`DialSetting` for the numeric grid, where a member each would be three
# dozen names for what is really one command with a number in it.
_PHRASES: dict[str, AppCommand | DialSetting] = {}


def _say(command: AppCommand | DialSetting, *phrases: str) -> None:
    """Teach the vocabulary that each of ``phrases`` asks for ``command``.

    A phrase already spoken for is a programming error rather than a preference
    between two meanings — one of them would silently never happen — so it
    raises here, where the module is imported, instead of at the mic.

    Compared by value, not identity: two ways of saying the same dial setting
    ("amp fifty" and "amp 50") arrive as two equal :class:`DialSetting`
    objects built at different moments, and that is agreement, not collision.
    """
    for phrase in phrases:
        taken = _PHRASES.get(phrase)
        if taken is not None and taken != command:
            raise RuntimeError(
                f"“{phrase}” already means {taken}, cannot also mean {command}"
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
# Cruise takes the explicit pair too, the way every switch above does: hands-free
# is the one setting you reach for without looking, so a speaker who wants it ON
# should never have to find out which way it is standing first.
_say(AppCommand.CRUISE_ON, "cruise on")
_say(AppCommand.CRUISE_OFF, "cruise off")
_say(AppCommand.OFFSET, "offset")

# --- the dials said outright: "amp fifty", "max speed" ----------------------
#
# The dial's name and a number, which is Fun Time's grid exactly. Tens only,
# because a dial is a feel rather than a figure and "amp fifty five" is a
# sentence nobody says out loud — the nudges above are what fine tuning is for.
_DIALS = ("speed", "amp", "center")
_TENS: dict[str, int] = {
    "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "one hundred": 100,
}
# Both ends of each dial by name, so the far end is one utterance rather than a
# number nobody has to remember. What "min" means is the dial's to say: speed
# floors at its own slowest rather than at a stop.
_EXTREMES: dict[str, int] = {"min": 0, "max": 100}

for _dial in _DIALS:
    for _word, _value in _TENS.items():
        # Said and written. Whisper renders a spoken number as digits about as
        # often as words — "amp fifty" comes back "amp 50" — and a vocabulary
        # that knows only one of the two hears half of what was said.
        _say(DialSetting(_dial, _value), f"{_dial} {_word}", f"{_dial} {_value}")
    for _label, _value in _EXTREMES.items():
        _say(DialSetting(_dial, _value), f"{_label} {_dial}")


def match_app_command(text: str) -> AppCommand | DialSetting | None:
    """The command an utterance is, or ``None`` when it is not one of them.

    The whole utterance has to be the phrase. Whisper's punctuation and case are
    its own invention and go; nothing else does, so a sentence that happens to
    contain a command word is left alone to steer the prompt.

    Digits survive that reduction, unlike the punctuation around them: whisper
    writes a spoken number either way, so "amp 50" and "amp fifty" are the same
    utterance said once and it is not the speaker who chose which.
    """
    return _PHRASES.get(" ".join(re.findall(r"[a-z]+|\d+", (text or "").lower())))


# What the bias leaves out. The initial prompt is whisper's hint about the words
# it is about to hear, and it has a hard budget — 224 tokens, past which
# faster-whisper keeps the TAIL and silently drops the head, which here is the
# fix vocabulary that needs the hint most (``tests/test_voice_bias.py`` guards
# the total). So the budget goes to words whisper would otherwise get wrong:
# "recents", "genau", "amp". Plain connectives and numbers are not those — it
# has never once mis-heard "fifty" — and listing them only crowds out a word
# that would have been mis-heard.
_BIAS_SKIP = frozenset(
    ("go", "to", "it", "this", "shelf", "on", "off", "min", "max", "one", "hundred")
    + tuple(_TENS)
    + tuple(str(value) for value in _TENS.values())
)


def app_command_bias() -> str:
    """Every word the vocabulary uses, as part of whisper's initial prompt.

    Derived from the phrases rather than listed again, so a command added above
    reaches the transcriber without a second list to keep in step — the same
    reason the fix vocabulary derives its bias from the parts. The connectives
    and numbers of ``_BIAS_SKIP`` are the exception, and being a skip list
    rather than a keep list is what preserves that: a new command's own words
    still arrive on their own.
    """
    words: dict[str, None] = {}  # an ordered set: first-said order reads best
    for phrase in _PHRASES:
        for word in phrase.split():
            if word not in _BIAS_SKIP:
                words.setdefault(word, None)
    return "App commands: " + ", ".join(words) + "."
