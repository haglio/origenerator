from __future__ import annotations

import ast
import inspect
import sqlite3
from pathlib import Path

import pytest

import origenerator.db_generations
from origenerator.db import Database
from origenerator.db_combine_video_uses import CombineVideoUseStore
from origenerator.db_connection import SqliteFile, Store
from origenerator.db_custom_collections import CustomCollectionStore
from origenerator.db_folder_meta import FolderMetaStore
from origenerator.db_generations import GenerationStore
from origenerator.db_item_numbers import ItemNumberStore
from origenerator.db_requests import RequestStore
from origenerator.db_schema import GENERATION_COLUMNS
from origenerator.db_seed_uses import SeedUseStore
from origenerator.db_trash import TrashStore

STORES = {
    "generations": (GenerationStore, lambda s: s.list_generations()),
    "deletions": (TrashStore, lambda s: s.list_trashed()),
    "requests": (RequestStore, lambda s: s.list_requests()),
    "folder_meta": (FolderMetaStore, lambda s: s.folder_meta_full()),
    "custom_collections": (CustomCollectionStore, lambda s: s.list_custom_collections()),
    "seed_uses": (SeedUseStore, lambda s: s.list_seed_uses()),
    "combine_video_uses": (CombineVideoUseStore, lambda s: s.list_combine_video_uses()),
    "item_numbers": (ItemNumberStore, lambda s: s.list_item_numbers()),
}


ASKED_OF_THE_REQUESTS_STORE = {"record_turns", "exchange_of", "distinct_positive_prompts",
                               "started_on", "mark_made",
                               "items_asked_into"}


@pytest.fixture
def file(tmp_path) -> SqliteFile:
    path = tmp_path / "origenerator.db"
    Database(path)
    return SqliteFile(path)


def _public_methods(cls) -> set[str]:
    return {name for name, value in vars(cls).items()
            if inspect.isfunction(value) and not name.startswith("_")}


@pytest.mark.parametrize("attribute", sorted(STORES))
def test_a_store_works_off_the_file_with_no_database_object_in_sight(file, attribute):
    store_class, read = STORES[attribute]

    assert not read(store_class(file))


@pytest.mark.parametrize("attribute", sorted(STORES))
def test_the_facade_holds_one_of_each(file, attribute):
    store_class, _ = STORES[attribute]

    assert isinstance(getattr(Database(file.path), attribute), store_class)


def test_the_facade_forwards_exactly_what_the_stores_offer():
    offered = set().union(*(_public_methods(store) for store, _ in STORES.values()))

    assert _public_methods(Database) == offered - ASKED_OF_THE_REQUESTS_STORE, (
        "fewer, and a query's name went with it when it moved out, breaking its callers; "
        "more, and a method was written on the facade and not on the table it queries, "
        "which is how the one big class grew")


def test_every_store_is_one(file):
    for attribute, (store_class, _) in STORES.items():
        store = store_class(file)

        assert isinstance(store, Store)
        assert store._connect == file.connect, attribute
        assert not [value for value in vars(store).values()
                    if isinstance(value, (Store, Database, sqlite3.Connection))], attribute


class TestTrashStore:
    def test_what_it_records_it_can_read_back(self, file):
        row = {"prompt_id": "gen-alpha", "workflow_name": "sdxl_t2i",
               "output_files": "alpha_00001_.png"}
        trash = TrashStore(file)

        trash.record_trashed("gen-alpha", row, {"trash": "batch-one"})

        assert trash.get_trashed("gen-alpha")["row"] == row

    def test_the_facade_and_the_store_are_looking_at_the_same_rows(self, file):
        db = Database(file.path)
        TrashStore(file).record_trashed("gen-beta", {"prompt_id": "gen-beta"}, {})

        assert [held["prompt_id"] for held in db.list_trashed()] == ["gen-beta"]
        assert db.deletions.get_trashed("gen-beta") is not None


class TestItemNumberStore:
    def test_what_it_records_it_can_read_back(self, file):
        numbers = ItemNumberStore(file)

        numbers.record_item_numbers({"gen-alpha": ("image/sdxl_t2i/0123456789ab", 3)})

        assert numbers.list_item_numbers() == {"gen-alpha": ("image/sdxl_t2i/0123456789ab", 3)}

    def test_an_item_recorded_again_keeps_only_its_newest_number(self, file):
        numbers = ItemNumberStore(file)
        numbers.record_item_numbers({"gen-alpha": ("image/sdxl_t2i/0123456789ab", 3)})

        numbers.record_item_numbers({"gen-alpha": ("image/sdxl_t2i/ba9876543210", 3)})

        assert numbers.list_item_numbers() == {"gen-alpha": ("image/sdxl_t2i/ba9876543210", 3)}


COLUMN_ARGUMENTS = {"_set": (1,), "_stamp": (1,), "_record_send": (1, 2)}


def test_every_column_written_by_name_is_a_literal_column_of_the_table():
    source = (Path(origenerator.db_generations.__file__)).read_text(encoding="utf-8")
    written = [
        node.args[position]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        for position in COLUMN_ARGUMENTS.get(node.func.attr, ())
        if len(node.args) > position
    ]

    assert written, "the walk found no call at all, so this checks nothing"
    for column in written:
        assert isinstance(column, ast.Constant), (
            f"{ast.unparse(column)}: a column's name goes straight into the statement, "
            "so it must be a literal written in that file, never a caller's string")
        assert column.value in GENERATION_COLUMNS, column.value
