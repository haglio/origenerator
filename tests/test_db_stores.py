"""Each table's queries, reached without the other five.

`Database` was one 626-line class over six unrelated tables, so a unit that
touches one of them — recovery reads only `deletions`, reconcile only
`folder_meta` and `custom_folder_members`, branch_session only
`branch_curation` — had to be handed the whole surface, and could be given no
narrow fake. The queries live one table to a module now, and these are the tests
that a store is a whole object on its own, and that the facade over them is
exactly a facade.

What each store *does* is covered where it always was, in tests/test_db.py,
through the facade every call site still uses. This file covers the seam.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import ast
import inspect
from pathlib import Path

import pytest

import origenerator.db_generations
from origenerator.db import Database
from origenerator.db_branch_curation import BranchCurationStore
from origenerator.db_connection import SqliteFile, Store
from origenerator.db_custom_folders import CustomFolderStore
from origenerator.db_deletions import DeletionStore
from origenerator.db_folder_meta import FolderMetaStore
from origenerator.db_generations import GenerationStore
from origenerator.db_requests import RequestStore
from origenerator.db_schema import GENERATION_COLUMNS

# The attribute each store hangs off `Database` under, and a read that proves it
# is talking to its own table.
STORES = {
    "generations": (GenerationStore, lambda s: s.list_generations()),
    "deletions": (DeletionStore, lambda s: s.list_deletions()),
    "requests": (RequestStore, lambda s: s.list_requests()),
    "folder_meta": (FolderMetaStore, lambda s: s.folder_meta_full()),
    "custom_folders": (CustomFolderStore, lambda s: s.list_custom_folders()),
    "branch_curation": (
        BranchCurationStore, lambda s: s.branch_curation_state("worktree-alpha")),
}


@pytest.fixture
def file(tmp_path) -> SqliteFile:
    """The database file, made once — a store queries, it does not create."""
    path = tmp_path / "origenerator.db"
    Database(path)
    return SqliteFile(path)


def _public_methods(cls) -> set[str]:
    """What the class itself defines, not what it inherits."""
    return {name for name, value in vars(cls).items()
            if inspect.isfunction(value) and not name.startswith("_")}


@pytest.mark.parametrize("attribute", sorted(STORES))
def test_a_store_works_off_the_file_with_no_database_object_in_sight(file, attribute):
    store_class, read = STORES[attribute]

    assert read(store_class(file)) in ([], None)


@pytest.mark.parametrize("attribute", sorted(STORES))
def test_the_facade_holds_one_of_each(file, attribute):
    store_class, _ = STORES[attribute]

    assert isinstance(getattr(Database(file.path), attribute), store_class)


def test_the_facade_forwards_exactly_what_the_stores_offer():
    """Held as an equality, and it is the gate on the whole split. Below it, a
    query moved out and its name went with it — breaking the several hundred
    call sites the split promised not to touch. Above it, a method was written
    on the facade rather than on the table it queries, which is how the
    626-line class happened in the first place."""
    offered = set().union(*(_public_methods(store) for store, _ in STORES.values()))

    assert _public_methods(Database) == offered


def test_every_store_is_one(file):
    """A store binds the file's `connect` and nothing else. One that reached for
    a second table's store, or kept its own connection policy, would make the
    'hand a unit the store it needs' above a promise rather than a fact."""
    for attribute, (store_class, _) in STORES.items():
        store = store_class(file)

        assert isinstance(store, Store)
        assert set(vars(store)) == {"_connect"}, attribute


class TestDeletionStore:
    """recovery.py and gallery_actions.py are its only readers, and neither has
    any business with `generations` or the custom folders."""

    def test_what_it_records_it_can_read_back(self, file):
        row = {"prompt_id": "gen-alpha", "workflow_name": "sdxl_t2i",
               "output_files": "alpha_00001_.png"}
        deletions = DeletionStore(file)

        deletions.record_deletion("gen-alpha", row, {"trash": "batch-one"})

        assert deletions.get_deletion("gen-alpha")["row"] == row

    def test_the_facade_and_the_store_are_looking_at_the_same_rows(self, file):
        db = Database(file.path)
        DeletionStore(file).record_deletion("gen-beta", {"prompt_id": "gen-beta"}, {})

        assert [held["prompt_id"] for held in db.list_deletions()] == ["gen-beta"]
        assert db.deletions.get_deletion("gen-beta") is not None


def test_every_column_written_by_name_is_a_literal_column_of_the_table():
    """`GenerationStore._set` and `._stamp` interpolate a column name straight
    into their statement, which is safe exactly as long as every one of them is
    a literal written in that file and a column that exists. Read off the syntax
    tree rather than left to care: a name reaching either of them from a
    caller's string, or a column that has been renamed out of the schema, fails
    here — before the statement, rather than as an OperationalError mid-write.
    """
    source = (Path(origenerator.db_generations.__file__)).read_text(encoding="utf-8")
    written = [
        node.args[1]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("_set", "_stamp") and len(node.args) >= 2
    ]

    assert written, "the walk found no call at all, so this checks nothing"
    for column in written:
        assert isinstance(column, ast.Constant), ast.unparse(column)
        assert column.value in GENERATION_COLUMNS, column.value
