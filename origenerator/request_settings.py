from __future__ import annotations

import json
from dataclasses import dataclass
from typing import NamedTuple

from origenerator.base_models import loras_offered_beside
from origenerator.model_titles import option_title, versioned
from origenerator.setting_advice import spoken_list
from origenerator.trigger_words import trigger_words
from origenerator.workflows.base import ParamDef, ParamType, shown_with_what_is_held
from origenerator.workflows.model_files import is_no_lora

_TOLD = (ParamType.INT, ParamType.FLOAT, ParamType.DROPDOWN, ParamType.BOOL)
_ON = ("on", "true", "yes", "1")
_OFF = ("off", "false", "no", "0")


def _as_named(text) -> str:
    return "" if text is None else str(text).strip().lower()


class Choice(NamedTuple):
    value: object
    title: str
    note: str = ""

    @property
    def told(self) -> str:
        return f"{self.title} ({self.note})" if self.note else self.title

    def is_called(self, name: str) -> bool:
        return name in (_as_named(self.value), _as_named(self.title))


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    type: ParamType
    value: object
    choices: tuple[Choice, ...]
    low: float | None
    high: float | None
    unit: str
    folder: str = ""

    def _choice_of(self, value) -> Choice | None:
        return next((choice for choice in self.choices if choice.value == value), None)

    def shown(self, value=None) -> str:
        value = self.value if value is None else value
        if self.type is ParamType.BOOL:
            return "on" if value else "off"
        choice = self._choice_of(value)
        return choice.title if choice else f"{value}{self.unit}"

    def told(self) -> str:
        if self.type is ParamType.DROPDOWN:
            kind = "one of " + ", ".join(choice.told for choice in self.choices)
        elif self.type is ParamType.BOOL:
            kind = "on or off"
        else:
            kind = "a whole number" if self.type is ParamType.INT else "a number"
            if self.low is not None and self.high is not None:
                kind += f" from {self.low:g}" if self.type is ParamType.INT else f" from {self.low}"
                kind += f" to {self.high:g}" if self.type is ParamType.INT else f" to {self.high}"
        picked = self._choice_of(self.value)
        return f"- {self.label} [{self.key}]: {picked.told if picked else self.shown()}, {kind}"

    def taken(self, raw):
        try:
            if self.type is ParamType.BOOL:
                word = _as_named(raw)
                return True if word in _ON else False if word in _OFF else None
            if self.type is ParamType.DROPDOWN:
                return self._option_called(_as_named(raw))
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if self.low is not None:
            number = max(self.low, number)
        if self.high is not None:
            number = min(self.high, number)
        return round(number) if self.type is ParamType.INT else number

    def _option_called(self, name: str):
        return next((choice.value for choice in self.choices if choice.is_called(name)), None)


def _named(pd: ParamDef, options: tuple) -> dict:
    if pd.type is not ParamType.DROPDOWN or not pd.folder:
        return {}
    return {option: option_title(option) for option in options}


def _newest_versions(names: dict) -> dict:
    newest: dict = {}
    for option, title in names.items():
        base_and_version = versioned(title)
        if base_and_version is not None:
            base, version = base_and_version
            newest.setdefault(base, []).append((version, option))
    return {max(versions)[1]: base for base, versions in newest.items() if len(versions) > 1}


def _lora_notes(pd: ParamDef, names: dict) -> dict:
    if pd.folder != "loras":
        return {}
    newest = _newest_versions(names)
    notes = {}
    for option in names:
        said = []
        if words := trigger_words(option) if not is_no_lora(option) else ():
            said.append(f"trigger word{'s' if len(words) > 1 else ''} {spoken_list(words, 'and')}")
        if option in newest:
            said.append(f"the newest {newest[option]}")
        if said:
            notes[option] = "; ".join(said)
    return notes


def _choices(pd: ParamDef, params: dict) -> tuple[Choice, ...]:
    options = _offered(pd, params)
    if pd.type is ParamType.DROPDOWN and pd.key in params:
        options = tuple(shown_with_what_is_held(options, params[pd.key]))
    names = _named(pd, options)
    notes = _lora_notes(pd, names)
    return tuple(Choice(option, names.get(option) or str(option), notes.get(option, ""))
                 for option in options)


def _offered(pd: ParamDef, params: dict) -> tuple:
    options = pd.options or ()
    if pd.beside_model:
        options = loras_offered_beside(params.get(pd.beside_model), options)
    return tuple(options)


def settings_to_tell(param_defs: list[ParamDef], params: dict) -> list[Setting]:
    return [Setting(pd.key, pd.label, pd.type, params.get(pd.key, pd.default),
                    _choices(pd, params), pd.min_val, pd.max_val, pd.unit, pd.folder)
            for pd in param_defs if pd.type in _TOLD]


_SIZE_KEYS = ("width", "height")
_SHAPES = (
    "Portrait, landscape and square are a matter of Width and Height and never of the prompts: "
    "portrait means Height greater than Width, landscape means Width greater than Height, square "
    "means the two equal, so to make a landscape image portrait or the reverse, swap the two "
    "numbers.")


def _shape_of(width: int, height: int) -> str:
    if width == height:
        return "square"
    return "portrait (taller than wide)" if height > width else "landscape (wider than tall)"


def shape_told(settings: list[Setting]) -> str:
    size = {setting.key: setting.value for setting in settings if setting.key in _SIZE_KEYS}
    if any(key not in size for key in _SIZE_KEYS):
        return ""
    return (f"Width {size['width']} and Height {size['height']} together make the image "
            f"{_shape_of(size['width'], size['height'])}. {_SHAPES}")


def as_told(settings: list[Setting]) -> str:
    lines = [setting.told() for setting in settings]
    if shape := shape_told(settings):
        lines.append(shape)
    return "\n".join(lines)


def setting_called(name, settings: list[Setting]) -> Setting | None:
    called = _as_named(name)
    return next((setting for setting in settings
                 if called in (_as_named(setting.key), _as_named(setting.label))), None)


def described(changes: dict, settings: list[Setting]) -> list[tuple[str, str, str]]:
    return [(setting.label, setting.shown(), setting.shown(changes[setting.key]))
            for setting in settings if setting.key in changes]


def recorded(changes) -> str:
    return json.dumps([list(change) for change in changes]) if changes else ""
