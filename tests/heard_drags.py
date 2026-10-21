"""What the drags a test starts announce to every place a drop can land."""
from __future__ import annotations

from origenerator.gui.drags import under_way
from origenerator.gui.generation_drag import dragged_generation


class HeardDrags:
    def __init__(self):
        self.started: list[tuple[object, object]] = []
        self.ended = 0
        under_way.started.connect(self._started)
        under_way.ended.connect(self._ended)

    def _started(self, mime, source) -> None:
        self.started.append((mime, source))

    def _ended(self) -> None:
        self.ended += 1

    def generations(self) -> list[str | None]:
        return [dragged_generation(mime) for mime, _source in self.started]
