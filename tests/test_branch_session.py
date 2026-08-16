"""Branch sessions — the env flag, the one-time DB seed, and the launcher."""

import json
import sqlite3
from pathlib import Path

from origenerator.branch_session import (
    ENV_FLAG, is_branch_session, seed_branch_db, session_trash,
)

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


def test_a_branch_sessions_trash_neither_takes_files_nor_reclaims_them(tmp_path, monkeypatch):
    # A preview has no standing to destroy library files, and none to purge what
    # an earlier preview took either: those batches hold the only copies left of
    # files the live app's own rows still point at.
    monkeypatch.setenv(ENV_FLAG, "1")
    held = tmp_path / "trash" / "batch" / "0_clip.mp4"
    held.parent.mkdir(parents=True)
    held.write_bytes(b"the only copy")
    library_file = tmp_path / "output" / "clip.mp4"
    library_file.parent.mkdir()
    library_file.write_bytes(b"data")

    trash = session_trash(tmp_path / "trash")
    batch = trash.store([library_file])
    assert trash.purge_orphans([]) == 0  # even told nothing is held, it takes nothing

    assert library_file.exists() and batch.moves == []
    assert held.exists()
    batch.restore()   # and an undo of a delete that moved nothing moves nothing
    assert library_file.exists()


def test_a_live_session_gets_a_working_trash(tmp_path):
    library_file = tmp_path / "output" / "clip.mp4"
    library_file.parent.mkdir(parents=True)
    library_file.write_bytes(b"data")

    session_trash(tmp_path / "trash").store([library_file])

    assert not library_file.exists()


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


# --- adoption: a branch session's generations come home at live-app launch


def _live_db(tmp_path):
    from origenerator.db import Database
    return Database(tmp_path / "live" / "origenerator.db")


def _branch_db_with(tmp_path, worktree, rows):
    """A worktree state DB holding *rows*, built through the real schema."""
    from origenerator.db import Database
    path = tmp_path / "worktrees" / worktree / "state" / "origenerator.db"
    db = Database(path)
    for row in rows:
        db.insert_generation(
            prompt_id=row["prompt_id"], workflow_name="sdxl_t2i",
            workflow_version="v1", positive_prompt=row.get("prompt", "a fox"),
            negative_prompt="", seed=7, params_json="{}", workflow_json="{}",
        )
        db.update_generation(
            row["prompt_id"], status=row.get("status", "completed"),
            output_files=json.dumps([{"filename": row["filename"], "subfolder": ""}]),
        )
    return path


def _output_file(tmp_path, name):
    from PIL import Image
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    Image.new("RGB", (16, 16), (90, 40, 160)).save(out / name, "PNG")
    return out


def test_adoption_brings_a_branch_generation_home(tmp_path):
    from origenerator.branch_session import adopt_branch_rows
    live = _live_db(tmp_path)
    _branch_db_with(tmp_path, "wt-a", [{"prompt_id": "b1", "filename": "fox1.png"}])
    out = _output_file(tmp_path, "fox1.png")

    adopted = adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs")

    assert adopted == 1
    row = live.get_generation("b1")
    assert row is not None
    assert (row.get("source") or "generated") == "generated"  # not an import
    thumb = row.get("thumbnail_path")
    assert thumb and str(tmp_path / "thumbs") in thumb  # regenerated into live state
    # Idempotent: the next launch adopts nothing new.
    assert adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs") == 0


def test_adoption_upgrades_an_earlier_import_of_the_same_file(tmp_path):
    from origenerator.branch_session import adopt_branch_rows
    live = _live_db(tmp_path)
    live.insert_generation(
        prompt_id="imp1", workflow_name="unknown", workflow_version="imported",
        positive_prompt=None, negative_prompt=None, seed=None,
        params_json="{}", workflow_json="{}", source="imported",
    )
    live.update_generation(
        "imp1", status="completed",
        output_files=json.dumps([{"filename": "fox2.png", "subfolder": ""}]),
    )
    _branch_db_with(tmp_path, "wt-a", [{"prompt_id": "b2", "filename": "fox2.png"}])
    out = _output_file(tmp_path, "fox2.png")

    assert adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs") == 1
    assert live.get_generation("imp1") is None      # the reconstruction made way
    assert live.get_generation("b2") is not None    # for the original


def test_adoption_defers_to_a_first_class_live_row(tmp_path):
    from origenerator.branch_session import adopt_branch_rows
    live = _live_db(tmp_path)
    live.insert_generation(
        prompt_id="mine", workflow_name="sdxl_t2i", workflow_version="v1",
        positive_prompt="a fox", negative_prompt="", seed=7,
        params_json="{}", workflow_json="{}",
    )
    live.update_generation(
        "mine", status="completed",
        output_files=json.dumps([{"filename": "fox3.png", "subfolder": ""}]),
    )
    _branch_db_with(tmp_path, "wt-a", [{"prompt_id": "b3", "filename": "fox3.png"}])
    out = _output_file(tmp_path, "fox3.png")

    assert adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs") == 0
    assert live.get_generation("mine") is not None
    assert live.get_generation("b3") is None


def test_adoption_skips_rows_whose_file_is_gone(tmp_path):
    from origenerator.branch_session import adopt_branch_rows
    live = _live_db(tmp_path)
    _branch_db_with(tmp_path, "wt-a", [{"prompt_id": "b4", "filename": "gone.png"}])
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)

    assert adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs") == 0
    assert live.get_generation("b4") is None
