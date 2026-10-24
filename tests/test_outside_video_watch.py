"""The look for other sources' videos, which runs while the window is up.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, QThreadPool

from origenerator.gui.outside_video_watch import LOOK_EVERY_MS, OutsideVideoWatch
from origenerator.outside_videos import Places

_PLACES = Places(upscaled_dir=Path("L:/outbox"), records_folder=Path("L:/records"),
                 frames_dir=Path("L:/frames"), thumb_dir=Path("L:/thumbs"),
                 skip_sources=frozenset(), library_root=Path("L:/"), journal=None)


class _Pool:
    """Runs nothing until told to, the way Qt's pool runs a look later."""

    def __init__(self):
        self.waiting = []

    def __call__(self, work, done, *, owner):
        self.waiting.append((work, done))

    def finish(self):
        work, done = self.waiting.pop(0)
        done(work())


def _watch(qtbot, *, places=_PLACES, every_ms=LOOK_EVERY_MS):
    pool, looks = _Pool(), []
    watch = OutsideVideoWatch(
        "the library", lambda: places, run=pool, every_ms=every_ms,
        scan=lambda db, where, **told: looks.append((db, where, told)) or 0)
    return watch, pool, looks


def test_the_window_looks_for_new_videos_away_from_its_own_thread(qtbot):
    watch, pool, looks = _watch(qtbot)

    watch.start()
    assert looks == []
    pool.finish()

    assert [(db, where) for db, where, _told in looks] == [("the library", _PLACES)]


def test_a_look_runs_at_the_priority_every_off_thread_call_runs_at(qtbot):
    seen = []
    watch = OutsideVideoWatch(
        "the library", lambda: _PLACES,
        scan=lambda *_args, **_told: seen.append(QThread.currentThread().priority()) or 0)

    watch.look()
    qtbot.waitUntil(lambda: bool(seen))

    assert seen == [QThreadPool.globalInstance().threadPriority()]


def test_the_look_comes_round_again(qtbot):
    watch, pool, looks = _watch(qtbot, every_ms=20)

    watch.start()
    pool.finish()
    qtbot.waitUntil(lambda: bool(pool.waiting))
    pool.finish()

    assert len(looks) == 2


def test_a_look_still_going_is_not_started_a_second_time(qtbot):
    watch, pool, _looks = _watch(qtbot)

    watch.start()
    watch.look()

    assert len(pool.waiting) == 1


def test_with_no_evolver_beside_this_app_there_is_nothing_to_look_for(qtbot):
    watch, pool, _looks = _watch(qtbot, places=None)

    watch.start()

    assert pool.waiting == []


def test_a_look_under_way_stops_once_the_app_is_closing(qtbot):
    watch, pool, looks = _watch(qtbot)

    watch.start()
    watch.stop()
    pool.finish()

    [(_db, _where, told)] = looks
    assert told["keep_going"]() is False
