"""Branch sessions — the env flag, the one-time DB seed, and the launcher."""

import ast
import json
import re
import sqlite3
from pathlib import Path

from origenerator.branch_session import (
    ENV_FLAG,
    adopt_branch_curation,
    adopt_branch_rows,
    is_branch_session,
    seed_branch_db,
    session_trash,
)
from origenerator.db import Database

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


def test_adoption_brings_a_spoken_request_home_with_its_generation(tmp_path):
    # Otherwise a request made while judging a preview lands in the live gallery
    # as an ordinary re-roll — the one thing it isn't.
    from origenerator.branch_session import adopt_branch_rows
    from origenerator.db import Database
    live = _live_db(tmp_path)
    branch_path = _branch_db_with(
        tmp_path, "wt-a", [{"prompt_id": "b5", "filename": "fox5.png"}])
    Database(branch_path).record_request(
        prompt_id="b5", source_prompt_id="asked-about",
        heard="Request, no hat, over.", term="hat", polarity="remove",
        action="dropped", old_positive="a fox, a hat", old_negative="",
        new_positive="a fox", new_negative="",
    )
    out = _output_file(tmp_path, "fox5.png")

    adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs")

    record = live.get_request("b5")
    assert record is not None
    assert record["heard"] == "Request, no hat, over."
    assert record["source_prompt_id"] == "asked-about"


def test_adoption_survives_a_branch_database_predating_requests(tmp_path):
    # A worktree seeded before the table existed must still hand its rows over.
    import sqlite3

    from origenerator.branch_session import adopt_branch_rows
    branch_path = _branch_db_with(
        tmp_path, "wt-a", [{"prompt_id": "b6", "filename": "fox6.png"}])
    with sqlite3.connect(branch_path) as conn:
        conn.execute("DROP TABLE requests")
    live = _live_db(tmp_path)
    out = _output_file(tmp_path, "fox6.png")

    assert adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs") == 1


def test_adoption_costs_no_query_per_seeded_row(tmp_path):
    """A worktree database is a *copy* of the live one, so nearly every row in it
    is a row the live app already has. Asking the database about each of those
    one at a time made launch cost a query per seeded row per worktree — 10,000
    round trips, twelve seconds of a startup that used to take half of one, and
    it grew every time an agent opened another worktree. The rows the live app
    already holds are in hand before the scan starts; recognizing them there is
    what keeps the cost flat."""
    from origenerator.branch_session import adopt_branch_rows
    live = _live_db(tmp_path)
    seeded = [{"prompt_id": f"s{i}", "filename": f"seed{i}.png"} for i in range(40)]
    for row in seeded:
        live.insert_generation(
            prompt_id=row["prompt_id"], workflow_name="sdxl_t2i",
            workflow_version="v1", positive_prompt="a fox", negative_prompt="",
            seed=7, params_json="{}", workflow_json="{}",
        )
        live.update_generation(
            row["prompt_id"], status="completed",
            output_files=json.dumps([{"filename": row["filename"], "subfolder": ""}]),
        )
    # Two worktrees, each carrying the whole seeded copy plus one row of its own.
    _branch_db_with(tmp_path, "wt-a", seeded + [{"prompt_id": "a1", "filename": "own_a.png"}])
    _branch_db_with(tmp_path, "wt-b", seeded + [{"prompt_id": "b1", "filename": "own_b.png"}])
    out = _output_file(tmp_path, "own_a.png")
    _output_file(tmp_path, "own_b.png")

    calls = []
    real = type(live).get_generation
    type(live).get_generation = lambda self, pid: (calls.append(pid), real(self, pid))[1]
    try:
        adopted = adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs")
    finally:
        type(live).get_generation = real

    assert adopted == 2                     # each worktree's own row came home
    assert len(calls) < len(seeded), calls  # and the 80 seeded ones cost no queries


# --- adoption: the bookmarks a branch session made come home too


def _completed_row(db, prompt_id, filename):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v1",
        positive_prompt="a fox", negative_prompt="", seed=7,
        params_json="{}", workflow_json="{}",
    )
    db.update_generation(
        prompt_id, status="completed",
        output_files=json.dumps([{"filename": filename, "subfolder": ""}]),
    )


def _seeded_pair(tmp_path, worktree="wt-a", prompt_id="lib1"):
    """A live database and a worktree copy of it, as seeding leaves them: the
    same library row in both, starred in neither."""
    from origenerator.db import Database
    live = _live_db(tmp_path)
    _completed_row(live, prompt_id, "lib1.png")
    branch = Database(tmp_path / "worktrees" / worktree / "state" / "origenerator.db")
    _completed_row(branch, prompt_id, "lib1.png")
    return live, branch


