from __future__ import annotations

import json

from origenerator import config
from origenerator.config import OUTPUT_PLACES
from origenerator.generation_metadata import created_item, file_item, metadata_facts
from origenerator.output_places import OutputPlaces
from origenerator.provenance import BASIS, WORKFLOW, WORKFLOW_VERSION


def _row(**overrides):
    row = {
        "status": "completed",
        "source": "generated",
        "created_at": "2026-01-01",
        "workflow_name": "wan22_i2v",
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "params_json": json.dumps({"positive_prompt": "a cat", "seed": 7}),
        "output_files": json.dumps([{"filename": "clip.mp4", "subfolder": "video"}]),
    }
    row.update(overrides)
    return row


def _image_row(**overrides):
    return _row(**{
        "workflow_name": "sdxl_t2i",
        "output_files": json.dumps([{"filename": "out.png", "subfolder": ""}]),
        **overrides,
    })


def _file(**overrides):
    return {"filename": "clip.mp4", "subfolder": "video", **overrides}


def test_an_items_name_is_what_its_copy_button_copies_and_its_video_is_left_to_its_versions():
    items = metadata_facts(_row(), name="AB12CD34 007").items
    assert [(item.label, item.value, item.copy) for item in items] == [
        ("Name", "AB12CD34 007", "AB12CD34 007")]


def test_a_file_no_version_lists_comes_before_its_date():
    row = _row(created_at="2026-07-01", output_files=json.dumps([
        {"filename": "a.mp4", "subfolder": "video"}, {"filename": "b.mp4", "subfolder": "video"}]))
    items = metadata_facts(row).items
    assert [(item.label, item.value) for item in items] == [
        ("File", "video/b.mp4"), ("Created", "2026-07-01")]


def test_file_shows_the_subfolder_path_but_copies_just_the_filename():
    item = file_item(_file(filename="clip_00001.mp4"))
    assert item.value == "video/clip_00001.mp4"
    assert item.copy == "clip_00001.mp4"


def test_every_output_file_past_the_video_gets_its_own_row():
    row = _row(output_files=json.dumps([
        {"filename": "a.mp4", "subfolder": ""}, {"filename": "b.mp4", "subfolder": ""},
        {"filename": "c.mp4", "subfolder": ""},
    ]))
    files = [i.value for i in metadata_facts(row).items
             if i.label == "File"]
    assert files == ["b.mp4", "c.mp4"]


def test_a_video_evolver_upscaled_lists_its_file_with_its_versions_instead(tmp_path):
    assert metadata_facts(_row(), upscale=tmp_path / "clip_topaz.mp4") is None


def test_file_item_reveals_the_absolute_output_path():
    assert file_item(_file()).reveal == str(OUTPUT_PLACES.folder("video") / "clip.mp4")


def test_file_item_reveals_a_deleted_items_file_where_it_now_sits():
    item = file_item(_file(path=r"C:\state\trash\abc\0_clip.mp4"))
    assert item.reveal == r"C:\state\trash\abc\0_clip.mp4"


def test_a_deleted_items_file_line_leads_with_its_days_in_the_trash():
    item = file_item(_file(), held_days=3)
    assert item.value == "(3 days in trash) video/clip.mp4", (
        "the File line is where the user learns what a file is, and for a deleted one "
        "how long it has sat in the Trash is part of that")
    assert item.copy == "clip.mp4"


def test_one_day_in_the_trash_reads_as_one_day():
    assert file_item(_file(), held_days=1).value.startswith("(1 day in trash)")


def test_an_item_trashed_today_says_so_rather_than_counting_zero():
    assert file_item(_file(), held_days=0).value == "(deleted today) video/clip.mp4"


def test_a_live_items_file_line_says_nothing_about_the_trash():
    assert file_item(_file()).value == "video/clip.mp4"


def test_created_row_carries_no_reveal_path():
    created = created_item(_file(), "2026-01-01")
    assert created.label == "Created"
    assert created.reveal is None


def _stamped(workflow="wan22_i2v", version="v007", basis="recorded", **block):
    return json.dumps({WORKFLOW: workflow, WORKFLOW_VERSION: version,
                       "app_commit": "1a2b3c4d5e6f7a8b", "app_dirty": False,
                       BASIS: basis, **block})


def test_the_block_ends_with_the_workflow_version_and_the_app_build_that_ran_it():
    item = metadata_facts(_row(provenance=_stamped())).items[-1]

    assert (item.label, item.value) == ("Workflow version", "v007 (app build 1a2b3c4)")


def test_an_image_with_a_stamp_shows_a_block_of_just_its_workflow_version():
    row = _image_row(provenance=_stamped(workflow="sdxl_t2i", version="v004"))

    assert [(item.label, item.value) for item in metadata_facts(row).items] == [
        ("Workflow version", "v004 (app build 1a2b3c4)")]


