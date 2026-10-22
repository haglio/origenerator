"""The child processes tests wait on: how one that hangs is reported, and how one ends."""
from __future__ import annotations

import os
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
    import sys, time
    from pathlib import Path
    from tests.children import say_where_it_hangs
    say_where_it_hangs(after_s=1)
    print("the line it said", flush=True)
    Path(sys.argv[1]).write_text("the line it logged\\n", encoding="utf-8")

    def waits_forever():
        while True:
            time.sleep(1)

    waits_forever()
""")


def test_a_child_still_running_at_its_timeout_fails_with_what_it_said_where_it_was_and_its_log(
        tmp_path):
    log = tmp_path / "child.log"
    with pytest.raises(AssertionError) as failure:
        run_python(["-c", _SAYS_AND_LOGS_SOMETHING_THEN_HANGS, str(log)], timeout=8, logs=[log])

    reported = str(failure.value)
    assert "the line it said" in reported
    assert "in waits_forever" in reported
    assert "the line it logged" in reported


def test_a_child_ended_outright_while_qt_still_probes_the_sound_devices_ends_at_once():
    ran = run_python(["-c", _MAKES_A_SOUND_OUTPUT_THEN_ENDS], timeout=30,
                     env=os.environ | {"QT_QPA_PLATFORM": "offscreen"})

    assert ran.stdout.splitlines() == ["made"]
