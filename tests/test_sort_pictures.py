"""The pictures the sorting window walks, as it is handed them.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

from origenerator import gallery
from origenerator.db import Database
from origenerator.output_places import OutputPlaces
from origenerator.sort_pictures import waiting_pictures


def test_each_waiting_picture_carries_the_name_its_tile_wears(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    db.insert_generation(prompt_id="gen-one", workflow_name="sdxl_t2i", workflow_version="v1",
                         seed=1, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite", "seed": 1}))
    db.update_generation("gen-one", status="completed",
                         output_files=json.dumps([{"filename": "gen-one.png", "subfolder": ""}]))
    row = db.get_generation("gen-one")

    waiting = waiting_pictures(db, OutputPlaces.in_one_folder(tmp_path))

    assert [picture["name"] for picture in waiting] == [
        f"{gallery.folder_id(gallery.settings_folder_key(row))} 000"]


def _a_finished_picture(db, prompt_id: str, seed: int) -> None:
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v1", seed=seed, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite",
                                                 "seed": seed}))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png",
                                                   "subfolder": ""}]))


def test_the_line_starts_with_the_picture_it_was_opened_on(tmp_path):
    """His words: it "should start with the current image, then go on to the usual
    queue" -- so the one in front of him comes first even with an action already."""
    db = Database(tmp_path / "origenerator.db")
    _a_finished_picture(db, "gen-one", 1)
    _a_finished_picture(db, "gen-two", 2)
    db.set_picture_state("gen-two", "state two")

    waiting = waiting_pictures(db, OutputPlaces.in_one_folder(tmp_path), "gen-two")

    assert [picture["prompt_id"] for picture in waiting] == ["gen-two", "gen-one"]


def test_the_picture_it_was_opened_on_stands_in_the_line_once(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_picture(db, "gen-one", 1)
    _a_finished_picture(db, "gen-two", 2)

    waiting = waiting_pictures(db, OutputPlaces.in_one_folder(tmp_path), "gen-two")

    asked = [picture["prompt_id"] for picture in waiting]
    assert (asked[0], asked.count("gen-two"), len(asked)) == ("gen-two", 1, 2)
