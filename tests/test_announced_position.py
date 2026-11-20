from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from origenerator.gui.announced_position import AnnouncedPosition


class _Player(QObject):
    positionChanged = Signal("qlonglong")

    def __init__(self, at: int = 0):
        super().__init__()
        self.at, self.asked = at, 0

    def position(self) -> int:
        self.asked += 1
        return self.at


def test_it_starts_where_the_player_is(qapp):
    assert AnnouncedPosition(_Player(at=700)).position() == 700


def test_it_reads_where_the_player_last_said_it_was_without_asking_the_player_again(qapp):
    player = _Player()
    playhead = AnnouncedPosition(player)

    player.positionChanged.emit(1234)

    assert (playhead.position(), player.asked) == (1234, 1), (
        "the OSR2's clock thread reads this, and Qt's player answers only on the window's thread;"
        " its position is the last one it announced, so the two read the same")
