"""What the config tabs read off the whole library, worked out once for each
state of it.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

from origenerator import gallery
from origenerator.db import Database
from origenerator.library_views import LibraryViews
from origenerator.workflows import WORKFLOW_REGISTRY


def _picture(db, prompt_id, seed):
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), seed=seed)
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version=WORKFLOW_REGISTRY["sdxl_t2i"].version,
                         params_json=json.dumps(params), workflow_json="{}")
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png",
                                                   "subfolder": "image"}]))


def test_the_same_library_is_one_reading(tmp_path):
    db = Database(tmp_path / "test.db")
    _picture(db, "pic-1", 1)
    views = LibraryViews(db)

    assert views.now() is views.now()


def test_a_change_to_the_library_is_read_at_once(tmp_path):
    db = Database(tmp_path / "test.db")
    _picture(db, "pic-1", 1)
    views = LibraryViews(db)
    views.now()

    _picture(Database(tmp_path / "test.db"), "pic-2", 2)

    assert [row["prompt_id"] for row in views.now().image_rows] == ["pic-2", "pic-1"]


def test_a_settings_folder_is_looked_up_once_for_each_reading(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _picture(db, "pic-1", 1)
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
