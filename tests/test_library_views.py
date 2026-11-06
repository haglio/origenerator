from __future__ import annotations

import json

from origenerator import gallery, library_views
from origenerator.db import Database, NewGeneration
from origenerator.gallery.collection import FAVORITES_KEY, LATEST_KEY, TRASH_KEY
from origenerator.gallery.custom import custom_collection_key
from origenerator.gallery.tree import ALL_KEY
from origenerator.item_shape import filter_rows, shaped_key
from origenerator.library_views import LibrarySnapshot, LibraryViews
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.children import run_python


def _image(db, prompt_id, seed):
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), seed=seed)
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version=WORKFLOW_REGISTRY["sdxl_t2i"].version,
                         params_json=json.dumps(params), workflow_json="{}"))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png",
                                                   "subfolder": "image"}]))


def test_the_same_library_is_one_reading(tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db, "pic-1", 1)
    views = LibraryViews(db)

    assert views.now() is views.now()


def test_a_change_to_the_library_is_read_at_once(tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db, "pic-1", 1)
    views = LibraryViews(db)
    views.now()

    _image(Database(tmp_path / "test.db"), "pic-2", 2)

    assert [row["prompt_id"] for row in views.now().image_rows] == ["pic-2", "pic-1"]


def test_a_change_another_program_makes_to_the_library_is_read_at_once(tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db, "pic-1", 1)
    views = LibraryViews(db)
    assert not views.now().image_rows[0]["starred"]

    star_it = ("import sys; from origenerator.db import Database;"
               " Database(sys.argv[1]).set_generation_favorite('pic-1', True)")
    run_python(["-c", star_it, str(db.path)], check=True)

    assert views.now().image_rows[0]["starred"]


def test_a_reading_holds_what_the_trash_holds(tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db, "pic-1", 1)
    db.record_trashed("pic-1", db.get_generation("pic-1"), {"moves": [], "subdir": None})
    db.delete_generation("pic-1")

    assert [row["prompt_id"] for row in LibraryViews(db).now().held_rows] == ["pic-1"]


