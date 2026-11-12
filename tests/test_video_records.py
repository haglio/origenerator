from __future__ import annotations

import json

from funestra.video_families import action_group_key, seed_group_and_seed

from origenerator.db import Database
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.gui.slideshow_wiring import DirectorSources
from origenerator.video_records import GalleryRecords, VideoRecords, of_this_library


def _gallery(tmp_path):
    return Database(tmp_path / "gallery.db"), tmp_path / "videos" / "videos" / "portrait"


def _outside(db, prompt_id: str, file, *, params: dict, **fields) -> None:
    db.insert_rows([{"prompt_id": prompt_id, "source": GenerationSource.OUTSIDE,
                     "workflow_name": "outside:Example Site", "workflow_version": "outside",
                     "status": GenerationStatus.COMPLETED, "params_json": json.dumps(params),
                     "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": file.name,
                                                  "library_path": str(file)}]),
                     **fields}])


def _filing(db, videos, video_name: str, *, video: dict | None = None,
            source_image: dict | None = None, **fields):
    video = video or {}
    params = {"positive_prompt": video.get("prompt"), "model": video.get("model"),
              "seed": video.get("seed")}
    if source_image is not None:
        frame = videos.parent / "frames" / f"{video_name}.jpg"
        _outside(db, f"frame of {video_name}", frame, params=source_image)
        params["input_image"] = str(frame)
    _outside(db, video_name, videos / video_name,
             params={key: value for key, value in params.items() if value is not None},
             recipe_category=video.get("action"),
             combined_labels=json.dumps(video["labels"]) if "labels" in video else None,
             **fields)
    return videos / video_name


def _records(db) -> VideoRecords:
    return VideoRecords(GalleryRecords(db))


def test_a_videos_weight_is_the_one_its_watch_counts_give_and_one_where_it_has_none(tmp_path):
    db, videos = _gallery(tmp_path)
    _filing(db, videos, "scene one.mp4", watch_completions=6)
    weights = _records(db)

    assert weights.weight_of(videos / "scene one.mp4") == 4.0
    assert weights.weight_of(videos / "scene two.mp4") == 1.0


def test_a_record_is_read_once_and_kept_for_as_long_as_the_app_runs(tmp_path):
    db, videos = _gallery(tmp_path)
    _filing(db, videos, "scene one.mp4", watch_completions=6)
    weights = _records(db)
    weights.learn([videos / "scene one.mp4"])

    db.set_watch_counts("scene one.mp4", {"skips": 6})

    assert weights.weight_of(videos / "scene one.mp4") == 4.0


def test_an_image_weighs_one_and_joins_no_group_without_a_record_being_looked_for(tmp_path):
    def never_asked(video):
        raise AssertionError("an image has no record to look for")

    records = VideoRecords(never_asked)

    assert records.weight_of(tmp_path / "images" / "scene one.png") == 1.0
    assert records.group_of(tmp_path / "images" / "scene one.png", False) is None


def test_a_video_with_no_row_weighs_one_and_joins_no_group(tmp_path):
    db, videos = _gallery(tmp_path)

    assert _records(db).weight_of(videos / "scene one.mp4") == 1.0
    assert _records(db).group_of(videos / "scene one.mp4", True) is None


_MADE_FROM_AN_IMAGE = {
    "video": {"prompt": "the alpha move", "model": "Motion A", "action": "alpha", "seed": "1"},
    "source_image": {"positive_prompt": "a lighthouse at dusk", "model": "Model A",
                     "seed": "101"},
}


def test_a_videos_groups_are_the_ones_its_row_and_its_start_image_give_it(tmp_path):
    db, videos = _gallery(tmp_path)
    video = _filing(db, videos, "scene one.mp4", **_MADE_FROM_AN_IMAGE)

    assert _records(db).group_of(video, False) == action_group_key(_MADE_FROM_AN_IMAGE)
    assert _records(db).group_of(video, True) == seed_group_and_seed(_MADE_FROM_AN_IMAGE)[0]


def test_a_video_whose_row_names_no_seed_is_in_no_seed_group(tmp_path):
    db, videos = _gallery(tmp_path)
    video = _filing(db, videos, "scene one.mp4",
                    video={"prompt": "a boat on a lake", "model": "Motion B", "action": "beta"})

    assert _records(db).group_of(video, True) is None


def _made_from(image_seed: str, action: str) -> dict:
    return {"video": {"prompt": f"the {action} move", "model": "Motion A", "action": action,
                      "labels": [action], "seed": "1"},
            "source_image": {"positive_prompt": "a lighthouse at dusk", "model": "Model A",
                             "seed": image_seed}}


def test_a_video_loops_with_the_videos_learned_beside_it_that_its_row_groups_it_with(tmp_path):
    db, videos = _gallery(tmp_path)
    filed = {"one alpha.mp4": _made_from("101", "alpha"), "one beta.mp4": _made_from("101", "beta"),
             "two alpha.mp4": _made_from("202", "alpha"), "two beta.mp4": _made_from("202", "beta")}
    paths = {name: _filing(db, videos, name, **made) for name, made in filed.items()}
    library = _records(db)
    library.learn(paths.values())

    loops = library.loops_of(paths["one alpha.mp4"])

    assert (loops.actions, loops.seeds) == ((str(paths["one beta.mp4"]),),
                                            (str(paths["two alpha.mp4"]),))