def _adopt(live, tmp_path):
    from origenerator.branch_session import adopt_branch_curation
    return adopt_branch_curation(live, tmp_path / "worktrees")


def test_a_star_made_in_a_preview_comes_home(tmp_path):
    # The star adoption used to lose entirely: the item already exists here, so
    # row adoption skips it by design and the bookmark went with the worktree.
    live, branch = _seeded_pair(tmp_path)
    branch.set_generation_starred("lib1", True)

    assert _adopt(live, tmp_path) == 1
    assert live.get_generation("lib1")["starred"] == 1
    assert _adopt(live, tmp_path) == 0  # and the next launch has nothing to do


def test_a_folder_bookmark_made_in_a_preview_comes_home(tmp_path):
    live, branch = _seeded_pair(tmp_path)
    branch.set_folder_starred("sdxl_t2i/model-a", True)
    branch.rename_folder("sdxl_t2i/model-a", "the good one")

    assert _adopt(live, tmp_path) == 1
    meta = live.folder_meta_map()["sdxl_t2i/model-a"]
    assert meta["starred"] is True and meta["custom_name"] == "the good one"


def test_a_first_sighting_adds_bookmarks_but_takes_none_away(tmp_path):
    """A worktree may have been seeded months ago, so a bookmark it lacks says
    nothing about the user's intent — only that this app has moved on since."""
    live, branch = _seeded_pair(tmp_path)
    live.set_generation_starred("lib1", True)      # starred here, after the seed
    live.set_folder_starred("sdxl_t2i/model-a", True)

    assert _adopt(live, tmp_path) == 0
    assert live.get_generation("lib1")["starred"] == 1
    assert live.folder_meta_map()["sdxl_t2i/model-a"]["starred"] is True


def test_a_bookmark_the_user_has_since_dropped_is_not_reinstated(tmp_path):
    """The reason a baseline is kept at all: without one, a worktree still
    carrying yesterday's star would re-light it at every single launch."""
    live, branch = _seeded_pair(tmp_path)
    branch.set_generation_starred("lib1", True)
    _adopt(live, tmp_path)
    live.set_generation_starred("lib1", False)     # the user changed their mind

    assert _adopt(live, tmp_path) == 0
    assert live.get_generation("lib1")["starred"] == 0


def test_an_unstar_made_in_a_preview_crosses_over_once_a_baseline_exists(tmp_path):
    live, branch = _seeded_pair(tmp_path)
    live.set_generation_starred("lib1", True)
    branch.set_generation_starred("lib1", True)
    _adopt(live, tmp_path)                         # the baseline: starred in both

    branch.set_generation_starred("lib1", False)   # taken back in the preview
    assert _adopt(live, tmp_path) == 1
    assert live.get_generation("lib1")["starred"] == 0


def test_a_folder_bookmark_dropped_in_a_preview_crosses_over_too(tmp_path):
    live, branch = _seeded_pair(tmp_path)
    branch.set_folder_starred("sdxl_t2i/model-a", True)
    _adopt(live, tmp_path)

    branch.delete_folder_meta("sdxl_t2i/model-a")
    assert _adopt(live, tmp_path) == 1
    assert "sdxl_t2i/model-a" not in live.folder_meta_map()


def test_a_star_on_a_generation_the_branch_made_needs_no_second_pass(tmp_path):
    # It rides home as one column of the adopted row; the bookmark pass must not
    # count it again.
    from origenerator.branch_session import adopt_branch_rows
    from origenerator.db import Database
    live = _live_db(tmp_path)
    branch_path = _branch_db_with(
        tmp_path, "wt-a", [{"prompt_id": "b7", "filename": "fox7.png"}])
    Database(branch_path).set_generation_starred("b7", True)
    out = _output_file(tmp_path, "fox7.png")

    assert adopt_branch_rows(live, tmp_path / "worktrees", out, tmp_path / "thumbs") == 1
    assert live.get_generation("b7")["starred"] == 1
    assert _adopt(live, tmp_path) == 0


