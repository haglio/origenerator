from __future__ import annotations

import io
import logging
import re
import textwrap
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app_support.threading_utils import wait_until
from PySide6.QtWidgets import QApplication

from origenerator import single_instance
from origenerator.freeze_watch import (
    CLOSED_WITHIN_S,
    HANDED_OVER_WITHIN_S,
    LATE_AFTER_S,
    STALL_LINES_A_MINUTE,
    AnsweringWindow,
    FreezeWatch,
    StallRecord,
    Timing,
)
from origenerator.where_the_time_went import PACKAGE_DIR
from tests.children import run_python


class _Faulthandler:
    def __init__(self):
        self.armed: list[tuple] = []

    def arm(self, timeout, *, repeat, file, exit):
        self.armed.append((timeout, repeat, file, exit))


_TIMING = Timing(stalled_after_s=10.0, closed_within_s=10.0, handed_over_within_s=30.0,
                 beat_ms=60_000)


def _watch(crash_log, faulthandler, *, clock=lambda: 0.0, timing=_TIMING):
    return FreezeWatch(crash_log, timing=timing, clock=clock, arm=faulthandler.arm)


def test_a_watch_arms_the_stack_dump_into_the_crash_log_for_one_stall(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()

    _watch(crash_log, faulthandler)

    assert faulthandler.armed == [(10.0, False, crash_log, False)]


def test_a_closed_window_gives_the_process_a_deadline_to_be_gone_by(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()
    watch = _watch(crash_log, faulthandler, timing=_TIMING._replace(closed_within_s=7.0))

    watch.end_the_process_if_the_close_sticks()

    assert faulthandler.armed[-1] == (7.0, False, crash_log, True)


def test_a_close_is_marked_in_the_crash_log_so_stacks_under_the_mark_read_as_a_stuck_close(qapp):
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), timing=_TIMING._replace(closed_within_s=7.0))

    watch.end_the_process_if_the_close_sticks()

    assert "=== closing at " in crash_log.getvalue()
    assert ("if still closing 7 s later, the stacks follow and the process is ended ===\n"
            in crash_log.getvalue())


def test_handing_comfyui_its_work_gives_the_process_a_deadline_of_its_own(qapp):
    crash_log = io.StringIO()
    faulthandler = _Faulthandler()
    watch = _watch(crash_log, faulthandler, timing=_TIMING._replace(closed_within_s=7.0, handed_over_within_s=25.0))

    watch.end_the_process_if_the_hand_over_sticks()

    assert faulthandler.armed[-1] == (25.0, False, crash_log, True)


def test_a_hand_over_is_marked_in_the_crash_log_so_stacks_under_the_mark_read_as_a_stuck_one(
        qapp):
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), timing=_TIMING._replace(handed_over_within_s=25.0))

    watch.end_the_process_if_the_hand_over_sticks()

    assert "=== handing ComfyUI its work at " in crash_log.getvalue()
    assert ("if still at it 25 s later, the stacks follow and the process is ended ===\n"
            in crash_log.getvalue())


def test_a_launch_waiting_on_a_closing_copy_outlasts_the_longest_close_the_watch_allows():
    longest_close_s = CLOSED_WITHIN_S + HANDED_OVER_WITHIN_S + CLOSED_WITHIN_S

    assert longest_close_s < single_instance.GIVE_UP_AFTER_S, (
        "closing arms one deadline as the window goes, handing ComfyUI its work a second, and "
        "what comes after the hand-over the first again")


def test_once_the_window_has_closed_no_beat_puts_the_deadline_off(qtbot):
    faulthandler = _Faulthandler()
    watch = FreezeWatch(io.StringIO(), timing=Timing(beat_ms=10), arm=faulthandler.arm)

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
    watch = FreezeWatch(io.StringIO(), timing=Timing(beat_ms=10), arm=faulthandler.arm)

    qtbot.waitUntil(lambda: len(faulthandler.armed) >= 3, timeout=5000)
    watch.deleteLater()


def test_the_first_beat_after_a_stall_says_how_long_the_window_stopped_answering(qapp, caplog):
    now = [100.0]
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), clock=lambda: now[0])

    now[0] += 42.0
    with caplog.at_level(logging.WARNING, logger="origenerator.freeze_watch"):
        watch.beat()

    assert "stopped answering for 42 s" in caplog.text
    assert "answering again after 42 s" in crash_log.getvalue()


