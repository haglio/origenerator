from __future__ import annotations

import io
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

from origenerator.freeze_watch import FreezeWatch


class _Faulthandler:
    def __init__(self):
        self.armed: list[tuple] = []
        self.disarmed = 0

    def arm(self, timeout, *, repeat, file, exit):
        self.armed.append((timeout, repeat, file, exit))

    def disarm(self):
        self.disarmed += 1


def _watch(crash_log, faulthandler, *, clock=lambda: 0.0, stalled_after_s=10.0):
    return FreezeWatch(crash_log, stalled_after_s=stalled_after_s, beat_ms=60_000,
                       clock=clock, arm=faulthandler.arm, disarm=faulthandler.disarm)


def test_a_watch_arms_the_stack_dump_into_the_crash_log_for_one_stall(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()

    _watch(crash_log, faulthandler, stalled_after_s=10.0)

    assert faulthandler.armed == [(10.0, False, crash_log, False)]


def test_every_beat_puts_the_dump_off_again_so_a_window_that_answers_never_reaches_it(qapp):
    faulthandler = _Faulthandler()
    watch = _watch(io.StringIO(), faulthandler)

    watch.beat()
    watch.beat()

    assert len(faulthandler.armed) == 3


def test_the_event_loop_beats_on_its_own(qtbot):
    faulthandler = _Faulthandler()
    watch = FreezeWatch(io.StringIO(), beat_ms=10, arm=faulthandler.arm,
                        disarm=faulthandler.disarm)

    qtbot.waitUntil(lambda: len(faulthandler.armed) >= 3, timeout=5000)
    watch.stop()


def test_a_stopped_watch_takes_the_dump_back_and_beats_no_more(qtbot):
    faulthandler = _Faulthandler()
    watch = FreezeWatch(io.StringIO(), beat_ms=10, arm=faulthandler.arm,
                        disarm=faulthandler.disarm)

    watch.stop()
    armed_at_the_stop = len(faulthandler.armed)
    qtbot.wait(100)

    assert faulthandler.disarmed == 1
    assert len(faulthandler.armed) == armed_at_the_stop


def test_the_first_beat_after_a_stall_says_how_long_the_window_stopped_answering(qapp, caplog):
    now = [100.0]
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), clock=lambda: now[0], stalled_after_s=10.0)

    now[0] += 42.0
    with caplog.at_level(logging.WARNING, logger="origenerator.freeze_watch"):
        watch.beat()

    assert "stopped answering for 42 s" in caplog.text
    assert "answering again after 42 s" in crash_log.getvalue()


def test_a_beat_on_time_says_nothing(qapp, caplog):
    now = [100.0]
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), clock=lambda: now[0], stalled_after_s=10.0)

    now[0] += 9.0
    with caplog.at_level(logging.WARNING, logger="origenerator.freeze_watch"):
        watch.beat()

    assert caplog.text == ""
    assert crash_log.getvalue() == ""


def test_a_window_stuck_in_a_slot_leaves_that_slot_in_the_crash_log(tmp_path):
    crash_log = tmp_path / "origenerator_crash.log"
    child = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path.cwd())!r})
        from PyQt6.QtCore import QCoreApplication, QTimer
        from origenerator.freeze_watch import FreezeWatch
        app = QCoreApplication([])
        watch = FreezeWatch(open({str(crash_log)!r}, "a", encoding="utf-8"),
                            stalled_after_s=0.5, beat_ms=50)
        def the_slot_that_stalls():
            time.sleep(4)
            QTimer.singleShot(300, app.quit)
        QTimer.singleShot(100, the_slot_that_stalls)
        app.exec()
        watch.stop()
    """)
    subprocess.run([sys.executable, "-c", child], capture_output=True, timeout=120,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    written = crash_log.read_text(encoding="utf-8")
    assert "the_slot_that_stalls" in written
    assert "answering again after 4 s" in written