def test_bookmark_adoption_skips_a_database_predating_stars(tmp_path):
    """An old worktree is passed over whole rather than read in part — recording
    a partial reading as the baseline would make its untouched bookmarks look
    like deletions at the next launch. The worktrees beside it still come home."""
    import sqlite3
    live, fresh = _seeded_pair(tmp_path, worktree="wt-new")
    fresh.set_generation_starred("lib1", True)
    old = tmp_path / "worktrees" / "wt-old" / "state" / "origenerator.db"
    old.parent.mkdir(parents=True)
    with sqlite3.connect(old) as conn:
        conn.execute("CREATE TABLE generations (prompt_id TEXT)")
        conn.execute("INSERT INTO generations VALUES ('lib1')")

    assert _adopt(live, tmp_path) == 1
    assert live.get_generation("lib1")["starred"] == 1


def test_bookmark_adoption_ignores_a_star_on_something_not_here(tmp_path):
    live, branch = _seeded_pair(tmp_path)
    _completed_row(branch, "only-there", "gone.png")
    branch.set_generation_starred("only-there", True)

    assert _adopt(live, tmp_path) == 0
    assert live.get_generation("only-there") is None


# --- a worktree's database is read, and only read ------------------------------


def test_nothing_here_carries_sql_over_the_apps_own_tables():
    """The column vocabulary of `generations`, `requests` and `folder_meta` used
    to live in two modules: db.py, which owns those tables, and this one, whose
    four readers restated them in raw SELECTs — including a hand-maintained copy
    of `folder_meta_full`'s five columns, and a `SELECT *` unpacked straight into
    `record_request(**row)`, an implicit contract between two files that a launch
    would have discovered as a TypeError.

    Held at zero. What is left is the online backup that seeds a worktree, which
    is a whole-file operation no query can express, and it is counted below.
    """
    sql = re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM)\b")

    statements = [node.value for node in ast.walk(_branch_session_module())
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and sql.search(node.value)]

    assert statements == []


def test_the_one_raw_connection_left_is_the_seeds_online_backup():
    """Two: the read-only source and the destination it is copied into. Every
    other database this module touches, it reaches through a store."""
    connections = [node for node in ast.walk(_branch_session_module())
                   if isinstance(node, ast.Call)
                   and ast.unparse(node.func) == "sqlite3.connect"]

    assert len(connections) == 2


def _branch_session_module() -> ast.Module:
    """The module as a syntax tree: what it says, not how its lines are wrapped."""
    return ast.parse((_REPO_ROOT / "origenerator" / "branch_session.py").read_text(
        encoding="utf-8"))


def _a_worktree_with_something_to_adopt(tmp_path):
    """A worktree database holding one generated row, starred, and a bookmark."""
    branch_db = Database(tmp_path / "worktrees" / "example-branch" / "state"
                         / "origenerator.db")
    branch_db.insert_generation(
        prompt_id="gen-alpha", workflow_name="sdxl_t2i", workflow_version="v1",
        params_json="{}", workflow_json="{}",
    )
    branch_db.set_generation_starred("gen-alpha", True)
    branch_db.rename_folder("folder/alpha", "Scene One")
    return branch_db


def test_a_worktree_database_is_only_ever_opened_read_only(tmp_path, monkeypatch):
    """The promise this module's docstrings make -- a branch is unfinished code,
    and the live session's library is not its to corrupt -- read the other way
    round: nor is the worktree's copy the live app's to write. Every connection
    made to one names `?mode=ro`, so sqlite refuses the write rather than the
    reader having to remember not to make one."""
    live = Database(tmp_path / "live" / "origenerator.db")
    _a_worktree_with_something_to_adopt(tmp_path)
    opened = []
    connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda target, *a, **k: (
        opened.append(str(target)), connect(target, *a, **k))[1])

    adopt_branch_rows(live, tmp_path / "worktrees",
                      tmp_path / "output", tmp_path / "thumbs")
    adopt_branch_curation(live, tmp_path / "worktrees")

    worktree_opens = [target for target in opened if "example-branch" in target]
    assert worktree_opens
    assert all("mode=ro" in target for target in worktree_opens), worktree_opens


def test_adopting_from_a_worktree_leaves_its_database_byte_for_byte(tmp_path):
    """The same promise, read off the file afterwards."""
    live = Database(tmp_path / "live" / "origenerator.db")
    branch_db = _a_worktree_with_something_to_adopt(tmp_path)
    before = branch_db.path.read_bytes()

    adopt_branch_rows(live, tmp_path / "worktrees",
                      tmp_path / "output", tmp_path / "thumbs")
    adopt_branch_curation(live, tmp_path / "worktrees")

    assert branch_db.path.read_bytes() == before
    assert not list(branch_db.path.parent.glob("*.db-*"))  # no journal, no wal
