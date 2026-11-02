from __future__ import annotations

import json
from pathlib import Path

from origenerator import db_schema
from origenerator import gallery_contract as contract
from origenerator.export_lane import EXPORT_LANES
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.frame_rate import NATIVE_FPS
from tests.children import run_python

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def test_the_tracked_copy_is_what_publishing_writes(tmp_path):
    tracked = contract.contract_path(REPO_ROOT)

    assert (contract.publish(tmp_path).read_text(encoding="utf-8")
            == tracked.read_text(encoding="utf-8"))


def test_every_column_the_document_names_is_one_this_app_writes():
    document = _document()
    declared = {*document["columns"], *document["optional_columns"]}

    assert declared <= set(db_schema.GENERATION_COLUMNS)


def test_every_lane_the_document_names_stamps_the_columns_it_promises():
    stamped = {lane.source_key: {"sent": lane.flag, "unsent": lane.unsent_flag}
               for lane in EXPORT_LANES}

    assert stamped == _document()["lanes"]


def test_a_videos_soundless_copy_is_listed_under_the_role_the_document_promises():
    finished = WORKFLOW_REGISTRY["wan22_flf2v_loop"].extract_output_info({"outputs": {"16": {
        "gifs": [{"filename": "clip_00001-audio.mp4", "subfolder": "video", "type": "output"}]}}})

    assert finished[1]["role"] == _document()["silent_copy_role"]


def test_the_document_promises_the_rate_every_video_is_generated_at():
    assert _document()["generated_fps"] == NATIVE_FPS


def test_the_contract_imports_first_though_the_workflows_it_reads_the_rate_from_import_it():
    imported = run_python(["-c", "import origenerator.gallery_contract"])

    assert imported.returncode == 0, imported.stderr


def test_the_document_names_the_command_that_starts_this_apps_work_while_it_is_closed():
    interpreter, *arguments = _document()["downtime_command"]

    assert interpreter == ".venv/Scripts/python.exe"
    assert arguments == ["-m", "origenerator.downtime"]
