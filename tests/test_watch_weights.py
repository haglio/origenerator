from __future__ import annotations

import json

from origenerator.watch_weights import RecordedWeights


def _library(tmp_path):
    return tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"


def _weighing(records, video_name: str, weight: float) -> None:
    record = (records / "portrait" / video_name).with_suffix(".json")
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"watch": {"weight": weight}}), encoding="utf-8")


def test_a_videos_weight_is_the_one_on_its_record_and_one_where_it_has_none(tmp_path):
    videos, records = _library(tmp_path)
    _weighing(records, "scene one.mp4", 4.0)
    weights = RecordedWeights(records)

    assert weights.of(videos / "portrait" / "scene one.mp4") == 4.0
    assert weights.of(videos / "portrait" / "scene two.mp4") == 1.0


def test_a_weight_is_read_once_and_kept_for_as_long_as_the_app_runs(tmp_path):
    videos, records = _library(tmp_path)
    _weighing(records, "scene one.mp4", 4.0)
    weights = RecordedWeights(records)
    weights.learn([videos / "portrait" / "scene one.mp4"])

    _weighing(records, "scene one.mp4", 0.25)

    assert weights.of(videos / "portrait" / "scene one.mp4") == 4.0


def test_an_image_weighs_one_without_a_record_being_looked_for(tmp_path):
    def never_asked(video, records_folder):
        raise AssertionError("an image has no record to look for")

    weights = RecordedWeights(tmp_path / "videos" / "metadata", read=never_asked)

    assert weights.of(tmp_path / "images" / "scene one.png") == 1.0


def test_with_no_records_folder_every_video_weighs_one(tmp_path):
    assert RecordedWeights(None).of(tmp_path / "scene one.mp4") == 1.0
