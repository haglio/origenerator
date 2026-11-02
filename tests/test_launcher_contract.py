from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import dry_run

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "launch_origenerator.vbs"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


def test_the_launcher_is_where_the_pinned_shortcut_points():
    assert LAUNCHER.is_file()


@on_windows
def test_the_launcher_runs_the_package_from_this_checkout_on_its_venv():
    """A python off PATH finds the repo directory as a namespace package instead of the editable install."""
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
    report = dry_run(REPO_ROOT / "sort_images.vbs")

    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == "-m origenerator.sort_images"
    assert report.value("environment") == "ORIGENERATOR_BRANCH_SESSION=1"
    assert Path(report.value("log")) == REPO_ROOT / "state" / "sort_images_launcher.log"


@on_windows
@pytest.mark.skipif(".claude" not in REPO_ROOT.parts,
                    reason="only a worktree has the primary checkout above it")
def test_both_of_those_windows_run_on_the_primary_checkouts_venv():
    for name in ("sort_images.vbs", "check_animations.vbs"):
        report = dry_run(REPO_ROOT / name)

        assert Path(report.value("interpreter")) == (
            REPO_ROOT.parents[2] / ".venv" / "Scripts" / "python.exe")


@on_windows
def test_the_animation_launcher_reads_the_live_library_too():
    report = dry_run(REPO_ROOT / "check_animations.vbs")

    assert report.value("arguments") == "-m origenerator.check_animations"
    assert report.value("environment") == "ORIGENERATOR_BRANCH_SESSION=1"
