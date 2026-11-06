from __future__ import annotations

import json

from origenerator import gallery
from origenerator.db import Database, NewGeneration
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


def _listed(prompt_id, *, shape="landscape", source="generated", starred=False):
    return {"prompt_id": prompt_id, "shape": shape, "source": source, "starred": starred,
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
