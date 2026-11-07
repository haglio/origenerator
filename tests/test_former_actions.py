from __future__ import annotations

import json

from origenerator.action_labels import Labels, is_labeled, labels_of
from origenerator.db import Database, NewGeneration
from origenerator.former_actions import fill_in_labels
from origenerator.generation_state import GenerationSource
from origenerator.media import MediaType

_SITE_WORDS = {
    "Alpha Act": {"video_actions": ["alpha"]},
    "Beta Pose": {"image_actions": ["beta"], "video_actions": ["gamma"]},
    "Spray": {"video_checked": ["second box"]},
    "Close": {"image_checked": ["first box"]},
    "Wide": {},
    "Default": {},
}

_CONTENT = {
    "image_actions": {"buttons": {"one": ["alpha"], "one + two": ["alpha", "beta"]},
                      "checkboxes": ["first box"],
                      "formerly": {"one, two": {"actions": ["alpha", "beta"]}}},
    "site_words": _SITE_WORDS,
    "video_actions": {"buttons": {"three": ["gamma"], "four": ["gamma", "delta"]},
                      "checkboxes": ["second box"],
                      "formerly": {"old three": {"actions": ["gamma"]},
                                   "gone": {"actions": [], "checked": ["second box"]}}},
}


def _item(db, prompt_id, filename, *, source=GenerationSource.GENERATED):
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                                       workflow_version="v001", params_json="{}",
                                       workflow_json="{}", source=source))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename}]))


def test_an_images_earlier_answer_becomes_the_actions_its_button_stands_for(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "kept", "kept_00001_.png")
    _item(db, "renamed", "renamed_00001_.png")
    db.set_image_state("kept", "One + Two")
    db.set_image_state("renamed", "one, two")

    filled = fill_in_labels(db, _CONTENT)

    assert filled == 2
    assert [labels_of(db.get_generation(p), MediaType.IMAGE) for p in ("kept", "renamed")] == [
        Labels(("alpha", "beta")), Labels(("alpha", "beta"))]


def test_a_videos_earlier_action_becomes_its_new_actions_and_checkboxes(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "renamed", "renamed_00001_.mp4")
    _item(db, "now a box", "box_00001_.mp4")
    db.set_action("renamed", "old three")
    db.set_action("now a box", "gone")

    fill_in_labels(db, _CONTENT)

    assert [labels_of(db.get_generation(p), MediaType.VIDEO) for p in ("renamed", "now a box")] == [
        Labels(("gamma",)), Labels((), ("second box",))]


def test_an_item_already_labeled_keeps_its_labels(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "img", "img_00001_.png")
    db.set_image_state("img", "one")
    db.set_labels("img", MediaType.IMAGE, Labels(("beta",)))

    assert fill_in_labels(db, _CONTENT) == 0
    assert labels_of(db.get_generation("img"), MediaType.IMAGE) == Labels(("beta",))


def test_an_answer_no_button_ever_had_is_left_for_the_setter_tool(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _item(db, "img", "img_00001_.png")
    db.set_image_state("img", "never a button")

    assert fill_in_labels(db, _CONTENT) == 0
    assert labels_of(db.get_generation("img"), MediaType.IMAGE) == Labels()


def _brought_in(db, said, *, frame_source=GenerationSource.STARTING_FRAME):
    db.insert_generation(NewGeneration(prompt_id="frame", workflow_name="sdxl_t2i",
                                       workflow_version="v001", params_json="{}",
                                       workflow_json="{}", source=frame_source))
    db.update_generation("frame", status="completed",
                         output_files=json.dumps([{"filename": "frame_00001_.png"}]))
    db.insert_generation(NewGeneration(prompt_id="theirs", workflow_name="sdxl_t2i",
                                       workflow_version="v001", workflow_json="{}",
                                       params_json=json.dumps({"input_image": "frame_00001_.png"}),
                                       source=GenerationSource.OUTSIDE))
    db.update_generation("theirs", status="completed",
                         output_files=json.dumps([{"filename": "theirs_00001_.mp4"}]))
    db.set_action("theirs", said)


def test_a_video_from_another_site_reads_its_sites_words_onto_itself_and_its_starting_frame(
        tmp_path):
    db = Database(tmp_path / "gallery.db")
    _brought_in(db, "Close Beta Pose, Spray, alpha act")

    fill_in_labels(db, _CONTENT)

    assert labels_of(db.get_generation("theirs"), MediaType.VIDEO) == Labels(
        ("gamma", "alpha"), ("second box",))
    assert labels_of(db.get_generation("frame"), MediaType.IMAGE) == Labels(("beta",), ("first box",))


def test_its_sites_own_words_stay_as_the_site_gave_them(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _brought_in(db, "Close Beta Pose, Spray")

    fill_in_labels(db, _CONTENT)

    assert db.get_generation("theirs")["action"] == "Close Beta Pose, Spray"


def test_a_site_word_that_means_nothing_leaves_the_video_for_the_setter_tool(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _brought_in(db, "Wide Default")

    fill_in_labels(db, _CONTENT)

    assert (is_labeled(db.get_generation("theirs"), MediaType.VIDEO),
            is_labeled(db.get_generation("frame"), MediaType.IMAGE)) == (False, False)


def test_a_starting_frame_already_labeled_keeps_its_labels(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _brought_in(db, "Close Beta Pose", frame_source=GenerationSource.OUTSIDE)
    db.set_labels("frame", MediaType.IMAGE, Labels(("alpha",)))

    fill_in_labels(db, _CONTENT)

    assert labels_of(db.get_generation("frame"), MediaType.IMAGE) == Labels(("alpha",))