def test_a_version_worked_out_from_the_files_date_says_so():
    row = _row(provenance=_stamped(version="v004", app_commit=None, app_dirty=None,
                                   basis="file_date"))

    assert metadata_facts(row).items[-1].value == "v004 (going by the file's date)"


def test_a_block_that_could_not_work_out_a_version_says_unknown():
    row = _row(provenance=_stamped(version=None, app_commit=None, app_dirty=None,
                                   basis=None))

    assert metadata_facts(row).items[-1].value == "unknown"


def test_a_version_recorded_before_builds_were_noted_shows_just_the_version():
    row = _row(provenance=_stamped(version="v002", app_commit=None, app_dirty=None))

    assert metadata_facts(row).items[-1].value == "v002"


def test_a_build_that_carried_uncommitted_edits_says_so():
    row = _row(provenance=_stamped(app_dirty=True))

    assert metadata_facts(row).items[-1].value == (
        "v007 (app build 1a2b3c4, plus uncommitted edits)")


def test_an_item_from_a_workflow_the_app_no_longer_has_names_no_workflow_version():
    row = _row(workflow_name="wan21_ati_i2v", provenance=_stamped(workflow="wan21_ati_i2v"))

    assert metadata_facts(row) is None


def test_a_passthrough_param_does_not_grow_a_second_block():
    row = _row(params_json=json.dumps({"vae": "x.safetensors"}))
    section = metadata_facts(row, name="AB12CD34 007")
    assert section.title == "Metadata"
    assert [item.label for item in section.items] == ["Name"], (
        "the settings, shown or carried along unshown, live in the form")


def test_an_images_block_leaves_its_file_to_the_version_list():
    section = metadata_facts(_image_row(), name="AB12CD34 007")
    assert [item.label for item in section.items] == ["Name"]


def test_a_batch_still_lists_the_siblings_no_version_claims():
    row = _image_row(output_files=json.dumps([
        {"filename": "a.png", "subfolder": ""},
        {"filename": "b.png", "subfolder": ""},
        {"filename": "c.png", "subfolder": ""},
    ]))
    files = [i.value for i in metadata_facts(row).items
             if i.label == "File"]
    assert files == ["b.png", "c.png"]


def test_a_files_row_can_be_pointed_at_a_different_output_folder(tmp_path):
    item = file_item({"filename": "alpha_00001_.png", "subfolder": "image"},
                     places=OutputPlaces.in_one_folder(tmp_path / "elsewhere"))

    assert item.reveal == str(tmp_path / "elsewhere" / "image" / "alpha_00001_.png"), (
        "the folder is an argument, as it is for its neighbors, so the signature shows the "
        "disk is read and no test has to patch a module to point it elsewhere")


def test_created_reads_the_file_in_the_folder_it_is_given(tmp_path):
    written = tmp_path / "elsewhere" / "image"
    written.mkdir(parents=True)
    (written / "alpha_00001_.png").write_bytes(b"an image")

    item = created_item({"filename": "alpha_00001_.png", "subfolder": "image"},
                        "never", places=OutputPlaces.in_one_folder(tmp_path / "elsewhere"))

    assert item.value != "never", (
        "an image's versions were made at different moments, so each is dated from its own file, "
        "which one date on the row could not do")


def test_the_output_folder_still_defaults_to_the_configured_one(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path / "configured"))

    item = file_item({"filename": "alpha_00001_.png", "subfolder": "image"})

    assert item.reveal == str(tmp_path / "configured" / "image" / "alpha_00001_.png")


def test_a_file_gone_from_disk_is_created_when_the_row_says(tmp_path):
    item = created_item({"filename": "missing.png", "subfolder": "image"}, "2026-01-02 03:04:05",
                        places=OutputPlaces.in_one_folder(tmp_path / "nowhere"))

    assert item.value == "2026-01-02 03:04:05"


def _frames(items):
    return [(item.label, item.value) for item in items if item.label in ("Frames from model", "Total frames")]


def test_a_video_says_how_many_frames_the_model_made_and_how_many_the_file_holds():
    row = _row(workflow_name="wan22_flf2v_loop",
               params_json=json.dumps({"frame_count": 17, "frame_rate": 112.0}))

    assert _frames(metadata_facts(row).items) == [
        ("Frames from model", "17"), ("Total frames", "113")]


def test_a_video_whose_settings_never_said_its_length_shows_no_frame_counts():
    row = _row(workflow_name="wan22_flf2v_loop", params_json=json.dumps({"frame_rate": 112.0}))

    assert metadata_facts(row) is None


def test_a_video_made_at_another_rate_counts_its_filled_in_frames_from_that_rate():
    row = _row(workflow_name="minimax_h3_i2v",
               params_json=json.dumps({"frame_count": 124, "frame_rate": 48.0}))

    items = metadata_facts(row).items
    assert _frames(items) == [("Frames from model", "124"), ("Total frames", "247")]
    (tip,) = {item.tooltip for item in items if item.label == "Total frames"}
    assert "MiniMax H3" in tip
    assert "24 frames a second" in tip
    assert "WAN" not in tip
