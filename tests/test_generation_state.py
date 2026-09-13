"""What a generations row says about itself, held to the bytes already on disk.

Evolver opens this database read-only, and every user's rows were written long
before these names existed, so a name is only right if it stands for the string
that was always stored.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing

from origenerator.db import Database
from origenerator.generation_state import GenerationSource, GenerationStatus, source_of


def _insert(db: Database, prompt_id: str = "a-generation", **fields) -> None:
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v001", params_json="{}", workflow_json="{}",
                         **fields)


def _stored(db: Database, column: str) -> tuple:
    with closing(sqlite3.connect(db.path)) as conn:
        return conn.execute(f"SELECT typeof({column}), {column} FROM generations").fetchone()


def test_the_statuses_are_the_four_strings_rows_have_always_carried():
    assert {status.value for status in GenerationStatus} == {
        "pending", "running", "completed", "error"}


def test_a_new_row_is_pending_because_the_schema_says_so(tmp_path):
    db = Database(tmp_path / "test.db")
    _insert(db)

    assert _stored(db, "status") == ("text", GenerationStatus.PENDING.value)


def test_a_status_goes_to_the_database_as_its_plain_string(tmp_path):
    db = Database(tmp_path / "test.db")
    _insert(db)

    db.update_generation("a-generation", status=GenerationStatus.COMPLETED)

    assert _stored(db, "status") == ("text", "completed")
    assert db.get_generation("a-generation")["status"] == GenerationStatus.COMPLETED


def test_the_sources_are_the_four_strings_rows_have_always_carried():
    assert {source.value for source in GenerationSource} == {
        "generated", "imported", "experiment", "base_render"}


def test_a_row_inserted_without_a_source_is_the_users_own_work(tmp_path):
    db = Database(tmp_path / "test.db")
    _insert(db)

    assert _stored(db, "source") == ("text", GenerationSource.GENERATED.value)


def test_a_source_goes_to_the_database_as_its_plain_string(tmp_path):
    db = Database(tmp_path / "test.db")
    _insert(db, source=GenerationSource.EXPERIMENT)

    assert _stored(db, "source") == ("text", "experiment")


def test_a_row_that_names_no_source_counts_as_the_users_own_work():
    assert source_of({}) == GenerationSource.GENERATED
    assert source_of({"source": None}) == GenerationSource.GENERATED


def test_an_old_rows_source_comes_back_as_stored_even_with_no_name_for_it():
    assert source_of({"source": "stroke_trim"}) == "stroke_trim"
