from __future__ import annotations

import json

from app_support import wrong_actions

from origenerator import gallery
from origenerator.action_setter_tool import (
    AnswersTold,
    ThrownInto,
    asks_to_keep_going,
    waiting_folders,
)
from origenerator.db import Database, NewGeneration
from origenerator.gui.action_setter_window import ask_to_keep_going
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.sent_back import Returned, SentBack


def _a_finished_image(db, prompt_id: str, seed: int, prompt: str = "a red kite") -> None:
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v1", seed=seed, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": prompt, "seed": seed})))
    db.update_generation(prompt_id, status="completed", thumbnail_path=f"{prompt_id}_thumb.jpg",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png",
                                                   "subfolder": ""}]))


def _waiting(db, tmp_path, side=MediaType.IMAGE, first="", **kwargs):
    return waiting_folders(db, OutputPlaces.in_one_folder(tmp_path), side, first, **kwargs)


def _in_each(folders) -> list[list[str]]:
    return [[item["prompt_id"] for item in folder["items"]] for folder in folders]


def test_the_images_of_one_folder_wait_together_under_the_name_the_toc_gives_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)

    [folder] = _waiting(db, tmp_path)

    assert (folder["name"], sorted(_in_each([folder])[0])) == (
        gallery.folder_id(gallery.settings_folder_key(db.get_generation("gen-one"))),
        ["gen-one", "gen-two"])


def test_a_folder_waits_while_any_of_its_items_has_no_actions_and_shows_them_all(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2)
    _a_finished_image(db, "all set", 3, "a blue kite")
    db.set_actions("gen-two", MediaType.IMAGE, ItemActions(("alpha",)))
    db.set_actions("all set", MediaType.IMAGE, ItemActions(("alpha",)))

    [folder] = _waiting(db, tmp_path)

    assert (sorted(_in_each([folder])[0]), sorted(folder["thumbnails"])) == (
        ["gen-one", "gen-two"], ["gen-one_thumb.jpg", "gen-two_thumb.jpg"])


def test_the_line_starts_with_the_folder_of_the_item_it_was_opened_on(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2, "a blue kite")
    db.set_actions("gen-two", MediaType.IMAGE, ItemActions(("alpha",)))

    assert _in_each(_waiting(db, tmp_path, first="gen-two")) == [["gen-two"], ["gen-one"]], (
        "the user's ask: start with the item in front of them, then go on to the usual line")


def test_the_folder_it_was_opened_on_stands_in_the_line_once(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    _a_finished_image(db, "gen-two", 2, "a blue kite")

    assert _in_each(_waiting(db, tmp_path, first="gen-two")) == [["gen-two"], ["gen-one"]]


def test_a_folder_carries_the_actions_its_items_share_and_none_when_they_differ(tmp_path):
    db = Database(tmp_path / "gallery.db")
    for prompt_id, seed, prompt in (("one", 1, "a red kite"), ("two", 2, "a red kite"),
                                    ("three", 3, "a blue kite"), ("four", 4, "a blue kite"),
                                    ("five", 5, "a blue kite")):
        _a_finished_image(db, prompt_id, seed, prompt)
    db.set_actions("two", MediaType.IMAGE, ItemActions((), ("first box",)))
    db.set_actions("three", MediaType.IMAGE, ItemActions(("alpha",)))
    db.set_actions("four", MediaType.IMAGE, ItemActions(("beta",)))

    assert sorted((sorted(_in_each([folder])[0]), folder["actions"])
                  for folder in _waiting(db, tmp_path)) == [
        (["five", "four", "three"], None), (["one", "two"], ItemActions((), ("first box",)))]


def test_each_answer_is_saved_and_then_told_to_whoever_asked_to_hear_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    heard = []
    store = AnswersTold(db, lambda prompt_id, side, item_actions: heard.append(
        (prompt_id, side, item_actions, actions_of(db.get_generation(prompt_id), side))))

    store.set_actions("gen-one", MediaType.IMAGE, ItemActions(("alpha",), ("first box",)))

    assert heard == [("gen-one", MediaType.IMAGE, ItemActions(("alpha",), ("first box",)),
                      ItemActions(("alpha",), ("first box",)))]



def test_an_answer_taken_back_is_told_too(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_image(db, "gen-one", 1)
    heard = []
    store = AnswersTold(db, lambda prompt_id, side, item_actions: heard.append(
        (prompt_id, item_actions, actions_of(db.get_generation(prompt_id), side))))

    store.put_back(MediaType.IMAGE, store.set_actions("gen-one", MediaType.IMAGE,
                                                      ItemActions(("alpha",))))

    assert heard[-1] == ("gen-one", None, ItemActions())

def _a_finished_video(db, prompt_id: str, *, made_from: str | None = None) -> None:
    params = {"positive_prompt": f"{prompt_id} flies", "noise_seed": 3}
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

    [folder] = _waiting(db, tmp_path)

    assert (_in_each([folder]), folder["thumbnails"]) == ([["vid"]], ["vid_thumb.jpg"])


def test_opened_on_an_item_it_asks_whether_to_go_on_and_opened_on_its_own_it_never_does():
    assert (asks_to_keep_going("first"), asks_to_keep_going("")) == (ask_to_keep_going, None)


def test_a_video_said_to_have_the_wrong_actions_comes_first_in_the_line(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "said")
    _a_finished_video(db, "favorite")
    db.set_generation_favorite("favorite", True)
    db.set_actions("said", MediaType.VIDEO, ItemActions(("beta",)))
    wrong_actions.say(tmp_path, tmp_path / "said.mp4")

    waiting = _waiting(db, tmp_path, MediaType.VIDEO,
                       returned=Returned(SentBack(tmp_path / "sent_back.json"), tmp_path))

    assert _in_each(waiting) == [["said"], ["favorite"]]


def test_an_item_sent_back_leaves_the_list_once_it_has_its_actions_again(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "vid")
    kept = SentBack(tmp_path / "sent_back.json")
    kept.add(("vid",))
    db.set_actions("vid", MediaType.VIDEO, ItemActions(("beta",)))
    db.set_actions("vid", MediaType.IMAGE, ItemActions(("alpha",)))

    _waiting(db, tmp_path, MediaType.VIDEO, returned=Returned(kept, tmp_path))

    assert kept.ids() == ()


def test_each_item_in_line_says_which_item_is_shown_for_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_finished_video(db, "vid")

    [folder] = _waiting(db, tmp_path, MediaType.VIDEO)

    assert folder["items"][0]["shown_id"] == "vid"


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