def test_a_beat_on_time_says_nothing(qapp, caplog):
    now = [100.0]
    crash_log = io.StringIO()
    watch = _watch(crash_log, _Faulthandler(), clock=lambda: now[0])

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
        from PySide6.QtCore import QCoreApplication, QTimer
        from origenerator.freeze_watch import FreezeWatch, Timing
        app = QCoreApplication([])
        watch = FreezeWatch(open({str(crash_log)!r}, "a", encoding="utf-8"),
                            timing=Timing(stalled_after_s=0.5, beat_ms=50))
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
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        from origenerator.freeze_watch import Timing, watch_the_window
        app = QApplication([])
        window = QWidget()
        window.show()
        def the_teardown():
            time.sleep({seconds})
        app.aboutToQuit.connect(the_teardown)
        watch_the_window(app, open({str(crash_log)!r}, "a", encoding="utf-8"),
                         Timing(closed_within_s={closed_within_s}))
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
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        from origenerator.freeze_watch import Timing, watch_the_window
        app = QApplication([])
        window = QWidget()
        window.show()
        watch = watch_the_window(app, open({str(crash_log)!r}, "a", encoding="utf-8"),
                                 Timing(closed_within_s=1, handed_over_within_s=20))
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


class _Window:
    def __init__(self):
        self.now = 0.0
        self.busy_until = 0.0
        self.asked: list[float] = []

    def answers_within(self, seconds):
        self.asked.append(seconds)
        if self.now + seconds < self.busy_until:
            self.now += seconds
            return False
        self.now = max(self.now, self.busy_until)
        return True

    def wait(self, seconds):
        self.now += seconds


_WINDOW_THREAD = 0x5E1
_A_WALL_CLOCK = 1_700_000_000.0
_REFRESHING_THE_GALLERY = SimpleNamespace(
    f_code=SimpleNamespace(co_filename=str(Path(PACKAGE_DIR, "gui", "gallery_view.py")),
                           co_name="refresh"),
    f_back=SimpleNamespace(
        f_code=SimpleNamespace(co_filename=str(Path(PACKAGE_DIR, "app.py")), co_name="run"),
        f_back=None))


def _stalls(window):
    return StallRecord(window, _WINDOW_THREAD, clock=lambda: window.now,
                       wall=lambda: _A_WALL_CLOCK + window.now,
                       frames=lambda: {_WINDOW_THREAD: _REFRESHING_THE_GALLERY},
                       pause=window.wait)


def _busy_for(window, stalls, seconds):
    window.busy_until = window.now + seconds
    while window.now < window.busy_until:
        stalls.watch_once()
    stalls.watch_once()


def _answering_until(window, stalls, until_s):
    while window.now < until_s:
        stalls.watch_once()


def _said(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if record.getMessage().startswith("Window stall")]


def _clock_time(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).astimezone().strftime("%H:%M:%S.%f")[:-3]


def test_a_window_that_answers_writes_no_stall(caplog):
    window = _Window()
    stalls = _stalls(window)

    with caplog.at_level(logging.INFO, logger="origenerator.freeze_watch"):
        _answering_until(window, stalls, 5.0)

    assert _said(caplog) == []


def test_each_ask_gives_the_window_a_tenth_of_a_second_to_answer():
    window = _Window()
    stalls = _stalls(window)

    _busy_for(window, stalls, 0.25)

    assert set(window.asked) == {LATE_AFTER_S}


def test_a_window_that_stops_answering_says_for_how_long_from_when_and_where_it_stood(caplog):
    window = _Window()
    stalls = _stalls(window)
    stalls.watch_once()

    with caplog.at_level(logging.INFO, logger="origenerator.freeze_watch"):
        _busy_for(window, stalls, 0.34)

    assert _said(caplog) == [
        f"Window stall: 0.34 s without answering, from {_clock_time(_A_WALL_CLOCK + 0.05)}; "
        "3 looks at the thread, and how many found it inside each function: "
        "gallery_view.refresh 3, app.run 3"]


def test_no_more_stalls_than_a_minute_allows_are_written_one_by_one(caplog):
    window = _Window()
    stalls = _stalls(window)

    with caplog.at_level(logging.INFO, logger="origenerator.freeze_watch"):
        for _ in range(STALL_LINES_A_MINUTE + 3):
            _busy_for(window, stalls, 0.3)

    assert len(_said(caplog)) == STALL_LINES_A_MINUTE


