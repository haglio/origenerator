from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from voice_core.spelling import numbers_as_digits

from origenerator.gallery.collection import collection, spoken_collections
from origenerator.voice.text import words


class AppCommand(Enum):
    BACK = "back"
    FORWARD = "forward"

    CULL = "trash"
    LOCK = "lock"
    UNLOCK = "unlock"
    FAVORITE = "favorite"
    UNDO = "undo"
    REDO = "redo"
    GROUP = "group"

    POPULATE = "populate"
    POPULATE_ON = "populate_on"
    POPULATE_OFF = "populate_off"
    RADIO = "radio"
    RADIO_ON = "radio_on"
    RADIO_OFF = "radio_off"
    DRIVE = "drive"
    DRIVE_ON = "drive_on"
    DRIVE_OFF = "drive_off"
    MIC_OFF = "mic_off"
    SWITCH = "switch"

    ENHANCED_ON = "enhanced_on"
    ENHANCED_OFF = "enhanced_off"
    FAVORITES_OFF = "favorites_off"
    FILTER_OFF = "filter_off"

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
    bar: str
    value: int


@dataclass(frozen=True)
class GoToCollection:
    key: str


_PHRASES: dict[str, AppCommand | BarSetting | GoToCollection] = {}


def _say(command: AppCommand | BarSetting | GoToCollection, *phrases: str, said: dict | None = None) -> None:
    said = _PHRASES if said is None else said
    for phrase in phrases:
        taken = said.get(phrase)
        if taken is not None and taken != command:
            raise RuntimeError(
                f"“{phrase}” already means {taken}, cannot also mean {command}"
            )
        said[phrase] = command


_COLLECTION_VERBS = ("go to", "open", "show")


def say_collections(collections, said: dict | None = None) -> None:
    for spoken in collections:
        for name in spoken.voice.names:
            _say(GoToCollection(spoken.key), *((name,) if spoken.voice.said_bare else ()),
                 f"{name} collection", *(f"{verb} {name}" for verb in _COLLECTION_VERBS),
                 said=said)


say_collections(spoken_collections())

_say(AppCommand.BACK, "back", "go back", "previous", "previous slide")
_say(AppCommand.FORWARD, "forward", "go forward", "next", "next slide", "skip")

_say(AppCommand.CULL, "trash", "delete", "delete it")
_say(AppCommand.LOCK, "lock", "hold")
_say(AppCommand.UNLOCK, "unlock", "release")
_say(AppCommand.FAVORITE, "favorite", "favorite it", "favorite this")
_say(AppCommand.UNDO, "undo")
_say(AppCommand.REDO, "redo")
_say(AppCommand.GROUP, "group", "group folders")

for _words, (_toggle, _on, _off) in (
    (("populate",), (AppCommand.POPULATE, AppCommand.POPULATE_ON, AppCommand.POPULATE_OFF)),
    (("radio",), (AppCommand.RADIO, AppCommand.RADIO_ON, AppCommand.RADIO_OFF)),
    (("drive", "motion"), (AppCommand.DRIVE, AppCommand.DRIVE_ON, AppCommand.DRIVE_OFF)),
):
    for _word in _words:
        _say(_toggle, _word)
        _say(_on, f"{_word} on")
        _say(_off, f"{_word} off")
_say(AppCommand.MIC_OFF, "mic off", "voice off")
_say(AppCommand.SWITCH, "switch")
# Whisper writes the letters either way: "osr two" or "o s r two".
_say(AppCommand.DRIVE_OFF, "osr two off", "o s r two off")
for _osr2 in ("osr two", "o s r two"):
    _say(AppCommand.DRIVE_OFF, f"{_osr2} control off")
    _say(AppCommand.DRIVE_ON, f"{_osr2} control on")

_say(AppCommand.ENHANCED_ON, "enhanced", "enhanced on", "filter enhanced", "enhanced filter",
     "filter enhanced only", "enhanced only",
     "enhancements", "enhancements only", "filter enhancements")
_say(AppCommand.ENHANCED_OFF, "enhanced off")
_say(AppCommand.FAVORITES_OFF, "favorites off")
_say(AppCommand.FILTER_OFF, "clear filter", "no filter", "filter off")

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

POPULATE_SWITCH, RADIO_SWITCH, DRIVE_SWITCH, MIC_SWITCH = "populate", "radio", "drive", "mic"
SWITCHES: dict[AppCommand, tuple[str, bool | None, str]] = {
    AppCommand.POPULATE: (POPULATE_SWITCH, None, "Populate"),
    AppCommand.POPULATE_ON: (POPULATE_SWITCH, True, "Populate"),
    AppCommand.POPULATE_OFF: (POPULATE_SWITCH, False, "Populate"),
    AppCommand.RADIO: (RADIO_SWITCH, None, "Origenerator Radio"),
    AppCommand.RADIO_ON: (RADIO_SWITCH, True, "Origenerator Radio"),
    AppCommand.RADIO_OFF: (RADIO_SWITCH, False, "Origenerator Radio"),
    AppCommand.DRIVE: (DRIVE_SWITCH, None, "OSR2"),
    AppCommand.DRIVE_ON: (DRIVE_SWITCH, True, "OSR2"),
    AppCommand.DRIVE_OFF: (DRIVE_SWITCH, False, "OSR2"),
    AppCommand.MIC_OFF: (MIC_SWITCH, False, "the mic"),
}
SWITCHES_A_HOST_HOLDS = (RADIO_SWITCH, DRIVE_SWITCH, MIC_SWITCH)
_STANDALONES_ALONE = frozenset({AppCommand.SWITCH})

_BARS = ("speed", "amp", "center")
_TENS: dict[str, int] = {
    "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "one hundred": 100,
}
_EXTREMES: dict[str, int] = {"min": 0, "max": 100}

for _bar in _BARS:
    for _word, _value in _TENS.items():
        _say(BarSetting(_bar, _value), f"{_bar} {_word}")
    for _label, _value in _EXTREMES.items():
        _say(BarSetting(_bar, _value), f"{_label} {_bar}")


def phrases_heard_only_outright() -> frozenset[str]:
    return phrases_for(AppCommand.MIC_OFF, AppCommand.CULL)


def phrases_for(*commands: AppCommand | GoToCollection) -> frozenset[str]:
    return frozenset(phrase for command in commands for phrase in said_as(command))


def said_as(command: AppCommand | GoToCollection) -> tuple[str, ...]:
    return tuple(phrase for phrase, meant in _PHRASES.items() if meant == command)


def spoken_phrases() -> frozenset[str]:
    return frozenset(_PHRASES)


def _answered_when_hosted(command: AppCommand | BarSetting | GoToCollection) -> bool:
    if isinstance(command, GoToCollection):
        return collection(command.key).voice.answered_when_hosted
    if isinstance(command, BarSetting) or command in MOTION_MOVES or command in _STANDALONES_ALONE:
        return False
    return command not in SWITCHES or SWITCHES[command][0] not in SWITCHES_A_HOST_HOLDS


def phrases_answered_when_hosted() -> frozenset[str]:
    return frozenset(phrase for phrase in spoken_phrases()
                     if _answered_when_hosted(_PHRASES[phrase]))


def match_app_command(text: str) -> AppCommand | BarSetting | GoToCollection | None:
    return _PHRASES_IN_DIGITS.get(_in_digits(text))


def _in_digits(text: str | None) -> str:
    return " ".join(numbers_as_digits(words(text, keep_digits=True)))


_PHRASES_IN_DIGITS = {_in_digits(phrase): command for phrase, command in _PHRASES.items()}
