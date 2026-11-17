from __future__ import annotations

from dataclasses import dataclass

FIXES_KEY = "fixes"
OFF_KEY = "fixes_off"
KEPT_KEY = "fixes_kept"


@dataclass(frozen=True)
class FixSwitch:
    part: str
    on: bool
    redrew_something: bool
    held_by: tuple[str, ...] = ()

    @property
    def can_be_switched(self) -> bool:
        return self.redrew_something and not self.held_by


def switches_of(file_entry: dict) -> list[FixSwitch]:
    fixes = _fixes_of(file_entry)
    off = _off_in(file_entry)
    return [FixSwitch(fix["part"], fix["part"] not in off, fix["box"] is not None,
                      _holding(fixes, fix, off))
            for fix in fixes]


def switched(file_entry: dict, part: str, on: bool) -> dict | None:
    switch = next((switch for switch in switches_of(file_entry) if switch.part == part), None)
    if switch is None or switch.on == on or not switch.can_be_switched:
        return None
    off = [name for name in _off_in(file_entry) if name != part] + ([] if on else [part])
    entry = {key: value for key, value in file_entry.items() if key != OFF_KEY}
    return {**entry, OFF_KEY: off} if off else entry


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


def _off_in(file_entry: dict) -> list[str]:
    off = file_entry.get(OFF_KEY)
    return [name for name in off if isinstance(name, str)] if isinstance(off, list) else []


def _holding(fixes: list[dict], mine: dict, off: list[str]) -> tuple[str, ...]:
    if mine["part"] in off:
        return tuple(part for part in mine["over"] if part in off)
    return tuple(fix["part"] for fix in fixes
                 if mine["part"] in fix["over"] and fix["part"] not in off)
