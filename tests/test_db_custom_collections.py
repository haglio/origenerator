from __future__ import annotations

from origenerator.db import Database


def test_dropping_a_folder_already_gathered_keeps_its_place_and_adds_no_second_copy(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Favorites")
    db.add_folders_to_custom_collection(folder_id, [("a", "settings", "p1"), ("b", "settings", "p2")])

    db.add_folders_to_custom_collection(folder_id, [("a", "settings", "p9")])

    (record,) = db.list_custom_collections()
    assert record["folders"] == ["a", "b"]


def test_dropping_a_folder_already_gathered_refreshes_its_identity(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Favorites")
    db.add_folders_to_custom_collection(folder_id, [("a", "settings", "p1")])

    db.add_folders_to_custom_collection(folder_id, [("a", "model", "p9")])

    (gathered,) = db.folders_in_custom_collections()
    assert (gathered["level"], gathered["ref_prompt_id"]) == ("model", "p9")


def test_a_collection_is_recreated_at_the_id_it_had(tmp_path):
    db = Database(tmp_path / "t.db")
    assert db.create_custom_collection("Favorites", folder_id=7) == 7
