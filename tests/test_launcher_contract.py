"""What launch_origenerator.vbs runs, asked of the launcher under the real script host.

The launcher is rendered from its spec in pyproject.toml by app_support.launcher,
whose own tests hold what every launcher does: the venv's interpreter and never
one off PATH, nothing on PYTHONPATH, Option Explicit, a dialog naming a missing
venv.  What is Origenerator's is asked of this one; the branch preview's
launcher is asked in tests/test_branch_session.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import assert_launchers_match_their_specs, dry_run

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "launch_origenerator.vbs"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


def test_the_launcher_is_where_the_pinned_shortcut_points():
    assert LAUNCHER.is_file()


def test_the_launchers_are_what_their_specs_render():
    assert_launchers_match_their_specs(REPO_ROOT)


@on_windows
def test_the_launcher_runs_the_package_from_this_checkout_on_its_venv():
    """A python off PATH finds the repo directory as a namespace package instead
    of the editable install, and dies while importing -- before any window."""
    report = dry_run(LAUNCHER)

    assert Path(report.value("interpreter")).parent == REPO_ROOT / ".venv" / "Scripts"
    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == "-m origenerator"
    assert report.values("environment") == []


@on_windows
def test_a_launch_that_dies_importing_leaves_its_traceback_in_state():
    report = dry_run(LAUNCHER)

    assert Path(report.value("log")) == REPO_ROOT / "state" / "origenerator_launcher.log"


@on_windows
def test_the_sorting_launcher_sorts_the_live_library_whichever_checkout_runs_it():
    """Its own launcher, because sorting is a window of its own: it wants the
    library and nothing else the app holds, and it is run beside the app or
    instead of it.

    The live library from any checkout, because what is being answered is the
    real library -- a branch's own database is one nobody will ever animate from,
    and a run of sorting spent on it is lost. So it borrows what the preview
    launcher does: the primary's venv, and the flag that points the library at
    the live install (config.LIBRARY_STATE_DIR). In the primary both are itself."""
    report = dry_run(REPO_ROOT / "sort_images.vbs")

    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == "-m origenerator.sort_images"
    assert report.value("environment") == "ORIGENERATOR_BRANCH_SESSION=1"
    assert Path(report.value("log")) == REPO_ROOT / "state" / "sort_images_launcher.log"


@on_windows
@pytest.mark.skipif(".claude" not in REPO_ROOT.parts,
                    reason="only a worktree has the primary checkout above it")
def test_both_of_those_windows_run_on_the_primary_checkouts_venv():
    """A worktree has no virtual environment of its own, and these two windows
    read and write the live install's library, so they borrow the primary's --
    three folders up from a worktree. Asked only from a worktree, because that
    is where three folders up IS the primary: the shared launcher spells that
    climb the same way wherever the file sits, so from a plain checkout it
    answers with a folder holding no virtual environment at all."""
    for name in ("sort_images.vbs", "check_animations.vbs"):
        report = dry_run(REPO_ROOT / name)

        assert Path(report.value("interpreter")) == (
            REPO_ROOT.parents[2] / ".venv" / "Scripts" / "python.exe")


@on_windows
def test_the_animation_launcher_reads_the_live_library_too():
    """The videos it judges and the settings it writes are the live install's,
    for the reason the sorting launcher's are."""
    report = dry_run(REPO_ROOT / "check_animations.vbs")

    assert report.value("arguments") == "-m origenerator.check_animations"
    assert report.value("environment") == "ORIGENERATOR_BRANCH_SESSION=1"
