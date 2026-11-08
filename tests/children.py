from __future__ import annotations

import faulthandler
import os
import signal
import subprocess
import sys
import threading
import time
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
                              check=check, **a_child_no_run_can_starve(), **kwargs)
    except subprocess.TimeoutExpired as timed_out:
        raise _still_running(f"{timeout:g} s after it started", timed_out.stdout, timed_out.stderr,
                             logs) from None


def run_python_timed_from(ready: str, args: list[str], *, timeout: float,
                          start_timeout: float = HANG_AFTER_S, **kwargs) -> subprocess.CompletedProcess:
    child = subprocess.Popen([sys.executable, *args], cwd=REPO_ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                             **a_child_no_run_can_starve(), **kwargs)
    said_ready = threading.Event()
    output: list[str] = []
    errors: list[str] = []

    def read_output() -> None:
        for line in child.stdout:
            output.append(line)
            if line.rstrip("\r\n") == ready:
                said_ready.set()

    readers = [threading.Thread(target=read_output, daemon=True),
               threading.Thread(target=lambda: errors.extend(child.stderr), daemon=True)]
    for reader in readers:
        reader.start()

    def collected() -> subprocess.CompletedProcess:
        for reader in readers:
            reader.join()
        return subprocess.CompletedProcess(child.args, child.returncode, "".join(output), "".join(errors))

    def ended_still_running(when: str) -> AssertionError:
        child.kill()
        child.wait()
        ran = collected()
        return _still_running(when, ran.stdout, ran.stderr, ())

    started = time.monotonic()
    while not said_ready.wait(0.1):
        if child.poll() is not None:
            return collected()
        if time.monotonic() - started > start_timeout:
            raise ended_still_running(f"{start_timeout:g} s after it started, without saying {ready!r}")
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ended_still_running(f"{timeout:g} s after it said {ready!r}") from None
    return collected()


def _still_running(when: str, output: str | bytes | None, errors: str | bytes | None,
                   logs: Iterable[Path]) -> AssertionError:
    return AssertionError("\n".join([
        f"the child was still running {when}",
        "--- its output", _text(output), "--- its errors", _text(errors),
        *(line for log in logs for line in _tail(log))]))


def a_child_no_run_can_starve() -> dict:
    return hidden_subprocess_kwargs(creationflags=subprocess.NORMAL_PRIORITY_CLASS)


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
