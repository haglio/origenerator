"""Which modules are allowed to need Qt, held as an equality.

Most of this package is a Qt-free library with a Qt package (`origenerator.gui`)
on top of it, and several modules say so in their own docstrings — `completion`
claims it is "Qt-free so the reconciler can use it without a running UI". That
was not true for anything downstream of `ComfyUIClient`, which is a `QThread`:
its eleven HTTP calls needed nothing from Qt, but living on a thread meant every
consumer of them carried Qt anyway.

So this counts, in a fresh interpreter each time, because PyQt6 is loaded long
before any test in this process runs.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Top-level modules of `origenerator` that must load with no Qt at all. Held as
# a list rather than a rule because the rule ("everything but the gui package")
# is not quite true: `comfyui_client` IS the Qt thread and `icon_design` draws
# with QPainter.
QT_FREE = (
    # It builds the QApplication -- inside main(), like every other import it
    # makes, so the splash is already up before the slow ones run. Importing it
    # costs nothing, which is what tests/test_launch_smoke.py replays off its AST.
    "origenerator.app",
    "origenerator.comfyui_api",
    "origenerator.completion",
    "origenerator.inflight",
    "origenerator.bookmark_reconcile",
    "origenerator.base_backfill",
    "origenerator.importer",
    "origenerator.db",
    "origenerator.recovery",
    "origenerator.branch_session",
    "origenerator.content",
    "origenerator.config",
    "origenerator.undo_stack",
    "origenerator.gallery_actions",
)

# The two that legitimately do, at import. `comfyui_client` is one because it is
# the websocket pump: it emits Qt signals from a thread, which is the one thing
# about ComfyUI that genuinely needs Qt. Its eleven HTTP calls do not, and no
# longer live on it.
NEEDS_QT = (
    "origenerator.comfyui_client",
    "origenerator.icon_design",
)


def _qt_after_importing(module: str) -> bool:
    """Whether importing *module* in a fresh interpreter pulled PyQt6 in."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p)
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys\n"
         "import origenerator.content as content\n"
         "content.LOCAL_CONTENT = content.EXAMPLE_CONTENT\n"
         f"import {module}\n"
         'print("PyQt6" in sys.modules)'],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "True"


@pytest.mark.parametrize("module", QT_FREE)
def test_a_module_that_claims_to_be_qt_free_is(module):
    assert _qt_after_importing(module) is False


@pytest.mark.parametrize("module", NEEDS_QT)
def test_the_modules_that_do_need_qt_are_only_these(module):
    """The control. Without it the list above could pass by importing nothing at
    all, and the boundary would be decorative."""
    assert _qt_after_importing(module) is True
