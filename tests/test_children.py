from __future__ import annotations

import ctypes
import os
import subprocess
import textwrap

import pytest

from tests.children import run_python

_MAKES_A_SOUND_OUTPUT_THEN_ENDS = textwrap.dedent("""
    import sys
    from PyQt6.QtMultimedia import QAudioOutput
    from PyQt6.QtWidgets import QApplication
    from tests.children import end_outright
    app = QApplication(sys.argv[:1])
    output = QAudioOutput()
    print("made", flush=True)
    end_outright()
""")

_SAYS_AND_LOGS_SOMETHING_THEN_HANGS = textwrap.dedent("""
    import faulthandler, sys, time
    from pathlib import Path
    faulthandler.dump_traceback_later(1)
    print("the line it said", flush=True)
    Path(sys.argv[1]).write_text("the line it logged\\n", encoding="utf-8")

    def waits_forever():
        while True:
            time.sleep(1)

    waits_forever()
""")


_ROOM_FOR_A_CHILD_TO_START_UNDER_LOAD_S = 30


def test_a_child_still_running_at_its_timeout_fails_with_what_it_said_where_it_was_and_its_log(
        tmp_path):
    log = tmp_path / "child.log"
    with pytest.raises(AssertionError) as failure:
        run_python(["-c", _SAYS_AND_LOGS_SOMETHING_THEN_HANGS, str(log)],
                   timeout=_ROOM_FOR_A_CHILD_TO_START_UNDER_LOAD_S, logs=[log])

    reported = str(failure.value)
    assert "the line it said" in reported
    assert "in waits_forever" in reported
    assert "the line it logged" in reported


def test_a_child_ended_outright_while_qt_still_probes_the_sound_devices_ends_at_once():
    ran = run_python(["-c", _MAKES_A_SOUND_OUTPUT_THEN_ENDS], timeout=30,
                     env=os.environ | {"QT_QPA_PLATFORM": "offscreen"})

    assert ran.stdout.splitlines() == ["made"]


_SAYS_ITS_PRIORITY_CLASS = textwrap.dedent("""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    print(kernel32.GetPriorityClass(kernel32.GetCurrentProcess()), flush=True)
""")


@pytest.fixture
def a_run_giving_way_to_what_he_is_using():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    this_run = kernel32.GetCurrentProcess()
    its_own = kernel32.GetPriorityClass(this_run)
    kernel32.SetPriorityClass(this_run, subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    try:
        yield
    finally:
        kernel32.SetPriorityClass(this_run, its_own)


def test_a_child_runs_at_normal_priority_so_other_runs_below_normal_cannot_starve_it(
        a_run_giving_way_to_what_he_is_using):
    ran = run_python(["-c", _SAYS_ITS_PRIORITY_CLASS])

    assert int(ran.stdout) == subprocess.NORMAL_PRIORITY_CLASS
