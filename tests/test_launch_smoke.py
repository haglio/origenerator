"""The launch smoke test: everything ``python -m origenerator`` imports, imported.

The suite can be entirely green while the icon does nothing, and this is the
gap. ``main()`` imports almost the whole app *inside the function* -- the
database, the recovery bin, the ComfyUI client, the importer, the main window --
so nothing about a break in one of them reaches a test that imports
``origenerator.app`` and stops there. And every other test here runs under
``tests/conftest.py``, which pins the content overlay and puts ``shared_ui`` on
``sys.path`` before the first import; the launcher does neither. A run can
therefore pass on modules the launch cannot even load.

So this drives the launch's import phase the way the launcher does: a fresh
interpreter, this repo as the working directory, the launcher's ``PYTHONPATH``
and nothing inherited, and the committed example overlay standing in for the
git-ignored local one -- which is also what a public checkout and CI have.

The walk that reads those imports off the AST, and the three assertions that
replay them, are ``app_support.launch_smoke``: seven repos carried a copy of the
same machinery, already drifting in signature. What stays here is the half that
is this app's -- which two files the launch executes, and how its launcher
starts an interpreter.

They come off the AST rather than a list maintained here, because a
hand-written list is exactly what would drift: the next lazy import added to
``main()`` would not be in it, and the guard would quietly stop covering the
thing it was written for. They are replayed as whole ``from X import a, b``
statements, not as ``import X``, so a symbol the launch names but the module no
longer defines fails here too -- a renamed ``Database`` is the same dead icon as
a syntax error.
"""
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
LAUNCHER = REPO_ROOT / "launch_origenerator.vbs"

# The two files ``python -m origenerator`` runs. Every helper ``main()`` calls
# lives in ``app.py``, so between them they hold the whole launch sequence.
LAUNCH_FILES = (
    REPO_ROOT / PACKAGE / "__main__.py",
    REPO_ROOT / PACKAGE / "app.py",
)

# Modules the launch is known to reach only from inside ``main()``. Asserted
# present so a walk that silently found nothing -- a renamed file, a parse that
# returned an empty tree -- cannot pass as a clean launch.
_REACHED_ONLY_FROM_INSIDE_MAIN = (
    "origenerator.gui.main_window",
    "origenerator.db",
    "origenerator.comfyui_client",
)


def _launch_imports() -> list[str]:
    return launch_imports(PACKAGE, LAUNCH_FILES)


def _checkouts_parent():
    """The directory holding the sibling checkouts — ``REPO_ROOT``'s own parent
    in the primary layout the launcher models.  A WORKTREE's parent is
    ``.claude/worktrees``, which holds no siblings, so walk up to the level
    that does (the same walk the app's own sibling resolution makes); without
    this, every import of a sibling read as a launch failure in any worktree
    run of the suite."""
    for parent in [REPO_ROOT.parent, *REPO_ROOT.parents]:
        if (parent / "app_support" / "app_support" / "__init__.py").exists():
            return parent
    return REPO_ROOT.parent


def _run_in_a_fresh_interpreter(statements: list[str]) -> subprocess.CompletedProcess:
    """Run them the way ``launch_origenerator.vbs`` runs the app.

    The launcher cds to this repo and sets ``PYTHONPATH`` to the checkouts'
    parent, so that is the whole path story -- any ``PYTHONPATH`` a developer or
    pytest happens to be carrying is dropped, because the icon does not get it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(_checkouts_parent())
    env["QT_QPA_PLATFORM"] = "offscreen"

    driver = "\n".join(
        [
            # Before anything that reads content at import time: a public
            # checkout has only the committed example, so that is what the
            # launch has to come up on.
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
    )


def test_the_launch_imports_everything_it_names():
    """Failing here means the icon does nothing: the traceback goes to the
    launcher log in ``state/``, and no window ever appears."""
    assert_every_import_resolves(_run_in_a_fresh_interpreter, _launch_imports())


def test_the_walk_reaches_the_imports_buried_in_main():
    """The guard above is only worth anything if the walk found the lazy ones --
    which are most of the launch, and all of what a module-level import test
    already covered."""
    assert_the_walk_reached(_launch_imports(), _REACHED_ONLY_FROM_INSIDE_MAIN)


def test_a_launch_import_that_cannot_resolve_fails_here():
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    assert_an_unresolvable_import_is_caught(
        _run_in_a_fresh_interpreter, _launch_imports(), "origenerator.db")


def test_the_launcher_runs_the_package_from_this_repo_on_its_own_venv():
    """A python off PATH finds the repo directory as a namespace package
    instead of the editable install, and dies while importing -- before any
    window, with nothing on screen to say so."""
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")

    assert ".venv\\Scripts\\python.exe" in text
    assert "-m origenerator" in text
    # The working directory and PYTHONPATH are what _run_in_a_fresh_interpreter
    # mirrors, so a launcher that stopped setting either would leave this file
    # checking an arrangement nothing runs under.
    assert "cd /d" in text
    assert "set PYTHONPATH=" in text
    assert "parentDir" in text


def test_the_launcher_keeps_what_a_failed_launch_wrote_to_its_console():
    """The launcher runs the app in a hidden window, so a crash during import
    writes its traceback to a console nobody sees. Redirecting it to
    ``state/origenerator_launcher.log`` is what makes the next one readable."""
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")

    assert "origenerator_launcher.log" in text
    assert "2>&1" in text
