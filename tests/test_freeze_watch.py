from __future__ import annotations

import io
import logging
import re
import textwrap
from pathlib import Path

from origenerator import single_instance
from origenerator.freeze_watch import CLOSED_WITHIN_S, HANDED_OVER_WITHIN_S, FreezeWatch
from tests.children import run_python


class _Faulthandler:
    def __init__(self):
        self.armed: list[tuple] = []

    def arm(self, timeout, *, repeat, file, exit):
        self.armed.append((timeout, repeat, file, exit))


def _watch(crash_log, faulthandler, *, clock=lambda: 0.0, stalled_after_s=10.0,
           closed_within_s=10.0, handed_over_within_s=30.0):
    return FreezeWatch(crash_log, stalled_after_s=stalled_after_s,
                       closed_within_s=closed_within_s,
                       handed_over_within_s=handed_over_within_s, beat_ms=60_000,
                       clock=clock, arm=faulthandler.arm)


def test_a_watch_arms_the_stack_dump_into_the_crash_log_for_one_stall(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()

    _watch(crash_log, faulthandler, stalled_after_s=10.0)

    assert faulthandler.armed == [(10.0, False, crash_log, False)]


def test_a_closed_window_gives_the_process_a_deadline_to_be_gone_by(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()
    watch = _watch(crash_log, faulthandler, closed_within_s=7.0)

    watch.end_the_process_if_the_close_sticks()

    assert faulthandler.armed[-1] == (7.0, False, crash_log, True)


def test_a_close_is_marked_in_the_crash_log_so_stacks_under_the_mark_read_as_a_stuck_close(qapp):
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), closed_within_s=7.0)

    watch.end_the_process_if_the_close_sticks()

    assert "=== closing at " in crash_log.getvalue()
    assert ("if still closing 7 s later, the stacks follow and the process is ended ===\n"
            in crash_log.getvalue())


def test_handing_comfyui_its_work_gives_the_process_a_deadline_of_its_own(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()
    watch = _watch(crash_log, faulthandler, closed_within_s=7.0, handed_over_within_s=25.0)

    watch.end_the_process_if_the_hand_over_sticks()

    assert faulthandler.armed[-1] == (25.0, False, crash_log, True)


def test_a_hand_over_is_marked_in_the_crash_log_so_stacks_under_the_mark_read_as_a_stuck_one(
        qapp):
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), handed_over_within_s=25.0)

    watch.end_the_process_if_the_hand_over_sticks()

    assert "=== handing ComfyUI its work at " in crash_log.getvalue()
    assert ("if still at it 25 s later, the stacks follow and the process is ended ===\n"
            in crash_log.getvalue())


def test_a_launch_waiting_on_a_closing_copy_outlasts_the_longest_close_the_watch_allows():
    # Closing arms one deadline as the window goes, handing ComfyUI its work a
    # second, and what comes after the hand-over the first again.
    longest_close_s = CLOSED_WITHIN_S + HANDED_OVER_WITHIN_S + CLOSED_WITHIN_S

    assert longest_close_s < single_instance.GIVE_UP_AFTER_S


def test_once_the_window_has_closed_no_beat_puts_the_deadline_off(qtbot):
    faulthandler = _Faulthandler()
    watch = FreezeWatch(io.StringIO(), beat_ms=10, arm=faulthandler.arm)

    watch.end_the_process_if_the_close_sticks()
    qtbot.wait(100)

    assert faulthandler.armed[-1][3] is True


def test_every_beat_puts_the_dump_off_again_so_a_window_that_answers_never_reaches_it(qapp):
    faulthandler = _Faulthandler()
    watch = _watch(io.StringIO(), faulthandler)

    watch.beat()
    watch.beat()

    assert len(faulthandler.armed) == 3


def test_the_event_loop_beats_on_its_own(qtbot):
    faulthandler = _Faulthandler()
    watch = FreezeWatch(io.StringIO(), beat_ms=10, arm=faulthandler.arm)

    qtbot.waitUntil(lambda: len(faulthandler.armed) >= 3, timeout=5000)
    watch.deleteLater()


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
    """)
    run_python(["-c", child])

    written = crash_log.read_text(encoding="utf-8")
    assert "the_slot_that_stalls" in written
    stalled = re.search(r"answering again after (\d+) s", written)
    assert stalled
    assert int(stalled.group(1)) >= 4


def _close_a_window_whose_teardown_takes(seconds, *, closed_within_s, crash_log):
    child = textwrap.dedent(f"""
        import os, sys, time
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {str(Path.cwd())!r})
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QWidget
        from origenerator.freeze_watch import watch_the_window
        app = QApplication([])
        window = QWidget()
        window.show()
        def the_teardown():
            time.sleep({seconds})
        app.aboutToQuit.connect(the_teardown)
        watch_the_window(app, open({str(crash_log)!r}, "a", encoding="utf-8"),
                         closed_within_s={closed_within_s})
        QTimer.singleShot(100, window.close)
        sys.exit(app.exec())
    """)
    return run_python(["-c", child], timeout=30)


def test_a_close_stuck_in_its_teardown_still_ends_the_process_and_names_where_it_stuck(tmp_path):
    crash_log = tmp_path / "origenerator_crash.log"

    ran = _close_a_window_whose_teardown_takes(60, closed_within_s=0.5, crash_log=crash_log)

    assert ran.returncode == 1, ran.stderr
    assert "the_teardown" in crash_log.read_text(encoding="utf-8")


def test_a_hand_over_longer_than_the_closes_deadline_runs_to_its_end(tmp_path):
    crash_log = tmp_path / "origenerator_crash.log"
    child = textwrap.dedent(f"""
        import os, sys, time
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {str(Path.cwd())!r})
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QWidget
        from origenerator.freeze_watch import watch_the_window
        app = QApplication([])
        window = QWidget()
        window.show()
        watch = watch_the_window(app, open({str(crash_log)!r}, "a", encoding="utf-8"),
                                 closed_within_s=1, handed_over_within_s=20)
        QTimer.singleShot(100, window.close)
        app.exec()
        watch.end_the_process_if_the_hand_over_sticks()
        time.sleep(2.5)
        watch.end_the_process_if_the_close_sticks()
        print("handed over", flush=True)
    """)

    ran = run_python(["-c", child], timeout=30)

    assert ran.returncode == 0, ran.stderr
    assert "handed over" in ran.stdout
    assert "Timeout" not in crash_log.read_text(encoding="utf-8")


def test_a_close_that_finishes_in_time_ends_the_process_as_usual(tmp_path):
    crash_log = tmp_path / "origenerator_crash.log"

    ran = _close_a_window_whose_teardown_takes(0.3, closed_within_s=3, crash_log=crash_log)

    assert ran.returncode == 0, ran.stderr
    assert "Timeout" not in crash_log.read_text(encoding="utf-8")
