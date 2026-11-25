from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

AfterTheDraw = Callable[[bool], None]


@dataclass
class _Asked:
    version: object
    after: list[AfterTheDraw | None] = field(default_factory=list)
    even_unmoved: bool = False
    over: int | None = None

    def add(self, then: AfterTheDraw | None, *, even_unmoved: bool) -> None:
        self.after.append(then)
        self.even_unmoved = self.even_unmoved or even_unmoved

    def covers(self, version, *, even_unmoved: bool) -> bool:
        return self.version == version and (self.even_unmoved or not even_unmoved)

    def joined(self, later: _Asked, version) -> _Asked:
        return _Asked(version, self.after + later.after,
                      self.even_unmoved or later.even_unmoved)


class LibraryRedraws:
    def __init__(self, *, version: Callable[[], object], read, draw,
                 drawn_version: Callable[[], int], off_thread) -> None:
        self._version = version
        self._drawn_version = drawn_version
        self._read = read
        self._draw = draw
        self._off_thread = off_thread
        self._reading: _Asked | None = None
        self._next: _Asked | None = None

    def ask(self, then: AfterTheDraw | None = None, *, even_unmoved: bool = True) -> None:
        version = self._version()
        if self._reading is None:
            asked = _Asked(version)
            asked.add(then, even_unmoved=even_unmoved)
            self._begin(asked)
        elif self._next is None and self._reading.covers(version, even_unmoved=even_unmoved):
            self._reading.add(then, even_unmoved=even_unmoved)
        else:
            self._next = self._next or _Asked(version)
            self._next.add(then, even_unmoved=even_unmoved)

    def _begin(self, asked: _Asked) -> None:
        asked.over = self._drawn_version()
        self._reading = asked
        self._off_thread(self._read(even_unmoved=asked.even_unmoved), self._landed)

    def _landed(self, read) -> None:
        asked, self._reading = self._reading, None
        if self._next is not None:
            later, self._next = self._next, None
            self._begin(asked.joined(later, self._version()))
            return
        if asked.over != self._drawn_version():
            self._begin(asked)
            return
        drew = self._draw(read, even_unmoved=asked.even_unmoved)
        for then in asked.after:
            if then is not None:
                then(drew)