def test_more_seeds_of_a_video_are_the_ones_of_its_action_from_the_most_similar_settings(tmp_path):
    db, videos = _gallery(tmp_path)

    def made_with(prompt: str, action: str) -> dict:
        return {"video": {"prompt": prompt, "model": "Motion A", "action": action,
                          "labels": [action], "seed": "1"}}

    filed = {"here.mp4": made_with("a lighthouse, dusk, calm sea", "alpha"),
             "near.mp4": made_with("a lighthouse, dusk, rough sea", "alpha"),
             "another action.mp4": made_with("a lighthouse, dusk, calm sea", "beta")}
    paths = {name: _filing(db, videos, name, **made) for name, made in filed.items()}
    library = _records(db)
    library.learn(paths.values())

    assert library.loops_of(paths["here.mp4"]).more_seeds == (str(paths["near.mp4"]),)


def test_the_library_hands_the_slideshow_one_reader_for_weights_and_groups(tmp_path):
    db, _videos = _gallery(tmp_path)
    reads = of_this_library(db)

    assert set(reads) == {"weight_of", "learn_weights", "record_group_of", "record_loops_of"}
    assert reads["weight_of"].__self__ is reads["record_group_of"].__self__
    assert reads["weight_of"](tmp_path / "scene one.png") == 1.0


def test_the_director_weighs_videos_from_the_gallery_it_is_handed(tmp_path):
    db, videos = _gallery(tmp_path)
    _filing(db, videos, "scene one.mp4", watch_completions=6)

    sources = DirectorSources.of_this_library(db=db, jobs=None, names=None,
                                              library=lambda: None, listing=lambda: None)

    assert sources.weight_of(videos / "scene one.mp4") == 4.0


_WORDS_VIDEO = {"prompt": "a lighthouse in words", "model": "Motion W", "seed": "7"}
_FRAME = "frame-one.png"


def _frame(db, prompt_id: str, *files: str, source=GenerationSource.STARTING_FRAME, **fields):
    db.insert_rows([{"prompt_id": prompt_id, "source": source, "workflow_name": "outside picture:Example Site",
                     "workflow_version": "outside", "status": GenerationStatus.COMPLETED,
                     "params_json": "{}", "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": name} for name in files]), **fields}])


def _made_here_from(db, frame_file: str) -> str:
    db.insert_rows([{"prompt_id": "made-1", "workflow_name": "wan22_i2v", "workflow_version": "v1",
                     "status": GenerationStatus.COMPLETED, "workflow_json": "{}",
                     "params_json": json.dumps({"input_image": frame_file}),
                     "output_files": json.dumps([{"filename": "wan22_i2v_00001_.mp4",
                                                  "subfolder": "video"}])}])
    return "wan22_i2v_00001__topaz.mp4"


def _words_video_from(db, videos, frame_file: str, *, video=_WORDS_VIDEO):
    _outside(db, "words-1", videos / "words one.mp4",
             params={"positive_prompt": video.get("prompt"), "model": video.get("model"),
                     "seed": video.get("seed"), "input_image": frame_file})


def test_a_video_made_from_a_text_to_video_videos_frame_names_the_video_it_was_taken_from(tmp_path):
    db, videos = _gallery(tmp_path)
    _frame(db, "frame-1", _FRAME, positive_prompt="the words of the frame")
    _words_video_from(db, videos, _FRAME)

    record = GalleryRecords(db)(videos / _made_here_from(db, _FRAME))

    assert record["source_image"]["frame_of_video"] == _WORDS_VIDEO
    assert record["source_image"]["positive_prompt"] == "the words of the frame"
    assert action_group_key(record) == action_group_key({"video": _WORDS_VIDEO})


def test_it_finds_the_text_to_video_video_through_any_file_of_the_frame(tmp_path):
    db, videos = _gallery(tmp_path)
    _frame(db, "frame-1", _FRAME, "frame-one-enhanced.png", positive_prompt="the words of the frame")
    _words_video_from(db, videos, _FRAME)

    record = GalleryRecords(db)(videos / _made_here_from(db, "frame-one-enhanced.png"))

    assert record["source_image"]["frame_of_video"] == _WORDS_VIDEO


def test_a_video_made_from_an_image_names_no_video(tmp_path):
    db, videos = _gallery(tmp_path)
    _frame(db, "image-1", _FRAME, source=GenerationSource.OUTSIDE, positive_prompt="an image")
    _words_video_from(db, videos, _FRAME)

    record = GalleryRecords(db)(videos / _made_here_from(db, _FRAME))

    assert "frame_of_video" not in record["source_image"]


def test_a_video_whose_frame_was_taken_from_a_video_with_no_words_names_no_video(tmp_path):
    db, videos = _gallery(tmp_path)
    _frame(db, "frame-1", _FRAME, positive_prompt="the words of the frame")
    _words_video_from(db, videos, _FRAME, video={})

    record = GalleryRecords(db)(videos / _made_here_from(db, _FRAME))

    assert "frame_of_video" not in record["source_image"]
