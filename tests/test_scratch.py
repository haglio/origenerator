"""The suite's own scratch goes when the suite does, whatever is in it."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.scratch import remove_scratch

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
    """Every link to a file shares that file's read-only bit, so clearing it on
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
    """The app opens its log in the state dir at import and nothing closes it
    before the suite's exit hook runs: 811 origenerator-suite-* dirs were
    standing in the system temp dir, each holding its origenerator.log."""
    state = _scratch_in(tmp_path)

    subprocess.run([sys.executable, "-c", _A_SUITE_THAT_LOGS_INTO_ITS_STATE_DIR, str(state)],
                   cwd=_REPO_ROOT, capture_output=True, text=True, check=True)

    assert not state.exists()
