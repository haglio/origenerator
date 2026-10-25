"""What each press in the sorting window does to the line of images."""
from __future__ import annotations

from collections import deque


class SortingSession:
    def __init__(self, images: list[dict], store):
        self._line = deque(images)
        self._store = store
        self._sorted: list[tuple[dict, str]] = []

    @property
    def current(self) -> dict | None:
        return self._line[0] if self._line else None

    @property
    def remaining(self) -> int:
        return len(self._line)

    @property
    def last_state(self) -> str | None:
        """The state the last answer gave, which :meth:`same` gives again."""
        return self._sorted[-1][1] if self._sorted else None

    @property
    def can_undo(self) -> bool:
        return bool(self._sorted)

    def sort_as(self, state: str) -> None:
        if not self._line:
            return
        image = self._line.popleft()
        self._store.set_image_state(image["prompt_id"], state)
        self._sorted.append((image, state))

    def same(self) -> None:
        if self.last_state is not None:
            self.sort_as(self.last_state)

    def skip(self) -> None:
        self._line.rotate(-1)

    def undo(self) -> None:
        if not self._sorted:
            return
        image, _state = self._sorted.pop()
        self._store.set_image_state(image["prompt_id"], None)
        self._line.appendleft(image)