def test_a_minute_with_stalls_ends_in_a_line_summing_them_up(caplog):
    window = _Window()
    stalls = _stalls(window)
    for _ in range(STALL_LINES_A_MINUTE + 2):
        _busy_for(window, stalls, 0.3)

    with caplog.at_level(logging.INFO, logger="origenerator.freeze_watch"):
        caplog.clear()
        _answering_until(window, stalls, 60.1)

    assert _said(caplog) == [
        f"Window stalls over 60 s: {STALL_LINES_A_MINUTE + 2}, "
        f"{0.3 * (STALL_LINES_A_MINUTE + 2):.2f} s in all, worst 0.30 s, "
        "2 not written one by one"]


def test_a_minute_without_a_stall_writes_nothing(caplog):
    window = _Window()
    stalls = _stalls(window)

    with caplog.at_level(logging.INFO, logger="origenerator.freeze_watch"):
        _answering_until(window, stalls, 130.0)

    assert _said(caplog) == []


def test_the_next_minute_writes_its_own_stalls_one_by_one_again(caplog):
    window = _Window()
    stalls = _stalls(window)
    for _ in range(STALL_LINES_A_MINUTE + 1):
        _busy_for(window, stalls, 0.3)
    _answering_until(window, stalls, 60.1)
    began = window.now

    with caplog.at_level(logging.INFO, logger="origenerator.freeze_watch"):
        caplog.clear()
        _busy_for(window, stalls, 0.35)

    assert _said(caplog) == [
        f"Window stall: 0.35 s without answering, from {_clock_time(_A_WALL_CLOCK + began)}; "
        "3 looks at the thread, and how many found it inside each function: "
        "gallery_view.refresh 3, app.run 3"]


class _GoneWindow:
    def answers_within(self, seconds):
        raise OSError("made-up: the window is gone")


def test_a_watch_whose_window_has_gone_ends_saying_so(caplog):
    stalls = StallRecord(_GoneWindow(), _WINDOW_THREAD)

    with caplog.at_level(logging.WARNING, logger="origenerator.freeze_watch"):
        stalls.start()
        stalls.stop()

    assert "the window it asks went away" in caplog.text


def test_a_stopped_watch_asks_the_window_no_more():
    window = _Window()
    stalls = StallRecord(window, _WINDOW_THREAD)
    stalls.start()
    wait_until(lambda: window.asked)

    stalls.stop()
    asked = len(window.asked)

    assert len(window.asked) == asked
    assert not stalls.watching()


def test_once_the_window_has_closed_no_stall_is_looked_for(qapp):
    window = _Window()
    stalls = StallRecord(window, _WINDOW_THREAD)
    stalls.start()
    watch = FreezeWatch(io.StringIO(), timing=_TIMING, arm=_Faulthandler().arm, stalls=stalls)

    watch.end_the_process_if_the_close_sticks()

    assert not stalls.watching()


def test_a_window_whose_thread_is_busy_does_not_answer(qapp):
    window = AnsweringWindow()
    answered = []
    asking = threading.Thread(target=lambda: answered.append(window.answers_within(0.05)))

    asking.start()
    asking.join()

    assert answered == [False]


def test_a_window_whose_thread_goes_back_to_its_events_answers(qapp):
    window = AnsweringWindow()
    answered = []
    asking = threading.Thread(target=lambda: answered.append(window.answers_within(3600.0)))

    asking.start()
    wait_until(lambda: answered, pump=QApplication.processEvents)
    asking.join()

    assert answered == [True]


def test_a_slot_holding_the_window_leaves_a_line_saying_how_long_and_where_it_was_looked_at(
        tmp_path):
    crash_log = tmp_path / "origenerator_crash.log"
    child = textwrap.dedent(f"""
        import logging, os, sys, time
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {str(Path.cwd())!r})
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from origenerator.freeze_watch import watch_the_window
        app = QApplication([])
        watch_the_window(app, open({str(crash_log)!r}, "a", encoding="utf-8"))
        def the_slot_that_stalls():
            time.sleep(1.5)
            QTimer.singleShot(300, app.quit)
        QTimer.singleShot(200, the_slot_that_stalls)
        app.exec()
    """)

    ran = run_python(["-c", child])

    assert "Window stalls: each over 0.1 s is written" in ran.stdout, ran.stdout + ran.stderr
    stall = re.search(r"Window stall: (\d+\.\d+) s without answering, from [\d:.]+; "
                      r"\d+ looks at the thread", ran.stdout)
    assert stall, ran.stdout + ran.stderr
    assert float(stall[1]) >= 1.4
