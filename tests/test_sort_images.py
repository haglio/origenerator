from __future__ import annotations

import json

from PIL import Image

from origenerator import gallery
from origenerator.db import Database, NewGeneration
from origenerator.output_places import OutputPlaces
from origenerator.sort_images import AnswersTold, waiting_images


def test_each_waiting_image_carries_the_name_its_tile_wears(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    db.insert_generation(NewGeneration(prompt_id="gen-one", workflow_name="sdxl_t2i", workflow_version="v1",
                         seed=1, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite", "seed": 1})))
    db.update_generation("gen-one", status="completed",
                         output_files=json.dumps([{"filename": "gen-one.png", "subfolder": ""}]))
    row = db.get_generation("gen-one")

    waiting = waiting_images(db, OutputPlaces.in_one_folder(tmp_path))

    assert [image["name"] for image in waiting] == [
        f"{gallery.folder_id(gallery.settings_folder_key(row))} 000"]


def _a_finished_image(db, prompt_id: str, seed: int) -> None:
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v1", seed=seed, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite",
                                                 "seed": seed})))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png",
                                                   "subfolder": ""}]))


def test_the_line_starts_with_the_image_it_was_opened_on(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)
    db.set_image_state("gen-two", "state two")

    waiting = waiting_images(db, OutputPlaces.in_one_folder(tmp_path), "gen-two")

    assert [image["prompt_id"] for image in waiting] == ["gen-two", "gen-one"]


def test_the_image_it_was_opened_on_stands_in_the_line_once(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)

    waiting = waiting_images(db, OutputPlaces.in_one_folder(tmp_path), "gen-two")

    asked = [image["prompt_id"] for image in waiting]
    assert (asked[0], asked.count("gen-two"), len(asked)) == ("gen-two", 1, 2)


def test_a_waiting_image_is_shown_from_its_full_file_and_from_its_thumbnail_once_that_file_is_gone(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_image(db, "gen-one", 1)
    db.update_generation("gen-one", thumbnail_path=str(tmp_path / "thumb.jpg"))
    places = OutputPlaces.in_one_folder(tmp_path)
    assert [image["image_path"] for image in waiting_images(db, places)] == [str(tmp_path / "thumb.jpg")]

    Image.new("RGB", (4, 4)).save(tmp_path / "gen-one.png")

    assert [image["image_path"] for image in waiting_images(db, places)] == [str(tmp_path / "gen-one.png")]



def test_each_answer_is_saved_and_then_told_to_whoever_asked_to_hear_it(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_image(db, "gen-one", 1)
    heard = []
    store = AnswersTold(db, lambda prompt_id, said: heard.append(
        (prompt_id, said, db.get_generation(prompt_id)["image_state"])))

    store.set_image_state("gen-one", "state one")
    store.set_image_state("gen-one", None)

    assert heard == [("gen-one", "state one", "state one"), ("gen-one", "", None)]
