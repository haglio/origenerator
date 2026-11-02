from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_support.launch_smoke import (
    assert_an_unresolvable_import_is_caught,
    assert_every_import_resolves,
    assert_the_walk_reached,
    launch_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "origenerator"

LAUNCH_FILES = (
    REPO_ROOT / PACKAGE / "__main__.py",
    REPO_ROOT / PACKAGE / "app.py",
)

_REACHED_ONLY_FROM_INSIDE_MAIN = (
    "origenerator.gui.core",
    "origenerator.db",
    "origenerator.comfyui_client",
)


def _launch_imports() -> list[str]:
    return launch_imports(PACKAGE, LAUNCH_FILES)


def _run_in_a_fresh_interpreter(statements: list[str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"

    driver = "\n".join(
        [
            "import origenerator.content as _content",
            "_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT",
            *statements,
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", driver],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_launch_imports_everything_it_names():
    assert_every_import_resolves(_run_in_a_fresh_interpreter, _launch_imports())


def test_the_walk_reaches_the_imports_buried_in_main():
    assert_the_walk_reached(_launch_imports(), _REACHED_ONLY_FROM_INSIDE_MAIN)


def test_a_launch_import_that_cannot_resolve_fails_here():
    assert_an_unresolvable_import_is_caught(
        _run_in_a_fresh_interpreter, _launch_imports(), "origenerator.db")
