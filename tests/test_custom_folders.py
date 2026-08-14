"""Custom folders: the pure grouping model, and the storage behind it."""

import json

import pytest

from origenerator import gallery
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
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
    """The "(no LoRA)" folder these rows all land under: media -> workflow ->
    model -> LoRA, whose children are the settings leaves."""
    return gallery.child_groups(gallery.child_groups(gallery.child_groups(tree[0])[0])[0])[0]


# --- keys --------------------------------------------------------------------

def test_a_custom_folder_key_round_trips_to_its_id():
    key = gallery.custom_folder_key(7)
    assert gallery.custom_folder_id(key) == 7
    assert gallery.is_custom_key(key)


@pytest.mark.parametrize("key", ["image", "image/sdxl_t2i", "__starred__", "__recents__"])
def test_a_derived_or_shelf_key_is_not_a_custom_folder(key):
    assert gallery.custom_folder_id(key) is None
    assert not gallery.is_custom_key(key)


def test_the_live_selection_counts_as_custom_but_names_no_saved_folder():
    # It renders like a saved folder while carrying nothing to save it under.
    assert gallery.is_custom_key(gallery.SELECTION_KEY)
    assert gallery.custom_folder_id(gallery.SELECTION_KEY) is None


# --- resolving a saved folder against the live tree --------------------------

def test_a_custom_folder_resolves_its_members_out_of_the_tree():
    rows = [_row("i1", "a cat"), _row("i2", "a dog")]
    tree = _tree(rows)
    cat, dog = [g.key for g in gallery.child_groups(_lora_folder(tree))]

    (folder,) = gallery.build_custom_folders(
        tree, [{"id": 3, "name": "Favorites", "members": [cat, dog]}]
    )

    assert folder.key == gallery.custom_folder_key(3)
    assert folder.label == "Favorites"
    assert [g.key for g in gallery.child_groups(folder)] == [cat, dog]
    assert {r["prompt_id"] for r in gallery.rows_under(folder)} == {"i1", "i2"}


def test_a_member_whose_folder_is_gone_is_skipped_not_dropped():
    # The folder may come back (an undone delete, a reconcile) — so the grouping
    # renders without it rather than forgetting it was ever a member.
    rows = [_row("i1", "a cat")]
    tree = _tree(rows)
    record = {"id": 1, "name": "Mixed", "members": ["image/sdxl_t2i/deadbeef", "image"]}

    (folder,) = gallery.build_custom_folders(tree, [record])

    assert [g.key for g in gallery.child_groups(folder)] == ["image"]
    assert record["members"] == ["image/sdxl_t2i/deadbeef", "image"]  # untouched


def test_an_empty_custom_folder_still_appears():
    # A folder you have made and named but not yet filled is exactly where you
    # are about to drop something.
    (folder,) = gallery.build_custom_folders(
        _tree([_row("i1", "a cat")]), [{"id": 1, "name": "Later", "members": []}]
    )
    assert gallery.child_groups(folder) == []
    assert gallery.rows_under(folder) == []


def test_gathering_a_folder_and_its_parent_counts_each_item_once():
    # Otherwise the slideshow would play the overlap twice and the tile would
    # claim more items than the folder holds.
    rows = [_row("i1", "a cat"), _row("i2", "a dog")]
    tree = _tree(rows)
    lora = _lora_folder(tree)
    leaf = gallery.child_groups(lora)[0]

    (folder,) = gallery.build_custom_folders(
        tree, [{"id": 1, "name": "Overlapping", "members": [lora.key, leaf.key]}]
    )

    assert len(gallery.rows_under(folder)) == 2


def test_a_custom_folder_wears_no_recipe_level_but_names_its_tier():
    (folder,) = gallery.build_custom_folders(
        _tree([_row("i1", "a cat")]), [{"id": 1, "name": "Mine", "members": []}]
    )
    assert gallery.folder_level(folder) is None   # no lettered chip: it is no tier
    assert gallery.group_level(folder) == "custom"


# --- storage -----------------------------------------------------------------

def _db_with_folder(tmp_path, name="Favorites", members=(("image", "media", "i1"),)):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_folder(name)
    db.add_custom_folder_members(folder_id, list(members))
    return db, folder_id


