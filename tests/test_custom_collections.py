"""Custom collections: the pure grouping model, and the storage under it."""
from __future__ import annotations

import json

import pytest

from origenerator import gallery
from origenerator.db import Database
from origenerator.gallery.sides import PORTRAIT
from origenerator.gallery_actions import GalleryActions
from origenerator.output_places import OutputPlaces
from origenerator.trash import Trash


def _row(prompt_id, prompt, steps=30, seed=1):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "workflow_version": "v1",
        "status": "completed",
        "source": "generated",
        "params_json": json.dumps(
            {"positive_prompt": prompt, "steps": steps, "seed": seed}
        ),
        "output_files": json.dumps([{"filename": f"sdxl_t2i_{prompt_id}.png",
                                     "subfolder": ""}]),
    }


def _tree(rows):
    return gallery.build_gallery_tree(rows, {})


def _lora_folder(tree):
    """The "(no LoRA)" folder these rows all land under: Images -> workflow ->
    model -> LoRA, whose children are the settings leaves."""
    (images,) = tree
    (workflow,) = gallery.child_groups(images)
    return gallery.child_groups(gallery.child_groups(workflow)[0])[0]


# --- keys --------------------------------------------------------------------

def test_a_custom_folder_key_round_trips_to_its_id():
    key = gallery.custom_collection_key(7)
    assert gallery.custom_folder_id(key) == 7


@pytest.mark.parametrize("key", ["image", "image/sdxl_t2i", "__starred__", "__recents__"])
def test_a_derived_or_collection_key_is_not_a_custom_folder(key):
    assert gallery.custom_folder_id(key) is None


def test_the_live_selection_names_no_saved_folder():
    # It renders like a saved folder while carrying nothing to save it under.
    assert gallery.custom_folder_id(gallery.SELECTION_KEY) is None


# --- resolving a saved folder against the live tree --------------------------

def test_a_custom_folder_resolves_its_folders_out_of_the_tree():
    rows = [_row("i1", "a cat"), _row("i2", "a dog")]
    tree = _tree(rows)
    cat, dog = [g.key for g in gallery.child_groups(_lora_folder(tree))]

    (folder,) = gallery.build_custom_collections(
        tree, [{"id": 3, "name": "Favorites", "folders": [cat, dog], "items": []}]
    )

    assert folder.key == gallery.custom_collection_key(3)
    assert folder.label == "Favorites"
    assert [g.key for g in gallery.child_groups(folder)] == [cat, dog]
    assert {r["prompt_id"] for r in gallery.rows_under(folder)} == {"i1", "i2"}


def test_a_gathered_folder_that_is_gone_is_skipped_not_dropped():
    # The folder may come back (an undone delete, a reconcile) — so the grouping
    # renders without it rather than forgetting it was ever gathered.
    rows = [_row("i1", "a cat")]
    tree = _tree(rows)
    record = {"id": 1, "name": "Mixed",
              "folders": ["image/sdxl_t2i/deadbeef", "image/sdxl_t2i"], "items": []}

    (folder,) = gallery.build_custom_collections(tree, [record])

    assert [g.key for g in gallery.child_groups(folder)] == ["image/sdxl_t2i"]
    # untouched
    assert record["folders"] == ["image/sdxl_t2i/deadbeef", "image/sdxl_t2i"]


def test_an_empty_custom_folder_still_appears():
    # A folder you have made and named but not yet filled is exactly where you
    # are about to drop something.
    (folder,) = gallery.build_custom_collections(
        _tree([_row("i1", "a cat")]),
        [{"id": 1, "name": "Later", "folders": [], "items": []}]
    )
    assert gallery.child_groups(folder) == []
    assert gallery.rows_under(folder) == []


def test_a_custom_folder_resolves_the_items_it_holds_out_of_the_tree():
    tree = _tree([_row("i1", "a cat"), _row("i2", "a dog"), _row("i3", "a fish")])

    (folder,) = gallery.build_custom_collections(
        tree, [{"id": 3, "name": "Mine", "folders": [], "items": ["i3", "gone", "i1"]}]
    )

    assert [r["prompt_id"] for r in gallery.rows_under(folder)] == ["i3", "i1"]


def test_a_custom_folders_own_items_lead_and_one_inside_a_gathered_folder_counts_once():
    # The slideshow plays these in the order the tiles are drawn: the items
    # first, then each gathered folder's.
    rows = [_row("i1", "a cat"), _row("i2", "a dog")]
    tree = _tree(rows)
    cat, dog = gallery.child_groups(_lora_folder(tree))

    (folder,) = gallery.build_custom_collections(
        tree, [{"id": 1, "name": "Mine", "folders": [dog.key, cat.key], "items": ["i1"]}]
    )

    assert [r["prompt_id"] for r in gallery.rows_under(folder)] == ["i1", "i2"]


