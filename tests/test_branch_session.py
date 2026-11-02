from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import dry_run
from shared_ui.preview import Preview

from origenerator.branch_session import ENV_FLAG, is_branch_session, shown_as

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_flag_marks_a_branch_session():
    assert is_branch_session({ENV_FLAG: "1"}) is True
    assert is_branch_session({ENV_FLAG: "0"}) is False
    assert is_branch_session({}) is False


def test_a_branch_session_is_shown_as_the_preview_its_checkout_describes(monkeypatch):
    described = Preview(feature="the new seed row")
    monkeypatch.setenv(ENV_FLAG, "1")
    monkeypatch.setattr("origenerator.branch_session.preview_of",
                        lambda checkout: described)

    assert shown_as(_REPO_ROOT) is described


def test_the_production_app_is_shown_as_no_preview_wherever_it_runs_from(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    monkeypatch.setattr("origenerator.branch_session.preview_of",
                        lambda checkout: Preview(feature="unused"))

    assert shown_as(_REPO_ROOT) is None


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")
def test_the_preview_launcher_marks_the_run_and_borrows_the_primary_venv():
    report = dry_run(_REPO_ROOT / "launch_preview_branch.vbs")

    primary = _REPO_ROOT.parents[2]
    assert report.value("environment") == f"{ENV_FLAG}=1"
    assert Path(report.value("interpreter")) == primary / ".venv" / "Scripts" / "python.exe"
    assert Path(report.value("directory")) == _REPO_ROOT
    assert report.value("arguments") == "-m origenerator"
    assert Path(report.value("log")) == _REPO_ROOT / "state" / "origenerator_launcher.log"


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")
def test_a_new_previews_first_click_shows_the_snapshots_an_earlier_preview_left():
    report = dry_run(_REPO_ROOT / "launch_preview_branch.vbs")

    primary = _REPO_ROOT.parents[2]
    assert Path(report.value("pictures")) == primary / "state" / "origenerator_launcher.screen" / "preview"
