"""A child process a test waits on: how it runs, how it ends, and what the test
says when one hangs."""
from __future__ import annotations

import faulthandler
import os
import signal
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

REPO_ROOT = Path(__file__).resolve().parent.parent
HANG_AFTER_S = 120
LOG_LINES_SHOWN = 100


def run_python(args: list[str], *, timeout: float = HANG_AFTER_S, logs: Iterable[Path] = (),
               check: bool = False, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([sys.executable, *args], cwd=REPO_ROOT, timeout=timeout,
                              capture_output=True, encoding="utf-8", errors="replace",
                              check=check, **hidden_subprocess_kwargs(), **kwargs)
    except subprocess.TimeoutExpired as timed_out:
        raise AssertionError("\n".join([
            f"the child was still running {timeout:g} s after it started",
            "--- its output", _text(timed_out.stdout), "--- its errors", _text(timed_out.stderr),
            *(line for log in logs for line in _tail(log))])) from None


def say_where_it_hangs(*, after_s: float = HANG_AFTER_S - 10) -> None:
    faulthandler.dump_traceback_later(after_s)


def end_outright() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


def _text(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", "replace")
    return output or ""


def _tail(log: Path) -> list[str]:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return [f"--- {log.name}: never written"]
    return [f"--- {log.name}, its last {LOG_LINES_SHOWN} lines", *lines[-LOG_LINES_SHOWN:]]
