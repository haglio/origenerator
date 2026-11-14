from __future__ import annotations

import json

from origenerator.db import Database, NewGeneration
from origenerator.item_actions import ItemActions
from origenerator.media import MediaType
from origenerator.published_actions import (
    PUBLISHED,
    give_the_launch_its_actions,
    published,
    put_back,
    set_actions,
    set_many_actions,
)


def _item(db, prompt_id, filename, params=None):
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                                       workflow_version="v001", workflow_json="{}",
                                       params_json=json.dumps(params or {})))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename}]))


def _published(db, prompt_id):
    said = db.get_generation(prompt_id)[PUBLISHED]
    return json.loads(said) if said is not None else None


def _a_video_from_an_image(db):
    _item(db, "img", "img_00001_.png")
    _item(db, "vid", "vid_00001_.mp4", {"input_image": "img_00001_.png"})


def test_a_video_publishes_its_images_actions_then_its_own_then_every_checked_box(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_video_from_an_image(db)

    set_actions(db, "img", MediaType.IMAGE, ItemActions(("alpha", "beta"), ("first box",)))
    set_actions(db, "vid", MediaType.VIDEO, ItemActions(("beta", "gamma"), ("third box",)))

    assert _published(db, "vid") == ["alpha", "beta", "gamma", "first box", "third box"]


def test_changing_the_images_actions_republishes_every_video_made_from_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_video_from_an_image(db)
    set_actions(db, "vid", MediaType.VIDEO, ItemActions(("gamma",)))

    set_actions(db, "img", MediaType.IMAGE, ItemActions(("delta",)))

    assert _published(db, "vid") == ["delta", "gamma"]


def test_a_video_made_from_no_image_publishes_its_own_image_actions(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "vid", "vid_00001_.mp4")

    set_actions(db, "vid", MediaType.IMAGE, ItemActions(("alpha",), ("second box",)))

    assert _published(db, "vid") == ["alpha", "second box"]


def test_a_video_nobody_has_given_actions_publishes_an_empty_list_and_an_image_publishes_nothing(
        tmp_path):
    db = Database(tmp_path / "gallery.db")
    _a_video_from_an_image(db)

    set_actions(db, "img", MediaType.IMAGE, None)

    assert (_published(db, "vid"), _published(db, "img")) == ([], None)


def test_a_box_checked_on_both_the_image_and_the_video_is_named_once():
    image = {"image_actions": json.dumps(["alpha"]), "image_checked": json.dumps(["box"])}
    video = {"video_actions": json.dumps(["alpha"]), "video_checked": json.dumps(["box"])}

    assert published(video, image) == ("alpha", "box")


def _combined_from(db, prompt_id, source, number):
    _item(db, prompt_id, f"{prompt_id}_{number:05d}_.mp4")
    db.set_settings_source(prompt_id, category="", video_prompt_id=source)


def test_a_videos_actions_go_to_every_video_combined_from_it_and_on_down(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "source", "source_00001_.mp4")
    _combined_from(db, "combined", "source", 2)
    _combined_from(db, "combined again", "combined", 3)
    _item(db, "other", "other_00004_.mp4")
    set_actions(db, "combined", MediaType.VIDEO, ItemActions(("gamma",)))

    set_actions(db, "source", MediaType.VIDEO, ItemActions(("alpha",), ("first box",)))

    assert {prompt_id: db.get_generation(prompt_id)["video_actions"]
            for prompt_id in ("source", "combined", "combined again", "other")} == {
        "source": '["alpha"]', "combined": '["alpha"]', "combined again": '["alpha"]',
        "other": None}


def test_videos_saved_together_say_each_video_they_gave_actions_to_and_keep_their_own(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "source", "source_00001_.mp4")
    _combined_from(db, "combined", "source", 2)
    _item(db, "other", "other_00003_.mp4")

    given = set_many_actions(db, MediaType.VIDEO, {"source": ItemActions(("alpha",)),
                                                   "combined": ItemActions(("gamma",)),
                                                   "other": ItemActions(("beta",))}).after

    assert given == {"source": ItemActions(("alpha",)), "combined": ItemActions(("gamma",)),
                     "other": ItemActions(("beta",))}


def test_a_video_saved_with_others_gives_its_actions_to_every_video_combined_from_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "source", "source_00001_.mp4")
    _combined_from(db, "combined", "source", 2)
    _item(db, "other", "other_00003_.mp4")

    given = set_many_actions(db, MediaType.VIDEO, {"source": ItemActions(("alpha",)),
                                                   "other": ItemActions(("beta",))}).after

    assert (given["combined"], db.get_generation("combined")["video_actions"]) == (
        ItemActions(("alpha",)), '["alpha"]')


def test_putting_back_what_a_videos_actions_replaced_gives_each_video_its_own_again(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "source", "source_00001_.mp4")
    _combined_from(db, "combined", "source", 2)
    set_actions(db, "combined", MediaType.VIDEO, ItemActions(("gamma",), ("third box",)))

    put_back(db, MediaType.VIDEO,
             set_actions(db, "source", MediaType.VIDEO, ItemActions(("alpha",))))

    assert [(db.get_generation(prompt_id)["video_actions"],
             db.get_generation(prompt_id)["video_checked"])
            for prompt_id in ("source", "combined")] == [
        (None, None), ('["gamma"]', '["third box"]')]
    assert _published(db, "combined") == ["gamma", "third box"]


def test_a_combine_started_from_a_video_with_no_action_picked_takes_the_videos_actions(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "source", "source_00001_.mp4")
    set_actions(db, "source", MediaType.VIDEO, ItemActions(("alpha",), ("first box",)))
    _combined_from(db, "combined", "source", 2)

    give_the_launch_its_actions(db, "combined")

    assert (db.get_generation("combined")["video_actions"],
            db.get_generation("combined")["video_checked"]) == ('["alpha"]', '["first box"]')
