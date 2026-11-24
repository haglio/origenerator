from __future__ import annotations

from dataclasses import dataclass

FIXES_KEY = "fixes"
OFF_KEY = "fixes_off"
LEFT_OUT_KEY = "fixes_left_out"
KEPT_KEY = "fixes_kept"

ON, OFF, LEFT_OUT = "on", "off", "left out"
CHOICES = (ON, OFF, LEFT_OUT)


@dataclass(frozen=True)
class FixSwitch:
    part: str
    on: bool
    redrew_something: bool
    held_by: tuple[str, ...] = ()
    left_out: bool = False

    @property
    def choice(self) -> str:
        return OFF if not self.on else LEFT_OUT if self.left_out else ON

    def can_be(self, choice: str) -> bool:
        if not self.redrew_something:
            return False
        return shows_the_fix(choice) == self.on or not self.held_by


def shows_the_fix(choice: str) -> bool:
    return choice != OFF


def switches_of(file_entry: dict) -> list[FixSwitch]:
    fixes = _fixes_of(file_entry)
    off = _named_under(file_entry, OFF_KEY)
    left_out = _named_under(file_entry, LEFT_OUT_KEY)
    return [FixSwitch(fix["part"], fix["part"] not in off, fix["box"] is not None,
                      _holding(fixes, fix, off),
                      left_out=fix["part"] in left_out and fix["part"] not in off)
            for fix in fixes]


def switch_of(file_entry: dict, part: str) -> FixSwitch | None:
    return next((switch for switch in switches_of(file_entry) if switch.part == part), None)


def chosen(file_entry: dict, part: str, choice: str) -> dict | None:
    switch = switch_of(file_entry, part)
    if switch is None or switch.choice == choice or not switch.can_be(choice):
        return None
    entry = {key: value for key, value in file_entry.items() if key not in (OFF_KEY, LEFT_OUT_KEY)}
    for key, said in ((OFF_KEY, OFF), (LEFT_OUT_KEY, LEFT_OUT)):
        named = ([name for name in _named_under(file_entry, key) if name != part]
                 + ([part] if choice == said else []))
        if named:
            entry[key] = named
    return entry


def left_out_of_a_re_enhance(file_entry: dict) -> list[str]:
    return [switch.part for switch in switches_of(file_entry) if switch.choice != ON]


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


def _named_under(file_entry: dict, key: str) -> list[str]:
    named = file_entry.get(key)
    return [name for name in named if isinstance(name, str)] if isinstance(named, list) else []


def _holding(fixes: list[dict], mine: dict, off: list[str]) -> tuple[str, ...]:
    if mine["part"] in off:
        return tuple(part for part in mine["over"] if part in off)
    return tuple(fix["part"] for fix in fixes
                 if mine["part"] in fix["over"] and fix["part"] not in off)
