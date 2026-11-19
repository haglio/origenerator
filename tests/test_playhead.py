from __future__ import annotations

from unittest.mock import MagicMock

from origenerator.gui.playhead import Playhead


def _playhead(at_ms=1000, length_ms=4000):
    now = [100.0]
    player = MagicMock()
    player.position.return_value = at_ms
    player.duration.return_value = length_ms
    return Playhead(player, clock=lambda: now[0]), player, now


def test_a_playhead_in_sight_reads_the_player():
    playhead, player, _now = _playhead()
    player.position.return_value = 1234

    assert playhead.position() == 1234


def test_a_held_playhead_runs_on_as_the_video_would_have_and_loops_with_it():
    playhead, _player, now = _playhead()
    playhead.hold()
    playhead.run(True)

    now[0] += 2.5
    assert playhead.position() == 3500
    now[0] += 1.0
    assert playhead.position() == 500


def test_a_held_playhead_stands_still_while_the_room_is_frozen():
    playhead, _player, now = _playhead()
    playhead.hold()
    playhead.run(True)
    now[0] += 1.0

    playhead.run(False)
    now[0] += 5.0
    assert playhead.position() == 2000
    playhead.run(True)
    now[0] += 0.5
    assert playhead.position() == 2500


def test_letting_go_of_a_held_playhead_says_where_the_video_goes_back_in():
    playhead, player, now = _playhead()
    playhead.hold()
    playhead.run(True)
    now[0] += 0.25

    assert playhead.release() == 1250
    player.position.return_value = 7
    assert playhead.position() == 7