def test_a_settings_folder_is_looked_up_once_for_each_reading(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _image(db, "pic-1", 1)
    lookups = []
    lookup = gallery.rows_in_settings
    monkeypatch.setattr(gallery, "rows_in_settings",
                        lambda *args: lookups.append(args) or lookup(*args))
    library = LibraryViews(db).now()
    folder = ("sdxl_t2i", gallery.settings_signature(
        "sdxl_t2i", library.rows[0]["params_json"], library.image_config_index,
        workflow_version=library.rows[0]["workflow_version"]))

    assert [row["prompt_id"] for row in library.in_settings(folder)] == ["pic-1"]
    library.in_settings(folder)
    assert len(lookups) == 1


def _listed(prompt_id, *, shape="landscape", source="generated", starred=False, seed=1):
    return {"prompt_id": prompt_id, "shape": shape, "source": source, "starred": starred,
            "workflow_name": "sdxl_t2i", "status": "completed",
            "params_json": json.dumps({"positive_prompt": "scene one", "seed": seed}),
            "output_files": json.dumps([{"filename": f"{prompt_id}.png"}])}


def test_a_reading_finds_each_row_by_its_id():
    rows = [_listed("pic-1"), _listed("pic-2")]

    library = LibrarySnapshot(rows)

    assert library.rows_by_id["pic-2"] is rows[1]
    assert library.rows_by_id.get("nobody") is None


def test_the_map_of_a_shape_holds_what_is_on_the_map_in_that_shape():
    rows = [_listed("tall", shape="portrait"), _listed("wide", shape="landscape"),
            _listed("left-out", shape="portrait", source="left_out")]
    library = LibrarySnapshot(rows)

    assert [row["prompt_id"] for row in library.on_the_map("portrait")] == ["tall"]
    assert library.on_the_map("portrait") is library.on_the_map("portrait")


def test_a_reading_knows_which_items_are_starred():
    library = LibrarySnapshot([_listed("pic-1", starred=True), _listed("pic-2")])

    assert library.favorite_ids == {"pic-1"}


def test_a_readings_tree_of_a_shape_is_the_gallery_tree_of_that_shapes_rows():
    rows = [_listed("tall", shape="portrait"), _listed("wide"), _listed("tall-too", shape="portrait")]
    meta = {"image": {"custom_name": "Stills", "starred": True}}

    library = LibrarySnapshot(rows, folder_meta=meta, name_of=lambda prompt_id: prompt_id)

    assert library.image_index == gallery.start_frame_index(rows)
    assert library.tree("portrait") == gallery.build_gallery_tree(
        filter_rows(rows, "portrait"), meta, image_index=library.image_index,
        name_of=lambda prompt_id: prompt_id)
    assert library.tree("portrait") is library.tree("portrait")
    assert [row["prompt_id"] for row in gallery.rows_under(library.tree("landscape")[0])] == ["wide"]


def test_a_reading_of_a_library_that_has_not_moved_keeps_the_trees_of_the_reading_before_it():
    rows = [_listed("tall", shape="portrait"), _listed("wide")]
    before = LibrarySnapshot(rows)
    before.tree("portrait")

    after = LibrarySnapshot(rows, trees_from=before)

    assert after.tree("portrait") is before.tree("portrait")
    assert after.image_index is before.image_index
    assert after.tree("landscape") == before.tree("landscape")


def _models_in(library, shape):
    (images,) = library.tree(shape)
    (workflow,) = gallery.child_groups(images)
    return {model.label: model.key for model in gallery.child_groups(workflow)}


def _made_with(prompt_id, checkpoint, *, shape="landscape", starred=False, source="generated",
               completed_at="2026-11-01 10:00:00"):
    row = _listed(prompt_id, shape=shape, starred=starred, source=source)
    row["params_json"] = json.dumps({"positive_prompt": "scene one", "seed": 1,
                                     "checkpoint": checkpoint})
    row["completed_at"] = completed_at
    return row


def test_a_folders_latest_is_what_that_folder_holds_of_the_shape_newest_first():
    rows = [_made_with("a1", "alpha.safetensors", completed_at="2026-11-01 09:00:00"),
            _made_with("a2", "alpha.safetensors", completed_at="2026-11-01 11:00:00"),
            _made_with("b1", "beta.safetensors"),
            _made_with("tall", "alpha.safetensors", shape="portrait"),
            _made_with("trial", "alpha.safetensors", source="experiment")]
    library = LibrarySnapshot(rows)

    latest_in_alpha = library.in_collection(LATEST_KEY, "landscape",
                                            _models_in(library, "landscape")["alpha"])

    assert [row["prompt_id"] for row in latest_in_alpha] == ["a2", "a1"]
    assert [row["prompt_id"] for row in library.in_collection(LATEST_KEY, "portrait", ALL_KEY)] == ["tall"]


def test_favorites_are_the_starred_items_and_everything_under_a_starred_folder_each_once():
    rows = [_made_with("a1", "alpha.safetensors", starred=True),
            _made_with("a2", "alpha.safetensors"),
            _made_with("b1", "beta.safetensors")]
    library = LibrarySnapshot(rows)
    alpha = _models_in(library, "landscape")["alpha"]
    library = LibrarySnapshot(rows, folder_meta={alpha: {"custom_name": None, "starred": True}})

    favorites = library.in_collection(FAVORITES_KEY, "landscape", ALL_KEY)

    assert sorted(row["prompt_id"] for row in favorites) == ["a1", "a2"]


def test_the_trash_of_a_folder_holds_what_was_deleted_from_it():
    kept = _made_with("a1", "alpha.safetensors")
    held = [_made_with("d1", "alpha.safetensors"), _made_with("d2", "beta.safetensors")]
    library = LibrarySnapshot([kept], held)

    in_alpha = library.in_collection(TRASH_KEY, "landscape", _models_in(library, "landscape")["alpha"])

    assert [row["prompt_id"] for row in in_alpha] == ["d1"]
    assert library.held_rows is held


def test_a_collection_key_with_its_shape_names_what_a_reading_lists_there():
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("tall", "alpha.safetensors", shape="portrait")]
    library = LibrarySnapshot(rows)

    assert [row["prompt_id"] for row in library.rows_at(shaped_key(LATEST_KEY, "portrait"))] == ["tall"]
    assert library.rows_at("not/a/collection") == []


