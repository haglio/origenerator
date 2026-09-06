"""Branch sessions: the env flag the preview launcher sets, and what it still means.

A preview runs on the live install's own library (see config.LIBRARY_STATE_DIR),
so the flag no longer stands for a database of its own; it stands for the one
thing a preview leaves to the live app -- ComfyUI's absence work, which would
outlive the preview in a queue only the app that queued it can cancel.
"""

from pathlib import Path

from origenerator.branch_session import ENV_FLAG, is_branch_session

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_flag_marks_a_branch_session():
    assert is_branch_session({ENV_FLAG: "1"}) is True
    assert is_branch_session({ENV_FLAG: "0"}) is False
    assert is_branch_session({}) is False


def test_the_preview_launcher_marks_the_run_and_borrows_the_primary_venv():
    """The launcher must set the branch flag (else the preview would schedule
    ComfyUI's absence work as if it were the live app) and run the primary's venv
    python (a worktree has no venv, and a bare PATH python lacks PyQt6)."""
    text = (_REPO_ROOT / "launch_preview_branch.vbs").read_text(
        encoding="utf-8", errors="replace")

    assert f"set {ENV_FLAG}=1&&" in text
    assert ".venv\\Scripts\\python.exe" in text
    assert "-m origenerator" in text
    assert "origenerator_launcher.log" in text and "2>&1" in text
