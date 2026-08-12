"""Branch sessions — the env flag, the one-time DB seed, and the launcher."""

import sqlite3
from pathlib import Path

from origenerator.branch_session import ENV_FLAG, is_branch_session, seed_branch_db

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_db(path, rows=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE generations (prompt_id TEXT)")
        conn.executemany("INSERT INTO generations VALUES (?)", [(r,) for r in rows])
    return path


def _prompt_ids(path):
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT prompt_id FROM generations")]


def test_the_flag_marks_a_branch_session():
    assert is_branch_session({ENV_FLAG: "1"}) is True
    assert is_branch_session({ENV_FLAG: "0"}) is False
    assert is_branch_session({}) is False


def test_seeding_copies_the_primary_db_once(tmp_path):
    primary = _make_db(tmp_path / "primary" / "origenerator.db", rows=["p1", "p2"])
    branch = tmp_path / "branch" / "origenerator.db"

    assert seed_branch_db(primary, branch) is True
    assert _prompt_ids(branch) == ["p1", "p2"]


def test_seeding_never_overwrites_the_branchs_own_db(tmp_path):
    primary = _make_db(tmp_path / "primary" / "origenerator.db", rows=["p1"])
    branch = _make_db(tmp_path / "branch" / "origenerator.db", rows=["mine"])

    assert seed_branch_db(primary, branch) is False
    assert _prompt_ids(branch) == ["mine"]  # the branch's own work, untouched


def test_seeding_without_a_primary_db_is_a_no_op(tmp_path):
    branch = tmp_path / "branch" / "origenerator.db"
    assert seed_branch_db(tmp_path / "primary" / "origenerator.db", branch) is False
    assert not branch.exists()


def test_the_preview_launcher_marks_the_run_and_borrows_the_primary_venv():
    """The launcher must set the branch flag (else the session crawls through the
    full library scan the flag exists to skip) and run the primary's venv python
    (a worktree has no venv, and a bare PATH python lacks PyQt6)."""
    text = (_REPO_ROOT / "launch_preview_branch.vbs").read_text(
        encoding="utf-8", errors="replace")

    assert f"set {ENV_FLAG}=1&&" in text
    assert ".venv\\Scripts\\python.exe" in text
    assert "-m origenerator" in text
    assert "origenerator_launcher.log" in text and "2>&1" in text
