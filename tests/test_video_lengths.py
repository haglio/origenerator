from __future__ import annotations

import json

import pytest

from origenerator import video_lengths
from origenerator.completion import mark_generation_completed
from origenerator.db import NewGeneration
from origenerator.generation_state import GenerationStatus
from origenerator.media import video_header
from origenerator.output_places import OutputPlaces
from tests.media_files import write_mp4


def _added(db, prompt_id, files, *, status=GenerationStatus.COMPLETED):
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="made_up",
                                       workflow_version="v001", params_json="{}",
                                       workflow_json="{}"))
    db.update_generation(prompt_id, status=status, output_files=json.dumps(files))


def _video(tmp_path, name, seconds):
    path = write_mp4(tmp_path / f"{name}.mp4", seconds=seconds)
    return [{"filename": path.name, "library_path": str(path)}]


@pytest.fixture
def places(tmp_path):
    return OutputPlaces.in_one_folder(tmp_path / "made-up library")


def test_a_finished_video_keeps_how_long_it_runs(db, tmp_path):
    _added(db, "v1", [], status=GenerationStatus.RUNNING)

    mark_generation_completed(db, "v1", _video(tmp_path, "video one", 2.0), None, 30.0)

    assert db.get_generation("v1")["video_seconds"] == pytest.approx(2.0)


def test_recording_measures_each_finished_video_that_has_no_length(db, tmp_path, places):
    _added(db, "unmeasured", _video(tmp_path, "video one", 1.0))
    _added(db, "measured", _video(tmp_path, "video two", 1.0))
    db.set_library_record("measured", video_seconds=9.0, video_frames=270)
    _added(db, "image", [{"filename": "made-up.png", "library_path": str(tmp_path / "x.png")}])
    _added(db, "running", _video(tmp_path, "video three", 1.0), status=GenerationStatus.RUNNING)

    recorded = video_lengths.record_video_lengths(db, places)

    seconds = {row["prompt_id"]: row["video_seconds"] for row in db.list_generations()}
    assert (recorded, seconds) == (1, {"unmeasured": pytest.approx(1.0), "measured": 9.0,
                                       "image": None, "running": None})


def test_a_video_whose_file_is_gone_is_left_unmeasured(db, tmp_path, places):
    _added(db, "gone", [{"filename": "gone.mp4", "library_path": str(tmp_path / "gone.mp4")}])

    assert video_lengths.record_video_lengths(db, places) == 0


def test_recording_looks_for_no_file_of_an_image(db, tmp_path, places, monkeypatch):
    _added(db, "image", [{"filename": "made-up.png", "library_path": str(tmp_path / "x.png")}])
    looked_for = []
    monkeypatch.setattr(video_lengths.gallery, "video_file_of",
                        lambda row, _places: looked_for.append(row["prompt_id"]))

    video_lengths.record_video_lengths(db, places)

    assert looked_for == [], (
        "the library holds thousands of images, and looking each one's file up on every launch "
        "took over a minute")


def test_a_finished_video_keeps_how_many_frames_its_file_holds(db, tmp_path):
    _added(db, "v1", [], status=GenerationStatus.RUNNING)

    mark_generation_completed(db, "v1", _video(tmp_path, "video one", 2.0), None, 30.0)

    kept = db.get_generation("v1")
    assert kept["video_frames"] > 1
    assert kept["video_frames"] / kept["video_seconds"] == pytest.approx(
        video_header(tmp_path / "video one.mp4").fps)


def test_recording_counts_the_frames_of_a_video_measured_before_frames_were_kept(
        db, tmp_path, places):
    _added(db, "timed", _video(tmp_path, "video one", 1.0))
    db.set_library_record("timed", video_seconds=9.0)

    recorded = video_lengths.record_video_lengths(db, places)

    kept = db.get_generation("timed")
    assert (recorded, kept["video_seconds"], kept["video_frames"]) == (
        1, 9.0, round(video_header(tmp_path / "video one.mp4").frames))
