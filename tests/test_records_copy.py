from __future__ import annotations

import json
import sqlite3

from origenerator.records_copy import copy_the_records


def _a_database(path, title="alpha one"):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("create table if not exists made (name text)")
    db.execute("insert into made values (?)", (title,))
    db.commit()
    db.close()
    return path


def _names_in(path) -> list[str]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [row[0] for row in db.execute("select name from made")]
    finally:
        db.close()


def test_the_records_are_copied_where_the_backup_will_find_them(tmp_path):
    records = _a_database(tmp_path / "state" / "origenerator.db")
    overlay = tmp_path / "content.local.json"
    overlay.write_text(json.dumps({"library_root": "D:/example"}), encoding="utf-8")
    kept = tmp_path / "library" / "origenerator_records"

    copied = copy_the_records(records, overlay, kept)

    assert sorted(path.name for path in copied) == ["content.local.json", "origenerator.db"]
    assert _names_in(kept / "origenerator.db") == ["alpha one"]
    assert json.loads((kept / "content.local.json").read_text(encoding="utf-8")) == {
        "library_root": "D:/example"}


def test_a_copy_as_new_as_the_records_is_left_where_it_is(tmp_path):
    records = _a_database(tmp_path / "state" / "origenerator.db")
    overlay = tmp_path / "content.local.json"
    overlay.write_text("{}", encoding="utf-8")
    kept = tmp_path / "kept"
    copy_the_records(records, overlay, kept)
    written_at = (kept / "origenerator.db").stat().st_mtime_ns

    assert copy_the_records(records, overlay, kept) == []
    assert (kept / "origenerator.db").stat().st_mtime_ns == written_at


def test_records_written_since_the_copy_are_copied_again(tmp_path):
    records = _a_database(tmp_path / "state" / "origenerator.db")
    overlay = tmp_path / "content.local.json"
    overlay.write_text("{}", encoding="utf-8")
    kept = tmp_path / "kept"
    copy_the_records(records, overlay, kept)
    _a_database(records, "beta two")

    assert [path.name for path in copy_the_records(records, overlay, kept)] == ["origenerator.db"]
    assert _names_in(kept / "origenerator.db") == ["alpha one", "beta two"]


def test_a_copy_taken_while_the_app_is_mid_write_opens_as_a_database(tmp_path):
    records = _a_database(tmp_path / "state" / "origenerator.db")
    overlay = tmp_path / "content.local.json"
    overlay.write_text("{}", encoding="utf-8")
    kept = tmp_path / "kept"
    live = sqlite3.connect(records)
    try:
        live.execute("insert into made values ('gamma three')")

        copy_the_records(records, overlay, kept)
    finally:
        live.rollback()
        live.close()

    assert _names_in(kept / "origenerator.db") == ["alpha one"]