def test_a_saved_folder_lists_its_members_in_the_order_they_were_added(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_folder("Favorites")
    db.add_custom_folder_members(folder_id, [("b", "settings", "p2")])
    db.add_custom_folder_members(folder_id, [("a", "settings", "p1"),
                                             ("c", "settings", "p3")])

    (record,) = db.list_custom_folders()
    assert record == {"id": folder_id, "name": "Favorites", "members": ["b", "a", "c"]}


def test_re_adding_a_member_keeps_its_place_rather_than_duplicating_it(tmp_path):
    db, folder_id = _db_with_folder(tmp_path, members=[("a", "settings", "p1"),
                                                       ("b", "settings", "p2")])

    db.add_custom_folder_members(folder_id, [("a", "settings", "p9")])

    (record,) = db.list_custom_folders()
    assert record["members"] == ["a", "b"]
    identity = {m["folder_key"]: m["ref_prompt_id"] for m in db.custom_folder_members_full()}
    assert identity["a"] == "p9"  # the identity refreshes even though the order holds


def test_removing_a_folder_takes_its_membership_with_it(tmp_path):
    db, folder_id = _db_with_folder(tmp_path)

    db.delete_custom_folder(folder_id)

    assert db.list_custom_folders() == []
    assert db.custom_folder_members_full() == []


def test_repointing_a_member_keeps_its_place_in_the_folder(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_folder("Favorites")
    db.add_custom_folder_members(folder_id, [("a", "settings", "p1"),
                                             ("old", "settings", "p2"),
                                             ("c", "settings", "p3")])

    db.repoint_custom_folder_member(folder_id, "old", "new",
                                    level="settings", ref_prompt_id="p2")

    (record,) = db.list_custom_folders()
    assert record["members"] == ["a", "new", "c"]


def test_repointing_onto_a_member_the_folder_already_holds_merges_them(tmp_path):
    db = Database(tmp_path / "t.db")
    folder_id = db.create_custom_folder("Favorites")
    db.add_custom_folder_members(folder_id, [("live", "settings", "p1"),
                                             ("stale", "settings", "p1")])

    db.repoint_custom_folder_member(folder_id, "stale", "live",
                                    level="settings", ref_prompt_id="p1")

    (record,) = db.list_custom_folders()
    assert record["members"] == ["live"]  # one folder can only be in a grouping once


# --- undo --------------------------------------------------------------------

def _actions(tmp_path):
    db = Database(tmp_path / "t.db")
    return db, GalleryActions(db, tmp_path / "output", Trash(tmp_path / "trash"))


def test_undoing_a_removal_brings_the_folder_back_whole(tmp_path):
    # At the same id, so a session saved while it was open still finds it.
    db, actions = _actions(tmp_path)
    folder_id = actions.create_custom_folder(
        "Favorites", [("a", "settings", "p1"), ("b", "settings", "p2")]
    )

    actions.delete_custom_folder(folder_id)
    assert db.list_custom_folders() == []
    actions.undo()

    assert db.list_custom_folders() == [
        {"id": folder_id, "name": "Favorites", "members": ["a", "b"]}
    ]


def test_undoing_an_add_leaves_the_members_that_were_already_there(tmp_path):
    db, actions = _actions(tmp_path)
    folder_id = actions.create_custom_folder("Favorites", [("a", "settings", "p1")])

    actions.add_to_custom_folder(folder_id, [("a", "settings", "p1"),
                                             ("b", "settings", "p2")])
    actions.undo()

    (record,) = db.list_custom_folders()
    assert record["members"] == ["a"]


def test_renaming_a_custom_folder_is_undoable_and_never_blanks_the_name(tmp_path):
    db, actions = _actions(tmp_path)
    folder_id = actions.create_custom_folder("Favorites", [])
    key = gallery.custom_folder_key(folder_id)

    actions.rename_folder(key, "")  # a derived folder resets; this one has nothing to
    assert db.list_custom_folders()[0]["name"] == "Favorites"

    actions.rename_folder(key, "Best of")
    assert db.list_custom_folders()[0]["name"] == "Best of"
    actions.undo()
    assert db.list_custom_folders()[0]["name"] == "Favorites"


def test_renaming_a_custom_folder_writes_no_folder_meta_overlay(tmp_path):
    # Its name is the row itself — an overlay keyed by "__custom__/1" would be a
    # second, silently-winning name.
    db, actions = _actions(tmp_path)
    folder_id = actions.create_custom_folder("Favorites", [])

    actions.rename_folder(gallery.custom_folder_key(folder_id), "Best of")

    assert db.folder_meta_map() == {}
