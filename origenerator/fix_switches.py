from __future__ import annotations

from dataclasses import dataclass

FIXES_KEY = "fixes"
OFF_KEY = "fixes_off"
LEFT_OUT_KEY = "fixes_left_out"
KEPT_KEY = "fixes_kept"

ON, BAD = "on", "bad"


@dataclass(frozen=True)
class FixSwitch:
    part: str
    on: bool
    redrew_something: bool
    held_by: tuple[str, ...] = ()
    bad: bool = False

    @property
    def can_be_switched(self) -> bool:
        return self.redrew_something and not self.held_by


def switches_of(file_entry: dict) -> list[FixSwitch]:
    fixes = _fixes_of(file_entry)
    off = _named_under(file_entry, OFF_KEY)
    bad = _named_under(file_entry, LEFT_OUT_KEY)
    return [FixSwitch(fix["part"], fix["part"] not in off, fix["box"] is not None,
                      _holding(fixes, fix, off), bad=fix["part"] in bad)
            for fix in fixes]


def switch_of(file_entry: dict, part: str) -> FixSwitch | None:
    return next((switch for switch in switches_of(file_entry) if switch.part == part), None)


def switched(file_entry: dict, part: str, on: bool) -> dict | None:
    switch = switch_of(file_entry, part)
    if switch is None or switch.on == on or not switch.can_be_switched:
        return None
    return _named_or_not(file_entry, OFF_KEY, part, named=not on)


def marked(file_entry: dict, part: str, bad: bool) -> dict | None:
    switch = switch_of(file_entry, part)
    if switch is None or switch.bad == bad or not switch.redrew_something:
        return None
    return _named_or_not(file_entry, LEFT_OUT_KEY, part, named=bad)


def with_these_off(file_entry: dict, off: list[str]) -> dict:
    entry = {key: value for key, value in file_entry.items() if key != OFF_KEY}
    if off:
        entry[OFF_KEY] = list(off)
    return entry


def changed(file_entry: dict, part: str, what: str, to: bool) -> dict | None:
    return (switched if what == ON else marked)(file_entry, part, to)


def left_out_of_a_re_enhance(file_entry: dict) -> list[str]:
    return [switch.part for switch in switches_of(file_entry) if switch.bad or not switch.on]


def drawn_as(file_entry: dict, part: str) -> tuple[int, list[int]] | None:
    for at, fix in enumerate(_fixes_of(file_entry)):
        if fix["part"] == part and fix["box"] is not None:
            return at, fix["box"]
    return None


def _fixes_of(file_entry: dict) -> list[dict]:
    fixes = file_entry.get(FIXES_KEY)
    if not isinstance(fixes, list) or not isinstance(file_entry.get(KEPT_KEY), str):
        return []
    return [fix for fix in fixes
            if isinstance(fix, dict) and isinstance(fix.get("part"), str)
            and isinstance(fix.get("over"), list) and "box" in fix]


def _named_or_not(file_entry: dict, key: str, part: str, *, named: bool) -> dict:
    entry = {k: value for k, value in file_entry.items() if k != key}
    names = ([name for name in _named_under(file_entry, key) if name != part]
             + ([part] if named else []))
    if names:
        entry[key] = names
    return entry


def _named_under(file_entry: dict, key: str) -> list[str]:
    named = file_entry.get(key)
    return [name for name in named if isinstance(name, str)] if isinstance(named, list) else []


def _holding(fixes: list[dict], mine: dict, off: list[str]) -> tuple[str, ...]:
    if mine["part"] in off:
        return tuple(part for part in mine["over"] if part in off)
    return tuple(fix["part"] for fix in fixes
                 if mine["part"] in fix["over"] and fix["part"] not in off)
