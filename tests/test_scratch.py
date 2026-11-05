from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tests.children import run_python
from tests.scratch import give_these_tests_a_state_dir, remove_scratch

_A_SUITE_THAT_LOGS_INTO_ITS_STATE_DIR = """
import logging, sys
from pathlib import Path
from tests.scratch import remove_at_exit
state = Path(sys.argv[1])
remove_at_exit(state)
logging.getLogger("the app's own").addHandler(logging.FileHandler(state / "origenerator.log"))
"""


def _scratch_in(tmp_path: Path) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return scratch


def test_a_read_only_file_does_not_keep_the_scratch_standing(tmp_path: Path):
    """git writes its object files read-only, and Windows refuses to delete one."""
    scratch = _scratch_in(tmp_path)
    (scratch / "object").write_bytes(b"what git writes under .git/objects")
    (scratch / "object").chmod(stat.S_IREAD)

    remove_scratch(scratch)

    assert not scratch.exists()


def test_a_file_something_still_has_open_is_named_instead_of_left_behind(tmp_path: Path):
    scratch = _scratch_in(tmp_path)
    with (scratch / "held.log").open("w"), pytest.raises(PermissionError, match=r"held\.log"):
        remove_scratch(scratch)


def test_a_file_linked_in_from_outside_keeps_its_read_only_bit(tmp_path: Path):
    """Windows gives every link to a file that file's read-only bit, so clearing it on
    the link would clear it on a file outside the scratch too."""
    outside = tmp_path / "elsewhere.txt"
    outside.write_bytes(b"a file its owner keeps read-only")
    outside.chmod(stat.S_IREAD)
    scratch = _scratch_in(tmp_path)
    os.link(outside, scratch / "linked.txt")
    try:
        with pytest.raises(PermissionError, match=r"linked\.txt"):
            remove_scratch(scratch)

        assert not outside.stat().st_mode & stat.S_IWRITE
    finally:
        outside.chmod(stat.S_IWRITE)


def test_the_suite_state_dir_goes_at_exit_with_the_apps_log_still_open_in_it(tmp_path: Path):
    state = _scratch_in(tmp_path)

    run_python(["-c", _A_SUITE_THAT_LOGS_INTO_ITS_STATE_DIR, str(state)], check=True)

    assert not state.exists()


def test_a_program_a_worker_starts_keeps_the_state_dir_it_was_handed():
    worker = {"PYTEST_XDIST_WORKER": "gw3"}
    give_these_tests_a_state_dir(worker, make=lambda: "made for gw3")
    handed_to_its_program = worker | {"ORIGENERATOR_STATE_DIR": "the one its test named"}

    give_these_tests_a_state_dir(handed_to_its_program, make=lambda: "made again")

    assert handed_to_its_program["ORIGENERATOR_STATE_DIR"] == "the one its test named"


@pytest.mark.parametrize("started_as", [{}, {"PYTEST_XDIST_WORKER": "gw3"}], ids=["one run", "a worker"])
def test_a_state_dir_named_from_outside_the_suite_is_the_one_its_tests_use(started_as):
    told = started_as | {"ORIGENERATOR_STATE_DIR": "named by whoever started the run"}

    give_these_tests_a_state_dir(told, make=lambda: "made over it")

    assert told["ORIGENERATOR_STATE_DIR"] == "named by whoever started the run"


_A_RUN_THAT_STARTS_A_WORKER = """
import os, subprocess, sys
sys.path.insert(0, "tests")
from scratch import give_these_tests_a_state_dir
give_these_tests_a_state_dir(os.environ, make=lambda: "made for the run")
os.environ["PYTEST_XDIST_WORKER"] = "gw3"
subprocess.run([sys.executable, "-c", sys.argv[1]], check=True)
"""

_A_WORKER = """
import os, sys
sys.path.insert(0, "tests")
from scratch import give_these_tests_a_state_dir
give_these_tests_a_state_dir(os.environ, make=lambda: "made for gw3")
print(os.environ["ORIGENERATOR_STATE_DIR"])
"""


def test_a_worker_makes_a_state_dir_of_its_own_though_windows_hands_it_no_variable_the_run_set_to_nothing():
    as_a_run_starts = {name: value for name, value in os.environ.items()
                       if name not in ("ORIGENERATOR_STATE_DIR", "ORIGENERATOR_SUITE_STATE_DIR_MADE_FOR",
                                       "PYTEST_XDIST_WORKER")}

    ran = run_python(["-c", _A_RUN_THAT_STARTS_A_WORKER, _A_WORKER], env=as_a_run_starts, check=True)

    assert ran.stdout.strip() == "made for gw3"