def test_a_custom_folder_inside_another_brings_what_it_holds():
    tree = _tree([_row("i1", "a cat"), _row("i2", "a dog")])
    cat, dog = gallery.child_groups(_lora_folder(tree))
    inner = gallery.custom_collection_key(2)

    outer_folder, _inner_folder = gallery.build_custom_collections(tree, [
        {"id": 1, "name": "Outer", "folders": [cat.key, inner], "items": []},
        {"id": 2, "name": "Inner", "folders": [dog.key], "items": []},
    ])

    assert [g.key for g in gallery.child_groups(outer_folder)] == [cat.key, inner]
    assert {r["prompt_id"] for r in gallery.rows_under(outer_folder)} == {"i1", "i2"}


def test_two_custom_folders_saved_inside_each_other_resolve_without_looping():
    # An undo and a redo can leave each holding the other; the later link is left out.
    tree = _tree([_row("i1", "a cat")])
    a, b = gallery.custom_collection_key(1), gallery.custom_collection_key(2)

    first, second = gallery.build_custom_collections(tree, [
        {"id": 1, "name": "A", "folders": [b], "items": ["i1"]},
        {"id": 2, "name": "B", "folders": [a], "items": []},
    ])

    assert [g.key for g in gallery.child_groups(first)] == [b]
    assert gallery.child_groups(second) == []
    assert [r["prompt_id"] for r in gallery.rows_under(first)] == ["i1"]


def test_gathering_a_folder_and_its_parent_counts_each_item_once():
    # Otherwise the slideshow would play the overlap twice and the tile would
    # claim more items than the folder holds.
    rows = [_row("i1", "a cat"), _row("i2", "a dog")]
    tree = _tree(rows)
    lora = _lora_folder(tree)
    leaf = gallery.child_groups(lora)[0]

    (folder,) = gallery.build_custom_collections(
        tree, [{"id": 1, "name": "Overlapping", "folders": [lora.key, leaf.key],
                "items": []}]
    )

    assert len(gallery.rows_under(folder)) == 2


def test_a_custom_folder_wears_no_folder_level_but_names_its_tier():
    (folder,) = gallery.build_custom_collections(
        _tree([_row("i1", "a cat")]), [{"id": 1, "name": "Mine", "folders": [], "items": []}]
    )
    assert gallery.folder_level(folder) is None   # no TOC initial: it is no tier
    assert gallery.group_level(folder) == "custom"


# --- storage -----------------------------------------------------------------

def _db_with_folder(tmp_path, name="Favorites", folders=(("image", "media", "i1"),)):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection(name)
    db.add_folders_to_custom_collection(folder_id, list(folders))
    return db, folder_id


def test_a_saved_folder_keeps_the_side_it_was_made_on(tmp_path):
    db = Database(tmp_path / "t.db")

    folder_id = db.create_custom_collection("Mine", side=PORTRAIT)

    assert db.list_custom_collections() == [
        {"id": folder_id, "name": "Mine", "side": PORTRAIT, "folders": [], "items": []}]


