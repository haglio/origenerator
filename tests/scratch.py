from __future__ import annotations

import atexit
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path

_STATE_DIR = "ORIGENERATOR_STATE_DIR"
_MADE_FOR = "ORIGENERATOR_SUITE_STATE_DIR_MADE_FOR"


def _made_now_and_removed_at_exit() -> str:
    made = tempfile.mkdtemp(prefix="origenerator-suite-")
    remove_at_exit(Path(made))
    return made


def give_these_tests_a_state_dir(environ, *, make=_made_now_and_removed_at_exit) -> None:
    these_tests = environ.get("PYTEST_XDIST_WORKER", "the run itself")
    if _STATE_DIR in environ and environ.get(_MADE_FOR, these_tests) == these_tests:
        return
    environ[_STATE_DIR] = make()
    environ[_MADE_FOR] = these_tests


def remove_at_exit(path: Path) -> None:
    atexit.register(_close_the_logs_then_remove, path)


def _close_the_logs_then_remove(path: Path) -> None:
    logging.shutdown()
    remove_scratch(path)


def remove_scratch(path: Path) -> None:
    shutil.rmtree(path, onexc=_clear_the_read_only_bit_and_try_again)


def _clear_the_read_only_bit_and_try_again(function, name, refusal) -> None:
    if function not in (os.unlink, os.rmdir) or not _named_only_here(name):
        raise refusal
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _named_only_here(name) -> bool:
    entry = os.lstat(name)
    return not stat.S_ISLNK(entry.st_mode) and entry.st_nlink == 1
