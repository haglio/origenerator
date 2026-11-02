from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    view: str
    query: str = ""
    item: str | None = None


class NavigationHistory:
    def __init__(self):
        self._stack: list[Location] = []
        self._index = -1

    def visit(self, location: Location):
        if self._stack and self._stack[self._index] == location:
            return
        del self._stack[self._index + 1:]
        self._stack.append(location)
        self._index = len(self._stack) - 1

    def replace(self, location: Location):
        if not self._stack:
            self.visit(location)
            return
        del self._stack[self._index + 1:]
        self._stack[self._index] = location

    def can_go_back(self) -> bool:
        return self._index > 0

    def can_go_forward(self) -> bool:
        return self._index < len(self._stack) - 1

    def back(self) -> Location | None:
        if not self.can_go_back():
            return None
        self._index -= 1
        return self._stack[self._index]

    def forward(self) -> Location | None:
        if not self.can_go_forward():
            return None
        self._index += 1
        return self._stack[self._index]

    def current(self) -> Location | None:
        return self._stack[self._index] if self._stack else None
