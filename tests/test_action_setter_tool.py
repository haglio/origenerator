from __future__ import annotations

import json

from PIL import Image

from origenerator import gallery
from origenerator.action_labels import Labels, labels_of
from origenerator.action_setter_tool import AnswersTold, waiting_items
from origenerator.db import Database, NewGeneration
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces


def test_each_waiting_image_carries_the_name_its_tile_wears(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    db.insert_generation(NewGeneration(prompt_id="gen-one", workflow_name="sdxl_t2i", workflow_version="v1",
                         seed=1, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite", "seed": 1})))
    db.update_generation("gen-one", status="completed",
                         output_files=json.dumps([{"filename": "gen-one.png", "subfolder": ""}]))
    row = db.get_generation("gen-one")

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE)

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
    db.set_labels("gen-two", MediaType.IMAGE, Labels(("alpha",)))

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE, "gen-two")

    assert [image["prompt_id"] for image in waiting] == ["gen-two", "gen-one"]


def test_the_image_it_was_opened_on_stands_in_the_line_once(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE, "gen-two")

    asked = [image["prompt_id"] for image in waiting]
    assert (asked[0], asked.count("gen-two"), len(asked)) == ("gen-two", 1, 2)


def test_a_waiting_image_is_shown_from_its_full_file_and_from_its_thumbnail_once_that_file_is_gone(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished_image(db, "gen-one", 1)
    db.update_generation("gen-one", thumbnail_path=str(tmp_path / "thumb.jpg"))
    places = OutputPlaces.in_one_folder(tmp_path)
    assert [image["path"] for image in waiting_items(db, places, MediaType.IMAGE)] == [str(tmp_path / "thumb.jpg")]

    Image.new("RGB", (4, 4)).save(tmp_path / "gen-one.png")

    assert [image["path"] for image in waiting_items(db, places, MediaType.IMAGE)] == [str(tmp_path / "gen-one.png")]



def test_each_answer_is_saved_and_then_told_to_whoever_asked_to_hear_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    heard = []
    store = AnswersTold(db, lambda prompt_id, side, labels: heard.append(
        (prompt_id, side, labels, labels_of(db.get_generation(prompt_id), side))))

    store.set_labels("gen-one", MediaType.IMAGE, Labels(("alpha",), ("first box",)))

    assert heard == [("gen-one", MediaType.IMAGE, Labels(("alpha",), ("first box",)),
                      Labels(("alpha",), ("first box",)))]


def test_each_item_in_line_carries_the_labels_it_has_now_and_one_never_labeled_carries_none(
        tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)
    db.set_labels("gen-two", MediaType.IMAGE, Labels((), ("first box",)))

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE)

    assert {item["prompt_id"]: item["labels"] for item in waiting} == {
        "gen-one": None, "gen-two": Labels((), ("first box",))}
