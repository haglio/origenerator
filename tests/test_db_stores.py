"""Each table's queries, reached without the other five.

`Database` was one 626-line class over six unrelated tables, so a unit that
touches one of them — recovery reads only `deletions`, reconcile only
`folder_meta` and `custom_folder_members` — had to be handed the whole surface,
and could be given no narrow fake. The queries live one table to a module now,
and these are the tests that a store is a whole object on its own: built
straight off the file, with nothing else constructed.

What each store *does* is covered where it always was, in tests/test_db.py,
through the facade every call site still uses. This file covers the seam.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import pytest

from origenerator.db import Database
from origenerator.db_connection import SqliteFile
from origenerator.db_deletions import DeletionStore


@pytest.fixture
def file(tmp_path) -> SqliteFile:
    """The database file, made once — a store queries, it does not create."""
    path = tmp_path / "origenerator.db"
    Database(path)
    return SqliteFile(path)


def _a_row(prompt_id="gen-alpha"):
    return {"prompt_id": prompt_id, "workflow_name": "sdxl_t2i",
            "output_files": "alpha_00001_.png"}


class TestDeletionStore:
    """recovery.py and gallery_actions.py are its only readers, and neither has
    any business with `generations` or the custom folders."""

    def test_it_works_off_the_file_with_no_database_object_in_sight(self, file):
        deletions = DeletionStore(file)

        deletions.record_deletion("gen-alpha", _a_row(), {"trash": "batch-one"})

        assert deletions.get_deletion("gen-alpha")["row"] == _a_row()

    def test_the_facade_and_the_store_are_looking_at_the_same_rows(self, file):
        db = Database(file.path)
        DeletionStore(file).record_deletion("gen-beta", _a_row("gen-beta"), {})

        assert [held["prompt_id"] for held in db.list_deletions()] == ["gen-beta"]
        assert db.deletions.get_deletion("gen-beta") is not None
