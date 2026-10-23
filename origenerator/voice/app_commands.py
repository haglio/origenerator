"""What a bare spoken word asks of the app — a collection, a button, the picture.

Fun Time's Funestras answer single words: "weird" condemns the clip, "lock" holds
it, "next" walks on. The same words work here, and beside them the rest of what
the toolbar does and the names of the collections that lead the tree — so
"experiments" stands you in the Experiments collection exactly as clicking its row
does, and "undo" takes back the last delete without reaching for the mouse.

Every phrase is matched against the WHOLE utterance, and that is the only thing
making a one-word vocabulary safe on a mic that is also dictating prompts. The
looser matchers can afford filler words because each carries a word no prompt
says — a fix leads with "fix", a slideshow command names the slideshow — but a bare
"lock" carries nothing, so it gets no slack at all: "lock" is the command and "a
lock of hair over her eye" is a prompt.

Most of the vocabulary is a fixed set of things to ask for, and one part of it
is not: the motion's bars take a number said outright — "amp fifty", "max
speed" — so those phrases answer with a :class:`BarSetting` carrying the bar
and the value rather than a constant each for three dozen combinations. Both come
back from the one matcher, and the caller tells them apart by type.

**Where a command lands is the surface in front of the speaker**, not a fixed
target. A fullscreen slideshow has the floor while one is up and the gallery has it
otherwise, which is Fun Time's active-side idea with two sides: "back" steps a
slide over a slideshow and walks the history in the gallery, because in both places
it means the one before. The app-wide switches (the mic, Origenerator Radio, the
OSR2) and the motion's own bars belong to no surface and answer from either.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from origenerator.voice.text import words


class AppCommand(Enum):
    """One thing a bare spoken word asks the app for."""

    # The collections that lead the tree, each reached by its own name.
    RECENTS = "recents"
    FAVORITES = "favorites"
    EXPERIMENTS = "experiments"
    TRASH = "trash"

    # The transport, aimed at whichever surface has the floor: a slide either
    # way over a slideshow, a step through the history in the gallery.
    BACK = "back"
    FORWARD = "forward"

    # What you do to what is in front of you.
    CULL = "cull"        # Fun Time's "weird": take this one away
    LOCK = "lock"        # lock the slide (which favorites it and asks for the better version)
    UNLOCK = "unlock"    # let it go again
    FAVORITE = "favorite"
    UNDO = "undo"
    REDO = "redo"
    GROUP = "group"      # the picked folders into a folder of their own

    # The app-wide switches. Each takes a bare toggle and an explicit on/off,
    # so a speaker who knows which way they want it never has to look first.
    AUTO = "auto"
    AUTO_ON = "auto_on"
    AUTO_OFF = "auto_off"
    RADIO = "radio"
    RADIO_ON = "radio_on"
    RADIO_OFF = "radio_off"
    DRIVE = "drive"
    DRIVE_ON = "drive_on"
    DRIVE_OFF = "drive_off"
    # No "mic on": a muted recognizer hears nothing, so there is no spoken way
    # back — the toolbar's switch is it. Fun Time's mic works the same way.
    MIC_OFF = "mic_off"

    # What a slideshow may play: the switch beside F-mode on its HUD, which keeps
    # only the pictures it has enhanced. Said either way round rather than as
    # one toggle: a speaker mid-show is not looking at the HUD to see which way
    # it is set, and "filter enhanced" that turned the filter OFF half the time
    # would be a command nobody could rely on. "clear filter" is the way back
    # out of both switches at once.
    FILTER_ENHANCED = "filter_enhanced"
    FILTER_OFF = "filter_off"

    # The OSR2 motion's bars, in Fun Time's own words. The driver is app-wide,
    # so these answer from the gallery and from a slideshow alike.
    SPEED_UP = "speed_up"
    SPEED_DOWN = "speed_down"
    AMP_UP = "amp_up"
    AMP_DOWN = "amp_down"
    CENTER_UP = "center_up"
    CENTER_DOWN = "center_down"
    NEXT_SHAPE = "next_shape"
    PREVIOUS_SHAPE = "previous_shape"
    LEARNED = "learned"
    LEARNED_ON = "learned_on"
    LEARNED_OFF = "learned_off"


@dataclass(frozen=True)
class BarSetting:
    """One of the motion's bars, said outright rather than nudged.

    "speed up" walks a bar five at a time, which is the right shape when the
    motion is nearly where you want it and the wrong one when it is not — from
    the far end, arriving takes a dozen utterances and every one of them has to
    be heard. Fun Time answers that with the number said plainly ("amp fifty",
    "max speed"), and this is that vocabulary: the bar, the value, and nothing
    about how far it has to travel to get there.

    ``bar`` is the driver's own word for it — ``speed``, ``amp``, ``center`` —
    and ``value`` is on the 0-100 scale all three share
    (:mod:`funestra.robot_hand` clamps, so "min speed" landing under the
    bar's own floor is the bar's business, not the vocabulary's).
    """

    bar: str
    value: int


# phrase -> command. Every key is a whole utterance, lowercased, its punctuation
# already dropped: what :func:`match_app_command` reduces a transcription to.
# A value is an :class:`AppCommand` for the things there is one of, and a
# :class:`BarSetting` for the numeric grid, where a constant each would be three
# dozen names for what is really one command with a number in it.
_PHRASES: dict[str, AppCommand | BarSetting] = {}


def _say(command: AppCommand | BarSetting, *phrases: str) -> None:
    """Teach the vocabulary that each of ``phrases`` asks for ``command``.

    A phrase already spoken for is a programming error rather than a preference
    between two meanings — one of them would silently never happen — so it
    raises here, where the module is imported, instead of at the mic.

    Compared by value, not identity: two ways of saying the same bar setting
    ("amp fifty" and "amp 50") arrive as two equal :class:`BarSetting`
    objects built at different moments, and that is agreement, not collision.
    """
    for phrase in phrases:
        taken = _PHRASES.get(phrase)
        if taken is not None and taken != command:
            raise RuntimeError(
                f"“{phrase}” already means {taken}, cannot also mean {command}"
            )
        _PHRASES[phrase] = command


# The collections, by name. Each answers bare — which is the whole point, since the
# name is what the row says — and to a verb in front of it or the word "collection"
# after it, for a speaker who would rather say a sentence.
_COLLECTION_NAMES: dict[AppCommand, tuple[str, ...]] = {
    AppCommand.RECENTS: ("recents", "recent"),
    AppCommand.FAVORITES: ("favorites",),
    AppCommand.EXPERIMENTS: ("experiments", "experiment"),
    AppCommand.TRASH: ("trash",),
}
_COLLECTION_VERBS = ("go to", "open", "show")
# Said on its own, this one already plays the collection, or narrows a slideshow to it
# (origenerator.voice.commands.COLLECTION_KEYS), so standing in it takes the sentence.
_NEVER_SAID_BARE = frozenset({"favorites"})
for _collection, _names in _COLLECTION_NAMES.items():
    for _name in _names:
        _say(_collection, *(() if _name in _NEVER_SAID_BARE else (_name,)), f"{_name} collection",
             *(f"{_verb} {_name}" for _verb in _COLLECTION_VERBS))

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
_say(AppCommand.FAVORITE, "favorite", "favorite it", "favorite this")
_say(AppCommand.UNDO, "undo")
_say(AppCommand.REDO, "redo")
_say(AppCommand.GROUP, "group", "group folders")

# The app-wide switches: "<name>" flips it, "<name> on" and "<name> off" say
# which way — the same three shapes Fun Time gives its own toggles.
for _words, (_toggle, _on, _off) in (
    (("auto", "auto generate"), (AppCommand.AUTO, AppCommand.AUTO_ON, AppCommand.AUTO_OFF)),
    (("radio",), (AppCommand.RADIO, AppCommand.RADIO_ON, AppCommand.RADIO_OFF)),
    (("drive", "motion"), (AppCommand.DRIVE, AppCommand.DRIVE_ON, AppCommand.DRIVE_OFF)),
):
    for _word in _words:
        _say(_toggle, _word)
        _say(_on, f"{_word} on")
        _say(_off, f"{_word} off")
_say(AppCommand.MIC_OFF, "mic off", "voice off")
# Fun Time's word for the console's control-off button, which is this switch
# off -- the letters and the number however whisper writes them.
_say(AppCommand.DRIVE_OFF, "osr 2 off", "o s r 2 off", "osr two off", "o s r two off")
for _osr2 in ("osr 2", "o s r 2", "osr two", "o s r two"):
    _say(AppCommand.DRIVE_OFF, f"{_osr2} control off")
    _say(AppCommand.DRIVE_ON, f"{_osr2} control on")

# The slideshow's own narrowing filter, in Fun Time's own grammar: "filter <what to
# keep>" turns one on, and "clear filter" is the way back to all of it — the
# very phrase the satellites answer, so one gesture has one wording in both
# rooms. "Upscales" is what the enhanced pictures are called at the desk, so it
# is heard too; inside a Fun Time session the room's recognizer has no such
# word, and "enhanced only" is the one that carries there.
_say(AppCommand.FILTER_ENHANCED, "filter enhanced", "enhanced filter",
     "filter enhanced only", "enhanced only",
     "upscales", "upscales only", "filter upscales", "upscaled only")
_say(AppCommand.FILTER_OFF, "clear filter", "no filter", "filter off")

# The motion's bars, said the way Fun Time says them, so the muscle memory
# carries between the two apps the way the keys already do.
_say(AppCommand.SPEED_UP, "speed up")
_say(AppCommand.SPEED_DOWN, "speed down", "slow down")
_say(AppCommand.AMP_UP, "amp up")
_say(AppCommand.AMP_DOWN, "amp down")
_say(AppCommand.CENTER_UP, "center up")
_say(AppCommand.CENTER_DOWN, "center down")
_say(AppCommand.NEXT_SHAPE, "next shape")
_say(AppCommand.PREVIOUS_SHAPE, "previous shape")
_say(AppCommand.LEARNED, "human inspired")
_say(AppCommand.LEARNED_ON, "human inspired on")
_say(AppCommand.LEARNED_OFF, "human inspired off")

MOTION_MOVES: dict[AppCommand, tuple[str, int | bool | None]] = {
    AppCommand.SPEED_UP: ("adjust_speed", 5),
    AppCommand.SPEED_DOWN: ("adjust_speed", -5),
    AppCommand.AMP_UP: ("adjust_amplitude", 10),
    AppCommand.AMP_DOWN: ("adjust_amplitude", -10),
    AppCommand.CENTER_UP: ("adjust_center", 5),
    AppCommand.CENTER_DOWN: ("adjust_center", -5),
    AppCommand.NEXT_SHAPE: ("cycle_shape", 1),
    AppCommand.PREVIOUS_SHAPE: ("cycle_shape", -1),
    AppCommand.LEARNED: ("toggle_learned", None),
    AppCommand.LEARNED_ON: ("set_learned", True),
    AppCommand.LEARNED_OFF: ("set_learned", False),
}

AUTO_SWITCH, RADIO_SWITCH, DRIVE_SWITCH, MIC_SWITCH = "auto", "radio", "drive", "mic"
SWITCHES: dict[AppCommand, tuple[str, bool | None, str]] = {
    AppCommand.AUTO: (AUTO_SWITCH, None, "auto-generate"),
    AppCommand.AUTO_ON: (AUTO_SWITCH, True, "auto-generate"),
    AppCommand.AUTO_OFF: (AUTO_SWITCH, False, "auto-generate"),
    AppCommand.RADIO: (RADIO_SWITCH, None, "Origenerator Radio"),
    AppCommand.RADIO_ON: (RADIO_SWITCH, True, "Origenerator Radio"),
    AppCommand.RADIO_OFF: (RADIO_SWITCH, False, "Origenerator Radio"),
    AppCommand.DRIVE: (DRIVE_SWITCH, None, "OSR2"),
    AppCommand.DRIVE_ON: (DRIVE_SWITCH, True, "OSR2"),
    AppCommand.DRIVE_OFF: (DRIVE_SWITCH, False, "OSR2"),
    AppCommand.MIC_OFF: (MIC_SWITCH, False, "the mic"),
}
SWITCHES_A_HOST_HOLDS = (RADIO_SWITCH, DRIVE_SWITCH, MIC_SWITCH)

# --- the bars said outright: "amp fifty", "max speed" ----------------------
#
# The bar's name and a number, which is Fun Time's grid exactly. Tens only,
# because a bar is a feel rather than a figure and "amp fifty five" is a
# sentence nobody says out loud — the nudges above are what fine tuning is for.
_BARS = ("speed", "amp", "center")
_TENS: dict[str, int] = {
    "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "one hundred": 100,
}
# Both ends of each bar by name, so the far end is one utterance rather than a
# number nobody has to remember. What "min" means is the bar's to say: speed
# floors at its own slowest rather than at a stop.
_EXTREMES: dict[str, int] = {"min": 0, "max": 100}

for _bar in _BARS:
    for _word, _value in _TENS.items():
        # Said and written. Whisper renders a spoken number as digits about as
        # often as words — "amp fifty" comes back "amp 50" — and a vocabulary
        # that knows only one of the two hears half of what was said.
        _say(BarSetting(_bar, _value), f"{_bar} {_word}", f"{_bar} {_value}")
    for _label, _value in _EXTREMES.items():
        _say(BarSetting(_bar, _value), f"{_label} {_bar}")


def phrases_heard_only_outright() -> frozenset[str]:
    """What a recognizer's near miss is never repaired into: the switch with no spoken way
    back, and the word that takes a picture away."""
    return frozenset(phrase for phrase in spoken_phrases()
                     if _PHRASES[phrase] in (AppCommand.MIC_OFF, AppCommand.CULL))


def spoken_phrases() -> frozenset[str]:
    """Every phrase of the vocabulary as a speaker says it, for a recognizer that
    listens for words: the spellings with digits in them are whisper's."""
    return frozenset(phrase for phrase in _PHRASES
                     if not any(character.isdigit() for character in phrase))


def _answered_when_hosted(command: AppCommand | BarSetting) -> bool:
    if isinstance(command, BarSetting) or command in MOTION_MOVES:
        return False
    return command not in SWITCHES or SWITCHES[command][0] not in SWITCHES_A_HOST_HOLDS


def phrases_answered_when_hosted() -> frozenset[str]:
    return frozenset(phrase for phrase in spoken_phrases()
                     if _answered_when_hosted(_PHRASES[phrase]))


def match_app_command(text: str) -> AppCommand | BarSetting | None:
    """The command an utterance is, or ``None`` when it is not one of them.

    The whole utterance has to be the phrase. Whisper's punctuation and case are
    its own invention and go; nothing else does, so a sentence that happens to
    contain a command word is left alone to steer the prompt.

    Digits survive that reduction, unlike the punctuation around them: whisper
    writes a spoken number either way, so "amp 50" and "amp fifty" are the same
    utterance said once and it is not the speaker who chose which.
    """
    return _PHRASES.get(" ".join(words(text, keep_digits=True)))
