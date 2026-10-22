"""The child processes tests wait on: how one that hangs is reported."""
from __future__ import annotations

import textwrap

import pytest

from tests.children import run_python

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

