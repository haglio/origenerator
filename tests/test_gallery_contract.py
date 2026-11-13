from __future__ import annotations

import json
from pathlib import Path

from app_support.gallery_records import RECORD_COLUMNS

from origenerator import config, db_schema
from origenerator import gallery_contract as contract
from origenerator.export_lane import EXPORT_LANES
from origenerator.media import MediaType
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.frame_rate import NATIVE_FPS
from origenerator.workflows.outside import VideoKind, outside_workflow
from tests.children import run_python

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def test_the_tracked_copy_is_what_publishing_writes(tmp_path):
    tracked = contract.contract_path(REPO_ROOT)

    assert (contract.publish(tmp_path).read_text(encoding="utf-8")
            == tracked.read_text(encoding="utf-8")), (
        "run origenerator.gallery_contract.publish(): Evolver cannot import this app's code, "
        "so the document is how the promise reaches it, and a copy that has drifted tells it "
        "something untrue")


def test_the_document_never_names_the_folder_a_lane_arrives_under():
    assert config.GENAU_SOURCE not in contract.published_text(), (
        "that folder's name is the library's own vocabulary, which no tracked file may hold")


def test_every_column_the_document_names_is_one_this_app_writes():
    document = _document()
    declared = {*document["columns"], *document["optional_columns"]}

    assert declared <= set(db_schema.GENERATION_COLUMNS), (
        "a rename the document does not carry leaves Evolver reading every row as never sent, "
        "with no other test in either app failing")


def test_the_document_names_every_column_the_familys_record_builder_reads():
    document = _document()

    assert set(RECORD_COLUMNS) <= {*document["columns"], *document["optional_columns"]}


def test_a_column_added_since_the_table_first_shipped_is_one_a_reader_must_ask_for():
    added = set(db_schema.ADDED_COLUMNS["generations"])

    assert not added & set(contract.COLUMNS), (
        "a gallery older than a column lacks it, and selecting it there raises")
    assert set(contract.OPTIONAL_COLUMNS) <= added


def test_every_lane_the_document_names_stamps_the_columns_it_promises():
    stamped = {lane.source_key: {"sent": lane.flag, "unsent": lane.unsent_flag}
               for lane in EXPORT_LANES}

    assert stamped == _document()["lanes"], (
        "Evolver deletes its copies of a row whose withdrawal stamp is set, "
        "and a lane stamping other columns than the document's is a send Evolver never sees")


def test_a_videos_soundless_copy_is_listed_under_the_role_the_document_promises():
    finished = WORKFLOW_REGISTRY["wan22_flf2v_loop"].extract_output_info({"outputs": {"16": {
        "gifs": [{"filename": "clip_00001-audio.mp4", "subfolder": "video", "type": "output"}]}}})

    assert finished[1]["role"] == _document()["silent_copy_role"]


def test_the_document_promises_the_rate_every_video_is_generated_at():
    assert _document()["generated_fps"] == NATIVE_FPS, (
        "Evolver gives Topaz only the frames the model generated: "
        "every M-th frame of a video saved at M times this rate")


def test_the_document_promises_the_rate_each_video_workflow_generates_at():
    assert _document()["generated_fps_by_workflow"] == {
        name: wf.native_fps for name, wf in WORKFLOW_REGISTRY.items()
        if wf.output_type == MediaType.VIDEO}, (
        "a MiniMax H3 video is generated at 24 frames a second where WAN's are at 16, so Evolver "
        "reads the rate of the workflow that made the video")
    assert _document()["generated_fps_by_workflow"]["minimax_h3_i2v"] == 24.0


def test_the_contract_imports_first_though_the_workflows_it_reads_the_rate_from_import_it():
    imported = run_python(["-c", "import origenerator.gallery_contract"])

    assert imported.returncode == 0, imported.stderr


def test_the_document_names_the_command_that_starts_this_apps_work_while_it_is_closed():
    interpreter, *arguments = _document()["downtime_command"]

    assert interpreter == ".venv/Scripts/python.exe"
    assert arguments == ["-m", "origenerator.downtime"]


def test_a_reader_taking_the_first_model_key_present_gets_the_workflows_own_first_model():
    for name, workflow in WORKFLOW_REGISTRY.items():
        recorded = [key for key in workflow.model_keys if key in contract.PARAMS_MODEL_KEYS]
        if not recorded:
            continue
        read = next(key for key in contract.PARAMS_MODEL_KEYS if key in recorded)

        assert read == recorded[0], name


def test_the_start_frame_key_is_the_one_every_image_to_video_workflow_records():
    animating = [wf for wf in WORKFLOW_REGISTRY.values() if wf.starts_from_an_image()]

    assert animating
    assert all(contract.PARAMS_INPUT_IMAGE_KEY in wf.default_params() for wf in animating)


def test_the_document_names_the_workflow_name_each_kind_of_outside_row_starts_with():
    prefixes = _document()["outside_workflow_prefixes"]

    assert {kind: prefix + "a-site" for kind, prefix in prefixes.items()} == {
        "video": outside_workflow("a-site"),
        "image_to_video": outside_workflow("a-site", MediaType.VIDEO, VideoKind.IMAGE_TO_VIDEO),
        "text_to_video": outside_workflow("a-site", MediaType.VIDEO, VideoKind.TEXT_TO_VIDEO),
        "image": outside_workflow("a-site", MediaType.IMAGE)}
