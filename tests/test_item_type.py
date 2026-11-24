from __future__ import annotations

import json

from origenerator import config, gallery
from origenerator.gallery.output import item_type_of
from origenerator.item_shape import key_holds
from origenerator.media import ItemType, icon_name
from origenerator.workflows.non_ai import NonAiWorkflow, non_ai_workflow


def _made(workflow_name: str, filename: str) -> dict:
    return {"workflow_name": workflow_name, "output_files": json.dumps([{"filename": filename}])}


def _kept(prompt_id: str, workflow_name: str, filename: str) -> dict:
    return {**_made(workflow_name, filename), "prompt_id": prompt_id, "status": "completed",
            "params_json": json.dumps({"positive_prompt": "alpha", "seed": 1}),
            "created_at": "2026-01-01T00:00:00"}


_AN_IMAGE = _kept("one", "sdxl_t2i", "image one.png")
_A_VIDEO = _kept("two", "wan22_t2v", "video one.mp4")
_A_FLICK = _kept("three", "wan22_flf2v_loop", "video two.mp4")


def test_an_item_is_an_image_a_video_or_what_a_looping_workflow_made_which_is_a_flick():
    assert [item_type_of(_made(workflow, filename)) for workflow, filename in (
        ("sdxl_t2i", "image one.png"), ("wan22_i2v", "video one.mp4"),
        ("wan22_flf2v_loop", "video two.mp4"))] == [
            ItemType.IMAGE, ItemType.VIDEO, ItemType.FLICK]


def test_a_video_no_model_made_is_a_flick_where_genau_keeps_it_and_a_video_anywhere_else(
        tmp_path, monkeypatch):
    genau = tmp_path / "videos" / "sample app"
    monkeypatch.setattr(config, "GENAU_DIR", genau)
    monkeypatch.setattr(config, "GENAU_FLICKS_NO_MODEL_MADE",
                        (genau / "flicks" / "2D" / "non_AI", genau / "flicks" / "VR"))

    assert [item_type_of(_made(non_ai_workflow(folder), "video one.mp4"))
            for folder in ("sample app flicks", "sample full")] == [ItemType.FLICK, ItemType.VIDEO]


def test_the_toc_files_flicks_in_a_folder_of_their_own_after_the_images_and_the_videos():
    tree = gallery.build_gallery_tree([_A_FLICK, _A_VIDEO, _AN_IMAGE])

    assert [(folder.key, folder.label, [row["prompt_id"] for row in gallery.rows_under(folder)])
            for folder in tree] == [
        ("image", "Images", ["one"]), ("video", "Videos", ["two"]), ("flick", "Flicks", ["three"])]


def test_a_flick_s_folders_keep_the_keys_they_had_when_a_flick_was_filed_as_a_video():
    chain = gallery.folder_chain(_A_FLICK)

    assert chain[:3] == (gallery.ALL_KEY, "flick", "video/wan22_flf2v_loop")
    assert all(key.startswith("video/wan22_flf2v_loop/") for key in chain[3:])


def test_the_flicks_folder_holds_every_folder_of_a_flick_and_the_videos_folder_none_of_them():
    flicks_folders, videos_folders = gallery.folder_chain(_A_FLICK)[2:], gallery.folder_chain(_A_VIDEO)[2:]

    assert all(key_holds("flick", key) and not key_holds("video", key) for key in flicks_folders)
    assert all(key_holds("video", key) and not key_holds("flick", key) for key in videos_folders)


def test_a_count_of_flicks_says_flicks_and_a_count_of_mixed_types_says_items():
    another = dict(_A_FLICK, prompt_id="four")

    assert [gallery.counted(rows) for rows in (
        [_A_FLICK], [_A_FLICK, another], [_A_FLICK, _A_VIDEO], [_AN_IMAGE])] == [
            "1 flick", "2 flicks", "2 items", "1 image"]


def test_a_job_making_a_flick_is_said_in_the_word_the_settings_give_a_flick():
    kind = gallery.job_kind_label("wan22_flf2v_loop")

    assert (gallery.made_by_a_job(kind), gallery.job_kind_said(kind)) == (ItemType.FLICK, "Flick")
    assert gallery.job_kind_said(gallery.job_kind_label("wan22_i2v")) == "Video"


def test_each_type_of_item_has_an_icon_of_its_own():
    assert [icon_name(item_type) for item_type in ItemType] == ["photo", "play", "flick"]


def test_a_flick_no_model_made_is_called_a_flick_where_it_says_it_was_never_generated(
        tmp_path, monkeypatch):
    genau = tmp_path / "videos" / "sample app"
    monkeypatch.setattr(config, "GENAU_DIR", genau)
    monkeypatch.setattr(config, "GENAU_FLICKS_NO_MODEL_MADE",
                        (genau / "flicks" / "2D" / "non_AI", genau / "flicks" / "VR"))

    said = [(workflow.why_it_cannot_be_made_again, workflow.why_it_has_no_settings)
            for workflow in (NonAiWorkflow("sample app flicks"), NonAiWorkflow("sample full"))]

    assert said == [
        ("A Non-AI flick wasn't generated, so it can't be made again",
         "This flick wasn't generated, so it has no generation settings."),
        ("A Non-AI video wasn't generated, so it can't be made again",
         "This video wasn't generated, so it has no generation settings.")]
