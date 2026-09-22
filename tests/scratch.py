"""The suite's own scratch, and how it is taken away again."""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import stat
from pathlib import Path


def remove_at_exit(path: Path) -> None:
    """Remove *path* as the process ends, once the logs open in it are closed."""
    atexit.register(_close_the_logs_then_remove, path)


def _close_the_logs_then_remove(path: Path) -> None:
    logging.shutdown()
    remove_scratch(path)


def remove_scratch(path: Path) -> None:
    """Delete *path* and all of it, clearing the read-only bit Windows stops on."""
    shutil.rmtree(path, onexc=_clear_the_read_only_bit_and_try_again)


def _clear_the_read_only_bit_and_try_again(function, name, refusal) -> None:
    if function not in (os.unlink, os.rmdir) or not _named_only_here(name):
        raise refusal
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _named_only_here(name) -> bool:
    """Whether clearing *name*'s read-only bit would reach nothing outside."""
    entry = os.lstat(name)
    return not stat.S_ISLNK(entry.st_mode) and entry.st_nlink == 1
