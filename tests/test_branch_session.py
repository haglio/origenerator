"""Branch sessions: the env flag the preview launcher sets, and what it still means.

A preview runs on the live install's own library (see config.LIBRARY_STATE_DIR),
so the flag no longer stands for a database of its own; it stands for the one
thing a preview leaves to the live app -- ComfyUI's absence work, which would
outlive the preview in a queue only the app that queued it can cancel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import dry_run

from origenerator.branch_session import ENV_FLAG, is_branch_session

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_flag_marks_a_branch_session():
    assert is_branch_session({ENV_FLAG: "1"}) is True
    assert is_branch_session({ENV_FLAG: "0"}) is False
    assert is_branch_session({}) is False


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")
def test_the_preview_launcher_marks_the_run_and_borrows_the_primary_venv():
    """The launcher must set the branch flag (else the preview would schedule
    ComfyUI's absence work as if it were the live app) and run the primary's venv
    python (a worktree has no venv, and a bare PATH python lacks PyQt6)."""
    report = dry_run(_REPO_ROOT / "launch_preview_branch.vbs")

    primary = _REPO_ROOT.parents[2]
    assert report.value("environment") == f"{ENV_FLAG}=1"
    assert Path(report.value("interpreter")) == primary / ".venv" / "Scripts" / "python.exe"
    assert Path(report.value("directory")) == _REPO_ROOT
    assert report.value("arguments") == "-m origenerator"
    assert Path(report.value("log")) == _REPO_ROOT / "state" / "origenerator_launcher.log"
