from __future__ import annotations

import json

from funestra.video_families import action_group_key, seed_group_key

from origenerator.video_records import VideoRecords, of_this_library


def _library(tmp_path):
    return tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"


def _filing(records, video_name: str, record: dict) -> None:
    filed = (records / "portrait" / video_name).with_suffix(".json")
    filed.parent.mkdir(parents=True, exist_ok=True)
    filed.write_text(json.dumps(record), encoding="utf-8")


def _weighing(records, video_name: str, weight: float) -> None:
    _filing(records, video_name, {"watch": {"weight": weight}})


def test_a_videos_weight_is_the_one_on_its_record_and_one_where_it_has_none(tmp_path):
    videos, records = _library(tmp_path)
    _weighing(records, "scene one.mp4", 4.0)
    weights = VideoRecords(records)

    assert weights.weight_of(videos / "portrait" / "scene one.mp4") == 4.0
    assert weights.weight_of(videos / "portrait" / "scene two.mp4") == 1.0


def test_a_record_is_read_once_and_kept_for_as_long_as_the_app_runs(tmp_path):
    videos, records = _library(tmp_path)
    _weighing(records, "scene one.mp4", 4.0)
    weights = VideoRecords(records)
    weights.learn([videos / "portrait" / "scene one.mp4"])

    _weighing(records, "scene one.mp4", 0.25)

    assert weights.weight_of(videos / "portrait" / "scene one.mp4") == 4.0


def test_an_image_weighs_one_and_joins_no_group_without_a_record_being_looked_for(tmp_path):
    def never_asked(video, records_folder):
        raise AssertionError("an image has no record to look for")

    records = VideoRecords(tmp_path / "videos" / "metadata", read=never_asked)

    assert records.weight_of(tmp_path / "images" / "scene one.png") == 1.0
    assert records.group_of(tmp_path / "images" / "scene one.png", False) is None


def test_with_no_records_folder_every_video_weighs_one_and_joins_no_group(tmp_path):
    assert VideoRecords(None).weight_of(tmp_path / "scene one.mp4") == 1.0
    assert VideoRecords(None).group_of(tmp_path / "scene one.mp4", True) is None


_MADE_FROM_AN_IMAGE = {
    "video": {"prompt": "the alpha move", "model": "Motion A", "action": "alpha", "seed": "1"},
    "source_image": {"positive_prompt": "a lighthouse at dusk", "model": "Model A",
                     "seed": "101"},
}


def test_a_videos_groups_are_the_ones_its_record_gives_it(tmp_path):
    videos, records = _library(tmp_path)
    _filing(records, "scene one.mp4", _MADE_FROM_AN_IMAGE)
    video = videos / "portrait" / "scene one.mp4"

    assert VideoRecords(records).group_of(video, False) == action_group_key(_MADE_FROM_AN_IMAGE)
    assert VideoRecords(records).group_of(video, True) == seed_group_key(_MADE_FROM_AN_IMAGE)[0]


def test_a_video_whose_record_names_no_seed_is_in_no_seed_family(tmp_path):
    videos, records = _library(tmp_path)
    unseeded = {"video": {"prompt": "a boat on a lake", "model": "Motion B", "action": "beta"}}
    _filing(records, "scene one.mp4", unseeded)

    assert VideoRecords(records).group_of(videos / "portrait" / "scene one.mp4", True) is None


def test_the_library_hands_the_slideshow_one_reader_for_weights_and_groups(tmp_path):
    reads = of_this_library()

    assert set(reads) == {"weight_of", "learn_weights", "record_group_of"}
    assert reads["weight_of"].__self__ is reads["record_group_of"].__self__
    assert reads["weight_of"](tmp_path / "scene one.png") == 1.0