def test_a_saved_folder_lists_its_folders_in_the_order_they_were_added(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Favorites")
    db.add_folders_to_custom_collection(folder_id, [("b", "settings", "p2")])
    db.add_folders_to_custom_collection(folder_id, [("a", "settings", "p1"),
                                                ("c", "settings", "p3")])

    (record,) = db.list_custom_collections()
    assert record["folders"] == ["b", "a", "c"]


def test_a_saved_folder_lists_the_items_it_holds_in_the_order_they_were_added(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Mine")

    db.add_items_to_custom_collection(folder_id, ["p2"])
    db.add_items_to_custom_collection(folder_id, ["p1", "p3"])

    (record,) = db.list_custom_collections()
    assert record["items"] == ["p2", "p1", "p3"]


def test_re_adding_an_item_keeps_its_place_rather_than_duplicating_it(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Mine")
    db.add_items_to_custom_collection(folder_id, ["p1", "p2"])

    db.add_items_to_custom_collection(folder_id, ["p1"])

    (record,) = db.list_custom_collections()
    assert record["items"] == ["p1", "p2"]


def test_removing_items_from_a_folder_leaves_the_rest_in_order(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Mine")
    db.add_items_to_custom_collection(folder_id, ["p1", "p2", "p3", "p4"])

    db.remove_items_from_custom_collection(folder_id, ["p3", "p1"])

    (record,) = db.list_custom_collections()
    assert record["items"] == ["p2", "p4"]


def test_re_adding_a_folder_keeps_its_place_rather_than_duplicating_it(tmp_path):
    db, folder_id = _db_with_folder(tmp_path, folders=[("a", "settings", "p1"),
                                                       ("b", "settings", "p2")])

    db.add_folders_to_custom_collection(folder_id, [("a", "settings", "p9")])

    (record,) = db.list_custom_collections()
    assert record["folders"] == ["a", "b"]
    identity = {m["folder_key"]: m["ref_prompt_id"] for m in db.folders_in_custom_collections()}
    assert identity["a"] == "p9"  # the identity refreshes even though the order holds


def test_removing_a_custom_folder_takes_what_it_gathered_with_it(tmp_path):
    db, folder_id = _db_with_folder(tmp_path)
    db.add_items_to_custom_collection(folder_id, ["p1"])

    db.delete_custom_collection(folder_id)

    assert db.list_custom_collections() == []
    assert db.folders_in_custom_collections() == []
    db.create_custom_collection("Mine", folder_id)  # what an undone removal does
    (record,) = db.list_custom_collections()
    assert record["items"] == []


def test_repointing_a_gathered_folder_keeps_its_place(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Favorites")
    db.add_folders_to_custom_collection(folder_id, [("a", "settings", "p1"),
                                                ("old", "settings", "p2"),
                                                ("c", "settings", "p3")])

    db.repoint_folder_in_custom_collection(folder_id, "old", "new",
                                       level="settings", ref_prompt_id="p2")

    (record,) = db.list_custom_collections()
    assert record["folders"] == ["a", "new", "c"]


def test_repointing_onto_a_folder_it_already_gathers_merges_them(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_collection("Favorites")
    db.add_folders_to_custom_collection(folder_id, [("live", "settings", "p1"),
                                                ("stale", "settings", "p1")])

    db.repoint_folder_in_custom_collection(folder_id, "stale", "live",
                                       level="settings", ref_prompt_id="p1")

    (record,) = db.list_custom_collections()
    assert record["folders"] == ["live"]  # one folder can only be in a grouping once


# --- undo --------------------------------------------------------------------

def _actions(tmp_path):
    db = Database(tmp_path / "t.db")
    return db, GalleryActions(db, OutputPlaces.in_one_folder(tmp_path / "output"), Trash(tmp_path / "trash"))


def test_undoing_a_removal_brings_the_folder_back_whole(tmp_path):
    # At the same id, so a session saved while it was open still finds it.
    db, actions = _actions(tmp_path)
    folder_id = actions.custom_collections.create(
        "Favorites", [("a", "settings", "p1"), ("b", "settings", "p2")], PORTRAIT
    )
    actions.custom_collections.add_to(folder_id, items=["p4", "p3"])

    actions.custom_collections.delete(folder_id)
    assert db.list_custom_collections() == []
    actions.undo()

    assert db.list_custom_collections() == [
        {"id": folder_id, "name": "Favorites", "side": PORTRAIT, "folders": ["a", "b"],
         "items": ["p4", "p3"]}
    ]


def test_undoing_an_add_leaves_the_folders_that_were_already_there(tmp_path):
    db, actions = _actions(tmp_path)
    folder_id = actions.custom_collections.create("Favorites", [("a", "settings", "p1")])

    actions.custom_collections.add_to(folder_id, [("a", "settings", "p1"),
                                              ("b", "settings", "p2")])
    actions.undo()

    (record,) = db.list_custom_collections()
    assert record["folders"] == ["a"]


def test_undoing_an_add_of_items_leaves_the_items_that_were_already_there(tmp_path):
    db, actions = _actions(tmp_path)
    folder_id = actions.custom_collections.create("Mine", [])
    actions.custom_collections.add_to(folder_id, items=["p1"])

    actions.custom_collections.add_to(folder_id, items=["p1", "p2"])
    assert actions.undo_label() == "Add 1 item to “Mine”"
    actions.undo()

    (record,) = db.list_custom_collections()
    assert record["items"] == ["p1"]


def test_undoing_a_removal_of_items_puts_them_back(tmp_path):
    db, actions = _actions(tmp_path)
    folder_id = actions.custom_collections.create("Mine", [])
    actions.custom_collections.add_to(folder_id, items=["p1", "p2"])

    actions.custom_collections.remove_from(folder_id, items=["p2"])
    assert db.list_custom_collections()[0]["items"] == ["p1"]
    actions.undo()

    assert db.list_custom_collections()[0]["items"] == ["p1", "p2"]


def test_redo_of_a_folder_creation_brings_it_back_at_the_same_id(tmp_path):
    # A saved session points at a custom collection by id, so a create that is undone
    # and redone has to resolve to the same key rather than a fresh one.
    db, actions = _actions(tmp_path)
    folder_id = actions.custom_collections.create("Mine", [("image/sdxl_t2i", "model", None)],
                                              PORTRAIT)
    actions.undo()
    assert db.list_custom_collections() == []

    actions.redo()

    ((record,),) = (db.list_custom_collections(),)
    assert record["id"] == folder_id
    assert record["side"] == PORTRAIT
    assert record["name"] == "Mine"
    assert record["folders"] == ["image/sdxl_t2i"]