def test_a_reading_deals_its_rows_to_a_shape_once_however_often_it_is_asked(monkeypatch):
    dealt = []
    filter_rows = library_views.filter_rows
    monkeypatch.setattr(library_views, "filter_rows",
                        lambda rows, shape: dealt.append(shape) or filter_rows(rows, shape))
    library = LibrarySnapshot([_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")])

    library.on_shape("landscape")
    library.in_collection(FAVORITES_KEY, "landscape", ALL_KEY)
    library.in_collection(LATEST_KEY, "landscape", ALL_KEY)
    once = len(dealt)
    library.on_shape("landscape")
    library.in_collection(FAVORITES_KEY, "landscape", ALL_KEY)
    library.in_collection(LATEST_KEY, "landscape", ALL_KEY)

    assert library.on_shape("landscape") == filter_rows(library.rows, "landscape")
    assert len(dealt) == once


def test_a_star_given_after_the_reading_was_taken_still_counts_since_the_gallery_stars_rows_in_place():
    row = _listed("pic-1")
    library = LibrarySnapshot([row])
    assert library.favorite_ids == set()

    row["starred"] = 1

    assert library.favorite_ids == {"pic-1"}


def test_a_folder_key_with_its_shape_names_what_a_reading_holds_under_that_folder():
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("a2", "alpha.safetensors"),
            _made_with("b1", "beta.safetensors")]
    library = LibrarySnapshot(rows)
    alpha = _models_in(library, "landscape")["alpha"]

    assert [row["prompt_id"] for row in library.rows_at(shaped_key(alpha, "landscape"))] == ["a1", "a2"]
    assert [row["prompt_id"] for row in library.rows_at(shaped_key(ALL_KEY, "landscape"))] == ["a1", "a2", "b1"]
    assert library.rows_at(shaped_key("nobody/knows", "landscape")) == []
    assert library.ids_at(shaped_key(alpha, "landscape")) == frozenset({"a1", "a2"})
    assert library.ids_at(shaped_key(alpha, "landscape")) is library.ids_at(shaped_key(alpha, "landscape"))


def test_a_custom_collection_of_a_shape_gathers_the_folders_and_items_its_record_names():
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors"),
            _made_with("tall", "alpha.safetensors", shape="portrait")]
    alpha = _models_in(LibrarySnapshot(rows), "landscape")["alpha"]
    records = [{"id": 3, "name": "Picks", "side": "landscape", "folders": [alpha], "items": ["b1"]}]

    library = LibrarySnapshot(rows, custom_collections=records)

    (picks,) = library.custom_collections("landscape")
    assert (picks.key, picks.label) == (custom_collection_key(3), "Picks")
    assert sorted(row["prompt_id"] for row in library.rows_at(shaped_key(picks.key, "landscape"))) == ["a1", "b1"]
    assert library.custom_collections("portrait") == []


def _resolving_by_id(monkeypatch, resolved: list):
    def resolve(row, _places):
        resolved.append(row["prompt_id"])
        return (f"{row['prompt_id']}.png", "image")
    monkeypatch.setattr(gallery, "resolve_preview", resolve)
    monkeypatch.setattr(library_views.EvolverUpscales, "scan",
                        lambda *args: library_views.EvolverUpscales({}))


def test_a_reading_resolves_each_slides_file_once_however_many_sets_ask_for_it(monkeypatch):
    resolved = []
    _resolving_by_id(monkeypatch, resolved)
    rows = [_listed("pic-1"), _listed("pic-2")]
    library = LibrarySnapshot(rows)

    first = library.slides_of(rows)
    again = library.slides_of([rows[1]])

    assert first == [("pic-1.png", "image", "pic-1", None), ("pic-2.png", "image", "pic-2", None)]
    assert again == [first[1]]
    assert resolved == ["pic-1", "pic-2"]


def test_a_row_whose_files_changed_is_resolved_again_within_the_same_reading(monkeypatch):
    resolved = []
    _resolving_by_id(monkeypatch, resolved)
    row = _listed("pic-1")
    library = LibrarySnapshot([row])
    library.slides_of([row])

    library.slides_of([{**row, "output_files": json.dumps([{"filename": "pic-1_v2.png"}])}])

    assert resolved == ["pic-1", "pic-1"]


def test_a_reading_scans_evolvers_upscales_once(monkeypatch):
    scanned = []
    monkeypatch.setattr(gallery, "resolve_preview", lambda row, _places: ("pic-1.mp4", "video"))
    monkeypatch.setattr(library_views.EvolverUpscales, "scan",
                        lambda *args: scanned.append(args) or library_views.EvolverUpscales({}))
    library = LibrarySnapshot([_listed("pic-1")])

    library.slides_of(library.rows)
    library.versions_of(library.rows)
    library.slides_of(library.rows)

    assert len(scanned) == 1
