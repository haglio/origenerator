from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import dry_run, launchers

REPO_ROOT = Path(__file__).resolve().parents[1]

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


@on_windows
def test_the_everyday_launcher_is_no_branch_session():
    assert dry_run(REPO_ROOT / "launch_origenerator.vbs").values("environment") == []


def test_both_library_windows_run_on_the_primary_checkouts_venv():
    assert {launcher.file for launcher in launchers(REPO_ROOT) if launcher.venv == "primary" and not launcher.preview} == {
        "sort_images.vbs", "check_animations.vbs"}


@on_windows
@pytest.mark.parametrize(("file", "module"), [
    ("sort_images.vbs", "origenerator.action_setter_tool"),
    ("check_animations.vbs", "origenerator.check_animations"),
])
def test_a_library_window_reads_the_live_library(file: str, module: str):
    report = dry_run(REPO_ROOT / file)

    assert report.value("arguments") == f"-m {module}"
    assert report.value("environment") == "ORIGENERATOR_BRANCH_SESSION=1"
