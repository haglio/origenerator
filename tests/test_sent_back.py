from __future__ import annotations

import json

from app_support import wrong_actions

from origenerator import sent_back
from origenerator.action_labels import Labels, labels_of
from origenerator.db import Database, NewGeneration
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces


def _a_finished(db, prompt_id: str, workflow: str, output: dict, **params) -> None:
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name=workflow,
                         workflow_version="v1", seed=1, workflow_json="{}",
                         params_json=json.dumps({"positive_prompt": "a red kite", "seed": 1,
                                                 **params})))
    db.update_generation(prompt_id, status="completed", output_files=json.dumps([output]))


def _a_library(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished(db, "image-one", "sdxl_t2i", {"filename": "image one.png", "subfolder": ""})
    _a_finished(db, "video-one", "wan22_i2v", {"filename": "video one.mp4", "subfolder": ""},
                input_image="image one.png")
    db.set_labels("image-one", MediaType.IMAGE, Labels(("alpha",), ("first box",)))
    db.set_labels("video-one", MediaType.VIDEO, Labels(("beta",)))
    return db


def _labels(db, prompt_id, side):
    return labels_of(db.get_generation(prompt_id), side)


def test_sending_a_video_back_asks_again_for_its_own_actions_and_its_images(tmp_path):
    db = _a_library(tmp_path)
    kept = sent_back.SentBack(tmp_path / "sent_back.json")

    said = sent_back.send_back(db, "video-one", kept)

    assert said == "alpha, beta"
    assert _labels(db, "video-one", MediaType.VIDEO) == Labels()
    assert _labels(db, "image-one", MediaType.IMAGE) == Labels()
    assert kept.ids() == ("video-one", "image-one")


def test_a_video_with_no_actions_sent_back_is_left_as_it_is(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _a_finished(db, "video-one", "wan22_t2v", {"filename": "video one.mp4", "subfolder": ""})
    kept = sent_back.SentBack(tmp_path / "sent_back.json")

    assert sent_back.send_back(db, "video-one", kept) == ""
    assert kept.ids() == ()


def test_a_video_fun_time_said_was_wrong_is_sent_back_when_the_app_takes_it_in(tmp_path):
    db = _a_library(tmp_path)
    places = OutputPlaces.in_one_folder(tmp_path)
    kept = sent_back.SentBack(tmp_path / "sent_back.json")
    wrong_actions.say(tmp_path, tmp_path / "video one.mp4")

    assert sent_back.take_in(db, places, tmp_path, kept) == 1

    assert _labels(db, "video-one", MediaType.VIDEO) == Labels()
    assert kept.ids() == ("video-one", "image-one")


def test_kinos_copy_of_one_of_the_apps_videos_is_that_video(tmp_path):
    db = _a_library(tmp_path)
    places = OutputPlaces.in_one_folder(tmp_path)
    kept = sent_back.SentBack(tmp_path / "sent_back.json")
    kinos_copy = tmp_path / "upscaled" / "portrait" / "origenerator" / "video one_topaz.mp4"
    wrong_actions.say(tmp_path, kinos_copy)

    assert sent_back.take_in(db, places, tmp_path, kept) == 1
    assert kept.ids()[0] == "video-one"


def test_a_video_from_a_site_is_found_by_where_it_was_brought_in_from(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    brought_in = tmp_path / "upscaled" / "portrait" / "sample site" / "scene one.mp4"
    _a_finished(db, "outside-one", "outside video",
                {"filename": "scene one.mp4", "library_path": str(brought_in)})
    db.set_labels("outside-one", MediaType.VIDEO, Labels(("beta",)))
    kept = sent_back.SentBack(tmp_path / "sent_back.json")
    wrong_actions.say(tmp_path, brought_in)

    assert sent_back.take_in(db, OutputPlaces.in_one_folder(tmp_path), tmp_path, kept) == 1
    assert _labels(db, "outside-one", MediaType.VIDEO) == Labels()


def test_a_video_the_app_has_no_item_for_is_let_go(tmp_path):
    db = _a_library(tmp_path)
    kept = sent_back.SentBack(tmp_path / "sent_back.json")
    wrong_actions.say(tmp_path, tmp_path / "somebody elses video.mp4")

    assert sent_back.take_in(db, OutputPlaces.in_one_folder(tmp_path), tmp_path, kept) == 0
    assert wrong_actions.take(tmp_path) == ()


def test_the_list_lets_go_of_every_item_no_longer_waiting(tmp_path):
    kept = sent_back.SentBack(tmp_path / "sent_back.json")
    kept.add(("video-one", "image-one", "video-two"))

    kept.keep_only({"image-one", "video-two"})

    assert kept.ids() == ("image-one", "video-two")


def test_an_item_sent_back_twice_stands_in_the_list_once(tmp_path):
    kept = sent_back.SentBack(tmp_path / "sent_back.json")
    kept.add(("video-one",))
    kept.add(("video-one",))

    assert kept.ids() == ("video-one",)
