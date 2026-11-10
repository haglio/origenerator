from __future__ import annotations

import json

from app_support import wrong_actions
from PIL import Image

from origenerator import gallery
from origenerator.action_setter_tool import (
    AnswersTold,
    ThrownInto,
    asks_to_keep_going,
    waiting_items,
)
from origenerator.db import Database, NewGeneration
from origenerator.gui.action_setter_window import ask_to_keep_going
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.sent_back import Returned, SentBack


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
    db.set_actions("gen-two", MediaType.IMAGE, ItemActions(("alpha",)))

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE, "gen-two")

    assert [image["prompt_id"] for image in waiting] == ["gen-two", "gen-one"], (
        "the image in front of the user comes first even when it has an action already, then the "
        "usual line")


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
    store = AnswersTold(db, lambda prompt_id, side, item_actions: heard.append(
        (prompt_id, side, item_actions, actions_of(db.get_generation(prompt_id), side))))

    store.set_actions("gen-one", MediaType.IMAGE, ItemActions(("alpha",), ("first box",)))

    assert heard == [("gen-one", MediaType.IMAGE, ItemActions(("alpha",), ("first box",)),
                      ItemActions(("alpha",), ("first box",)))]


def test_each_item_in_line_carries_the_actions_it_has_now_and_one_never_given_any_carries_none(
        tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)
    db.set_actions("gen-two", MediaType.IMAGE, ItemActions((), ("first box",)))

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE)

    assert {item["prompt_id"]: item["actions"] for item in waiting} == {
        "gen-one": None, "gen-two": ItemActions((), ("first box",))}


def _a_finished_video(db, prompt_id: str, *, made_from: str | None = None) -> None:
    params = {"positive_prompt": "a red kite flies", "noise_seed": 3}
    if made_from:
        params["input_image"] = f"{made_from}.png"
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="wan22_i2v",
                         workflow_version="v1", workflow_json="{}",
                         params_json=json.dumps(params)))
    db.update_generation(prompt_id, status="completed", thumbnail_path=f"{prompt_id}_thumb.jpg",
                         output_files=json.dumps([{"filename": f"{prompt_id}.mp4",
                                                   "subfolder": ""}]))


def test_a_video_made_from_no_image_waits_among_the_images_shown_by_its_first_frame(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "vid")

    [item] = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.IMAGE)

    assert (item["prompt_id"], item["path"]) == ("vid", "vid_thumb.jpg")


def test_opened_on_an_item_it_asks_whether_to_go_on_and_opened_on_its_own_it_never_does():
    assert (asks_to_keep_going("first"), asks_to_keep_going("")) == (ask_to_keep_going, None)


def test_a_video_said_to_have_the_wrong_actions_comes_first_in_the_line(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "said")
    _a_finished_video(db, "favorite")
    db.set_generation_favorite("favorite", True)
    db.set_actions("said", MediaType.VIDEO, ItemActions(("beta",)))
    wrong_actions.say(tmp_path, tmp_path / "said.mp4")

    waiting = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.VIDEO,
                            returned=Returned(SentBack(tmp_path / "sent_back.json"), tmp_path))

    assert [video["prompt_id"] for video in waiting] == ["said", "favorite"]


def test_an_item_sent_back_leaves_the_list_once_it_has_its_actions_again(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "vid")
    kept = SentBack(tmp_path / "sent_back.json")
    kept.add(("vid",))
    db.set_actions("vid", MediaType.VIDEO, ItemActions(("beta",)))
    db.set_actions("vid", MediaType.IMAGE, ItemActions(("alpha",)))

    waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.VIDEO,
                  returned=Returned(kept, tmp_path))

    assert kept.ids() == ()


def test_each_item_in_line_says_which_item_is_shown_for_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "vid")

    [item] = waiting_items(db, OutputPlaces.in_one_folder(tmp_path), MediaType.VIDEO)

    assert item["shown_id"] == "vid"


def test_a_trashed_item_goes_the_way_the_gallery_deletes_and_comes_back_as_it_restores(
        tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    deleted, restored = [], []
    rubbish = ThrownInto(db, deleted.extend, restored.extend)

    rubbish.away("gen-one")
    rubbish.away("never-made")
    rubbish.back("gen-one")

    assert ([row["prompt_id"] for row in deleted], restored) == (["gen-one"], ["gen-one"])
