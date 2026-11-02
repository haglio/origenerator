from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass


@dataclass(frozen=True)
class Picks:
    picked: frozenset[Hashable] = frozenset()
    anchor: Hashable | None = None


class Picking:
    def __init__(self):
        self._picked: set[Hashable] = set()
        self._anchor: Hashable | None = None
        self._shown: list[Hashable] = []

    def note_shown(self, entry: Hashable) -> None:
        self._shown.append(entry)

    def forget_what_was_shown(self) -> None:
        self._shown = []

    @property
    def shown(self) -> list[Hashable]:
        return list(self._shown)

    def apply(self, entry: Hashable, *, ctrl: bool = False, shift: bool = False) -> None:
        if ctrl:
            self._picked ^= {entry}
            self._anchor = entry
            return
        if shift and self._anchor in self._shown and entry in self._shown:
            a = self._shown.index(self._anchor)
            b = self._shown.index(entry)
            lo, hi = sorted((a, b))
            self._picked = set(self._shown[lo:hi + 1])
            return
        self._picked = {entry}
        self._anchor = entry

    def clear(self) -> None:
        self._picked = set()
        self._anchor = None

    def picks(self) -> Picks:
        return Picks(frozenset(self._picked), self._anchor)

    def pick_again(self, picks: Picks) -> None:
        self._picked = set(picks.picked) & set(self._shown)
        self._anchor = picks.anchor

    def holds(self, entry: Hashable) -> bool:
        return entry in self._picked

    @property
    def picked(self) -> set[Hashable]:
        return self._picked

    def in_shown_order(self) -> list[Hashable]:
        return [entry for entry in self._shown if entry in self._picked]
