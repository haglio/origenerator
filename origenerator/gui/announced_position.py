from __future__ import annotations


class AnnouncedPosition:
    def __init__(self, player) -> None:
        self._position = int(player.position())
        player.positionChanged.connect(self._heard)

    def _heard(self, position: int) -> None:
        self._position = int(position)

    def position(self) -> int:
        return self._position
