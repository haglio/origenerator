from __future__ import annotations

import json

from origenerator.db import Database, NewGeneration
from origenerator.item_actions import ItemActions
from origenerator.media import MediaType
from origenerator.published_actions import PUBLISHED, published, set_actions


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
