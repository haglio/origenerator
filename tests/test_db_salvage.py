"""A database that has been corrupted underneath the app still opens.

SQLite guarantees its own writes, but nothing protects the file from a write
that arrives from outside it. One did: a stray 922-byte block of ffmpeg's own
stderr chatter landed in the middle of the database file, and from then on every
full-table read raised ``database disk image is malformed`` -- which killed the
running app from its poll timer and then killed every relaunch while the gallery
was still being built. These tests reproduce that shape of damage and pin the
behavior that answers it: open what is readable, keep the damaged file, carry on.
"""

import shutil
import sqlite3

from origenerator.db import Database

PAGE = 4096
# Big enough that each generation gets a leaf page to itself, as the real rows
# (full workflow graphs) do -- so a clobbered page costs exactly one row.
FILLER = "x" * 2500


def _fill(path, count):
    db = Database(path)
    for i in range(count):
        db.insert_generation(
            prompt_id=f"job-{i}",
            workflow_name="sdxl_t2i",
            workflow_version="v002",
            positive_prompt=f"marker-{i}-{FILLER}",
            params_json="{}",
            workflow_json="{}",
        )


def _journal_mode(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def _set_journal_mode(path, mode):
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA journal_mode = {mode}")
    finally:
        conn.close()


def _leave_a_hot_journal(path, rows):
    """Fill ``path``, leaving the write-ahead log a crash mid-write leaves.

    Copied out from under a connection that is still holding it open, which is
    the only way to keep one: closing the last connection folds the log back
    into the database and deletes it.
    """
    staged = path.with_name("staged.db")
    _fill(staged, rows)
    _set_journal_mode(staged, "wal")
    holding = sqlite3.connect(staged)
    holding.execute(
        "INSERT INTO generations (prompt_id, workflow_name, workflow_version,"
        " params_json, workflow_json) VALUES ('job-in-the-log', 'sdxl_t2i', 'v002', '{}', '{}')"
    )
    holding.commit()
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(f"{staged}{suffix}", f"{path}{suffix}")
    holding.close()


def _stray_write_over(path, marker):
    """Land a stray write on the page holding ``marker``, as the real one did.

    Overwriting the page header is what the real stray write did to a page whose
    row occupied only the tail: the row's bytes survived, but the header saying
    where they start did not, so the page is unreachable through the b-tree.
    """
    data = bytearray(path.read_bytes())
    page = data.index(marker.encode()) // PAGE
    data[page * PAGE:page * PAGE + 10] = b"Input #0, "
    path.write_bytes(bytes(data))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]
    except sqlite3.DatabaseError:
        pass  # too malformed to even check -- the damage landed
    finally:
        conn.close()


def test_a_malformed_database_opens_with_every_row_still_readable(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 12)
    _stray_write_over(path, "marker-5-")

    rows = Database(path).list_generations()

    assert [r["prompt_id"] for r in rows] == [
        f"job-{i}" for i in reversed(range(12)) if i != 5
    ]


def test_the_damaged_file_is_kept_beside_the_rebuilt_one(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 12)
    _stray_write_over(path, "marker-5-")
    damaged = path.read_bytes()

    Database(path)

    assert (tmp_path / "origenerator.db.corrupt").read_bytes() == damaged


def test_damage_to_the_newest_rows_does_not_cost_the_older_ones(tmp_path):
    # The newest rows sit on the pages SQLite walks to answer max(rowid), so
    # damage there hides how far the table counts -- and salvaging nothing would
    # empty a gallery that was almost entirely readable.
    path = tmp_path / "origenerator.db"
    _fill(path, 12)
    _stray_write_over(path, "marker-11-")

    rows = Database(path).list_generations()

    assert [r["prompt_id"] for r in rows] == [f"job-{i}" for i in reversed(range(11))]


def test_the_rebuilt_database_keeps_the_journal_mode_it_replaced(tmp_path):
    # The live database runs in WAL, where a reader never waits on the writer --
    # which the gallery's poll timer leans on. Coming back from a salvage in
    # rollback-journal mode would be a quieter break than the one being fixed.
    path = tmp_path / "origenerator.db"
    _fill(path, 6)
    _set_journal_mode(path, "wal")
    _stray_write_over(path, "marker-3-")

    Database(path)

    assert _journal_mode(path) == "wal"


def test_the_damaged_files_write_ahead_log_goes_aside_with_it(tmp_path):
    # A write-ahead log names no database of its own -- it belongs to whatever
    # file sits beside it. One left behind by the crash would be replayed into
    # the rebuilt database that inherits the name, whose pages it knows nothing
    # about.
    path = tmp_path / "origenerator.db"
    _leave_a_hot_journal(path, rows=6)
    _stray_write_over(path, "marker-3-")

    Database(path)

    assert (tmp_path / "origenerator.db.corrupt-wal").exists()
    assert not (tmp_path / "origenerator.db-wal").exists()


def test_a_healthy_database_is_opened_untouched(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 3)

    rows = Database(path).list_generations()

    assert [r["prompt_id"] for r in rows] == ["job-2", "job-1", "job-0"]
    assert [p.name for p in tmp_path.iterdir()] == ["origenerator.db"]
