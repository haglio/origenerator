"""The pictures the sorting window walks, as it is handed them.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

from origenerator import gallery
from origenerator.db import Database
from origenerator.sort_pictures import waiting_pictures


def test_each_waiting_picture_carries_the_name_its_tile_wears(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    db.insert_generation(prompt_id="gen-one", workflow_name="sdxl_t2i", workflow_version="v1",
                         seed=1, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite", "seed": 1}))
    db.update_generation("gen-one", status="completed",
                         output_files=json.dumps([{"filename": "gen-one.png", "subfolder": ""}]))
    row = db.get_generation("gen-one")

    waiting = waiting_pictures(db, tmp_path)

    assert [picture["name"] for picture in waiting] == [
        f"{gallery.folder_id(gallery.settings_folder_key(row))} 000"]
