from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from voice_core.spelling import numbers_as_digits

from origenerator.voice.text import words


class AppCommand(Enum):
    LATEST = "recents"
    FAVORITES = "favorites"
    EXPERIMENTS = "experiments"

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

    FILTER_ENHANCED = "filter_enhanced"
    FILTER_ORIGINALS = "filter_originals"
    ENHANCED_AND_ORIGINAL = "enhanced_and_original"
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


_PHRASES: dict[str, AppCommand | BarSetting] = {}


def _say(command: AppCommand | BarSetting, *phrases: str, said: dict | None = None) -> None:
    said = _PHRASES if said is None else said
    for phrase in phrases:
        taken = said.get(phrase)
        if taken is not None and taken != command:
            raise RuntimeError(
                f"“{phrase}” already means {taken}, cannot also mean {command}"
            )
        said[phrase] = command


_COLLECTION_NAMES: dict[AppCommand, tuple[str, ...]] = {
    AppCommand.LATEST: ("recents", "recent"),
    AppCommand.FAVORITES: ("favorites",),
    AppCommand.EXPERIMENTS: ("experiments", "experiment"),
}
_COLLECTION_VERBS = ("go to", "open", "show")
_NEVER_SAID_BARE = frozenset({"favorites"})
for _collection, _names in _COLLECTION_NAMES.items():
    for _name in _names:
        _say(_collection, *(() if _name in _NEVER_SAID_BARE else (_name,)), f"{_name} collection",
             *(f"{_verb} {_name}" for _verb in _COLLECTION_VERBS))

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
_say(AppCommand.DRIVE_OFF, "osr two off", "o s r two off")
for _osr2 in ("osr two", "o s r two"):
    _say(AppCommand.DRIVE_OFF, f"{_osr2} control off")
    _say(AppCommand.DRIVE_ON, f"{_osr2} control on")

_say(AppCommand.FILTER_ENHANCED, "filter enhanced", "enhanced filter",
     "filter enhanced only", "enhanced only",
     "upscales", "upscales only", "filter upscales", "upscaled only")
_say(AppCommand.FILTER_ORIGINALS, "original only")
_say(AppCommand.ENHANCED_AND_ORIGINAL, "enhanced and original", "original and enhanced")
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


def phrases_for(*commands: AppCommand) -> frozenset[str]:
    return frozenset(phrase for command in commands for phrase in said_as(command))


def said_as(command: AppCommand) -> tuple[str, ...]:
    return tuple(phrase for phrase, meant in _PHRASES.items() if meant == command)


def spoken_phrases() -> frozenset[str]:
    return frozenset(_PHRASES)


def _answered_when_hosted(command: AppCommand | BarSetting) -> bool:
    if isinstance(command, BarSetting) or command in MOTION_MOVES or command is AppCommand.EXPERIMENTS:
        return False
    return command not in SWITCHES or SWITCHES[command][0] not in SWITCHES_A_HOST_HOLDS


def phrases_answered_when_hosted() -> frozenset[str]:
    return frozenset(phrase for phrase in spoken_phrases()
                     if _answered_when_hosted(_PHRASES[phrase]))


def match_app_command(text: str) -> AppCommand | BarSetting | None:
    return _PHRASES_IN_DIGITS.get(_in_digits(text))


def _in_digits(text: str | None) -> str:
    return " ".join(numbers_as_digits(words(text, keep_digits=True)))


_PHRASES_IN_DIGITS = {_in_digits(phrase): command for phrase, command in _PHRASES.items()}
