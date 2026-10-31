from __future__ import annotations

import json
from dataclasses import dataclass

from origenerator.workflows.base import ParamDef, ParamType

_TOLD = (ParamType.INT, ParamType.FLOAT, ParamType.COMBO, ParamType.BOOL)
_ON = ("on", "true", "yes", "1")
_OFF = ("off", "false", "no", "0")


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    type: ParamType
    value: object
    options: tuple
    low: float | None
    high: float | None
    unit: str

    def shown(self, value=None) -> str:
        value = self.value if value is None else value
        if self.type is ParamType.BOOL:
            return "on" if value else "off"
        return f"{value}{self.unit}"

    def told(self) -> str:
        if self.type is ParamType.COMBO:
            kind = "one of " + ", ".join(str(option) for option in self.options)
        elif self.type is ParamType.BOOL:
            kind = "on or off"
        else:
            kind = "a whole number" if self.type is ParamType.INT else "a number"
            if self.low is not None and self.high is not None:
                kind += f" from {self.low:g}" if self.type is ParamType.INT else f" from {self.low}"
                kind += f" to {self.high:g}" if self.type is ParamType.INT else f" to {self.high}"
        return f"- {self.label} [{self.key}]: {self.shown()}, {kind}"

    def taken(self, raw):
        try:
            if self.type is ParamType.BOOL:
                word = str(raw).strip().lower()
                return True if word in _ON else False if word in _OFF else None
            if self.type is ParamType.COMBO:
                return next((option for option in self.options
                             if str(option).lower() == str(raw).strip().lower()), None)
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if self.low is not None:
            number = max(self.low, number)
        if self.high is not None:
            number = min(self.high, number)
        return int(round(number)) if self.type is ParamType.INT else number


def settings_to_tell(param_defs: list[ParamDef], params: dict) -> list[Setting]:
    return [Setting(pd.key, pd.label, pd.type, params.get(pd.key, pd.default),
                    tuple(pd.options or ()), pd.min_val, pd.max_val, pd.unit)
            for pd in param_defs if pd.type in _TOLD]


def as_told(settings: list[Setting]) -> str:
    return "\n".join(setting.told() for setting in settings)


def changes_asked(answer, settings: list[Setting]) -> dict:
    if not isinstance(answer, dict):
        return {}
    by_name = {setting.key.lower(): setting for setting in settings}
    by_name.update({setting.label.lower(): setting for setting in settings})
    changes = {}
    for name, raw in answer.items():
        setting = by_name.get(str(name).strip().lower())
        if setting is None:
            continue
        value = setting.taken(raw)
        if value is not None and value != setting.value:
            changes[setting.key] = value
    return changes


def described(changes: dict, settings: list[Setting]) -> list[tuple[str, str, str]]:
    return [(setting.label, setting.shown(), setting.shown(changes[setting.key]))
            for setting in settings if setting.key in changes]


def recorded(changes) -> str:
    return json.dumps([list(change) for change in changes]) if changes else ""
