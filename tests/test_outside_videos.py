from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from funestra.video_families import seed_group_and_seed
from PIL import Image

from origenerator import config, funscript_backfill, trash_collection
from origenerator.action_setter import waiting
from origenerator.db import Database
from origenerator.gallery import (
    SourceImageGroup,
    build_gallery_tree,
    child_groups,
    media_type_of_row,
    output_disk_files,
    output_file_reference,
    recent_generations,
    resolve_preview,
    settings_folder_key,
    source_image_of,
    start_frame_index,
)
from origenerator.generation_state import GenerationSource
from origenerator.importer import backfill_shared_thumbnails, merge_video_sidecar_rows
from origenerator.item_names import ItemNames
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import (
    FrameFolders,
    Made,
    OutsideVideo,
    Places,
    Record,
    bring_in_one,
    outside_videos,
    places_here,
    record_from,
    rows_bringing_in,
    scan,
    scan_in_turn,
    take_record,
    turn_at,
)
from origenerator.provenance import stamp_unstamped
from origenerator.relocate import relocate_moved_outputs
from origenerator.thumbnail import animated_thumbnail_path
from origenerator.workflows.outside import outside_workflow
from tests.media_files import write_mp4


def _filed(root, orientation: str, source: str, name: str):
    path = root / orientation / source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really a video")
    return path


def test_the_videos_found_are_the_outbox_videos_this_app_did_not_make(tmp_path):
    found = _filed(tmp_path, "portrait", "a-site", "clip1_topaz.mp4")
    _filed(tmp_path, "landscape", "this-app", "made-here_topaz.mp4")
    _filed(tmp_path, "portrait", "a-site", "half.partial.mp4")
    _filed(tmp_path, "portrait", "a-site", "notes.txt")
    _filed(tmp_path, "portrait", "a-site", "wan22_i2v_00001__topaz.mp4")
    held = [{"prompt_id": "g1", "output_files": json.dumps([{"filename": "wan22_i2v_00001_.mp4"}])}]

    videos = outside_videos(tmp_path, skip_sources={"this-app"}, rows=held, held=set())

    assert videos == [OutsideVideo(path=found, source="a-site")]


def _record(tmp_path, video, record: dict):
    return take_record(Database(tmp_path / "test.db"), video, record, places=_places(tmp_path),
                       grab=_still)


_VIDEO_BLOCK = {"prompt": "a slow walk on the shore", "seed": "11", "action": "Wave",
                "created": "2025-03-02", "model": "Video Model", "style": "Video Style",
                "resolution": "720p", "aspect_ratio": "9:16", "quality": "High",
                "creativity": "Low", "duration_seconds": 5.0, "orientation": "portrait",
                "type": "image"}
_IMAGE_BLOCK = {"positive_prompt": "a quiet shore", "negative_prompt": "rain", "seed": "22",
                  "created": "2025-03-01", "model": "Image Model", "style": "Image Style",
                  "resolution": "1024", "aspect_ratio": "9:16", "quality": "Medium",
                  "creativity": "High"}


def test_a_record_brings_every_field_this_app_has_a_place_for():
    recorded = {"favorite": True, "watch": {"weight": 2.5},
                "provenance": {"upscale": {"app": "an-upscaler"}},
                "video": _VIDEO_BLOCK, "source_image": _IMAGE_BLOCK}

    record = record_from(recorded)

    assert record == Record(
        video=Made({"positive_prompt": "a slow walk on the shore", "seed": "11",
                    "model": "Video Model", "style": "Video Style",
                    "resolution": "720p", "aspect_ratio": "9:16", "quality": "High",
                    "creativity": "Low"}, created="2025-03-02"),
        image=Made({"positive_prompt": "a quiet shore", "negative_prompt": "rain",
                      "seed": "22", "model": "Image Model", "style": "Image Style",
                      "resolution": "1024", "aspect_ratio": "9:16", "quality": "Medium",
                      "creativity": "High"}, created="2025-03-01"),
        action="Wave", image_key=seed_group_and_seed(recorded),
        favorite=True)


def test_a_video_made_from_words_alone_has_no_image_and_an_empty_record_says_nothing():
    assert record_from({"video": {"model": "Video Model"}}) == Record(
        video=Made({"model": "Video Model"}))
    assert record_from({}) == Record()
    assert record_from({"video": "not a block", "source_image": []}) == Record()


def _bring_in(tmp_path, record: Record, *, grab=lambda _path: Image.new("RGB", (64, 96))):
    db = Database(tmp_path / "test.db")
    video = OutsideVideo(_filed(tmp_path / "outbox", "portrait", "a-site", "c1_topaz.mp4"), "a-site")
    db.insert_rows(rows_bringing_in(video, record,
                                    FrameFolders(tmp_path / "frames", tmp_path / "thumbs"),
                                    grab=grab))
    return db, video


def test_a_video_brought_in_has_its_thumbnail_ready_to_animate(tmp_path):
    video = OutsideVideo(write_mp4(tmp_path / "outbox" / "c1_topaz.mp4"), "a-site")

    rows = rows_bringing_in(video, Record(),
                            FrameFolders(tmp_path / "frames", tmp_path / "thumbs"))

    assert animated_thumbnail_path(tmp_path / "thumbs", rows[-1]["prompt_id"]).exists()


def _by_source(db) -> dict:
    return {row["source"]: row for row in db.list_generations()}


def _videos(db) -> list[dict]:
    return [row for row in db.list_generations() if media_type_of_row(row) == MediaType.VIDEO]


def _frame_of(db, video_row: dict) -> dict:
    return source_image_of(video_row, db.list_generations())


def test_a_video_comes_in_with_its_starting_frame_as_the_image_it_starts_from(tmp_path):
    db, video = _bring_in(tmp_path, Record(video=Made({"model": "Video Model",
                                                        "style": "Video Style"}), favorite=True))

    shown = _by_source(db)[GenerationSource.OUTSIDE]
    frame = _frame_of(db, shown)
    params = json.loads(shown["params_json"])
    [file] = json.loads(shown["output_files"])
    [frame_file] = json.loads(frame["output_files"])
    assert (shown["workflow_name"], shown["starred"]) == (outside_workflow("a-site"), 1)
    assert {key: params[key] for key in ("model", "style")} == {"model": "Video Model",
                                                                 "style": "Video Style"}
    assert file == {"filename": "c1_topaz.mp4", "library_path": str(video.path)}
    assert params["input_image"] == frame_file["path"]
    assert Path(frame_file["path"]).is_file()
    assert Path(shown["thumbnail_path"]).is_file()


_VIDEO_PARAMS = {"positive_prompt": "a slow walk on the shore", "seed": "11",
                 "model": "Video Model", "style": "Video Style", "resolution": "720p",
                 "aspect_ratio": "9:16", "quality": "High", "creativity": "Low"}
_IMAGE_PARAMS = {"positive_prompt": "a quiet shore", "negative_prompt": "rain", "seed": "22",
                   "model": "Image Model", "style": "Image Style", "resolution": "1024",
                   "aspect_ratio": "9:16", "quality": "Medium", "creativity": "High"}


def test_a_video_and_the_image_it_was_made_from_come_in_with_all_their_record_says(tmp_path):
    db, _video = _bring_in(tmp_path, Record(
        video=Made(_VIDEO_PARAMS, created="2025-03-02"),
        image=Made(_IMAGE_PARAMS, created="2025-03-01"), action="Wave"))

    [shown] = _videos(db)
    image = _frame_of(db, shown)
    assert {key: value for key, value in json.loads(shown["params_json"]).items()
            if key != "input_image"} == _VIDEO_PARAMS
    assert (shown["positive_prompt"], shown["seed"], shown["action"],
            shown["created_at"]) == ("a slow walk on the shore", 11, "Wave", "2025-03-02 00:00:00")
    assert json.loads(image["params_json"]) == _IMAGE_PARAMS
    assert (image["positive_prompt"], image["negative_prompt"], image["seed"],
            image["created_at"]) == ("a quiet shore", "rain", 22, "2025-03-01 00:00:00")


def test_a_video_made_from_words_alone_keeps_its_starting_frame_out_of_the_toc(tmp_path):
    db, _video = _bring_in(tmp_path, Record())

    assert [media.label for media in build_gallery_tree(db.list_generations())] == ["Videos"]


def test_a_hidden_starting_frame_is_not_on_latest(tmp_path):
    db, _video = _bring_in(tmp_path, Record())

    assert [row["source"] for row in recent_generations(db.list_generations())] == [
        GenerationSource.OUTSIDE]


def test_a_hidden_starting_frame_waits_for_its_actions_only_as_the_video_it_was_taken_from(
        tmp_path):
    db, _video = _bring_in(tmp_path, Record())

    [entry] = waiting(db.list_generations(), MediaType.IMAGE)

    assert (entry.holder["source"], entry.shown["source"]) == (
        GenerationSource.STARTING_FRAME, GenerationSource.OUTSIDE)


def test_a_video_made_from_an_image_shows_its_frame_as_that_image(tmp_path):
    db, _video = _bring_in(tmp_path, Record(image=Made({"model": "Image Model",
                                                          "style": "Image Style"})))

    image = next(row for row in db.list_generations()
             if json.loads(row["output_files"])[0]["filename"].endswith(".jpg"))
    assert image["source"] == GenerationSource.OUTSIDE
    assert json.loads(image["params_json"]) == {"model": "Image Model", "style": "Image Style"}


def test_a_video_whose_first_frame_cannot_be_read_is_left_for_the_next_scan(tmp_path):
    db, _video = _bring_in(tmp_path, Record(), grab=lambda _path: None)

    assert db.list_generations() == []


def _places(tmp_path) -> Places:
    return Places(kino=tmp_path / "videos" / "videos" / "kino",
                  frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                  skip_sources=frozenset({"this-app"}), library_root=tmp_path)


def _still(_path):
    return Image.new("RGB", (64, 96))


def test_a_scan_brings_each_new_video_in_once(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _filed(places.upscaled_dir, "landscape", "b-site", "c1_topaz.mp4")

    assert (scan(db, places, grab=_still), scan(db, places, grab=_still)) == (2, 0)
    assert len(_videos(db)) == 2


def test_a_scan_stands_back_while_another_program_is_bringing_videos_in(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    write_mp4(places.upscaled_dir / "portrait" / "a-site" / "c1_topaz.mp4")

    with turn_at(db).taken():
        during = scan_in_turn(db, places, wait_s=0)
    after = scan_in_turn(db, places)

    assert (during, after) == (0, 1)
    assert len(_videos(db)) == 1


def test_a_scan_writes_what_it_brings_in_a_few_videos_at_a_time(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    for name in ("c1_topaz.mp4", "c2_topaz.mp4", "c3_topaz.mp4"):
        _filed(places.upscaled_dir, "portrait", "a-site", name)
    writes, insert = [], db.insert_rows
    db.insert_rows = lambda rows: (writes.append(len(rows)), insert(rows))

    scan(db, places, grab=_still, videos_per_write=2)

    assert writes == [4, 2]


def test_one_video_kino_plays_is_brought_in_by_itself(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    one = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _filed(places.upscaled_dir, "portrait", "a-site", "c2_topaz.mp4")

    brought = bring_in_one(db, one, places=places, grab=_still)

    assert brought is True
    assert [json.loads(row["output_files"])[0]["library_path"] for row in _videos(db)] == [str(one)]


def test_one_video_of_this_apps_own_source_is_brought_in_when_asked_for_by_itself(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    own = _filed(places.upscaled_dir, "landscape", "this-app", "c3_topaz.mp4")

    assert bring_in_one(db, own, places=places, grab=_still) is True
    assert len(_videos(db)) == 1


def test_a_video_outside_kinos_upscales_is_never_brought_in_by_itself(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    elsewhere = _filed(tmp_path / "elsewhere", "portrait", "a-site", "c4_topaz.mp4")

    assert bring_in_one(db, elsewhere, places=places, grab=_still) is False
    assert _videos(db) == []


def test_a_video_whose_frame_cannot_be_read_is_not_brought_in_by_itself(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    one = _filed(places.upscaled_dir, "portrait", "a-site", "c5_topaz.mp4")

    assert bring_in_one(db, one, places=places, grab=lambda _path: None) is False


def test_no_places_means_no_video_is_brought_in_by_itself(tmp_path):
    db = Database(tmp_path / "test.db")

    assert bring_in_one(db, tmp_path / "c6_topaz.mp4", places=None) is False


def _deleted(db, row: dict) -> None:

    db.delete_generation(row["prompt_id"])
    db.record_trashed(row["prompt_id"], row, {"moves": [], "subdir": None})


def test_a_video_waiting_in_the_trash_is_not_brought_in_again(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    [shown] = _videos(db)

    _deleted(db, shown)

    assert scan(db, places, grab=_still) == 0


def test_a_video_deleted_for_good_is_not_brought_in_again(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    [shown] = _videos(db)
    _deleted(db, shown)

    trash_collection.purge(db, db.get_trashed(shown["prompt_id"]))

    assert scan(db, places, grab=_still) == 0


def test_a_video_made_from_words_alone_takes_its_starting_frame_when_deleted_for_good(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    [shown] = _videos(db)
    frame = _frame_of(db, shown)
    _deleted(db, shown)

    trash_collection.purge(db, db.get_trashed(shown["prompt_id"]))

    assert db.get_generation(frame["prompt_id"]) is None
    assert not Path(json.loads(frame["output_files"])[0]["path"]).exists()
    assert not Path(frame["thumbnail_path"]).exists()


def test_a_starting_frame_a_video_here_was_made_from_outlives_its_video_deleted_for_good(
        tmp_path):
    _video, shown, frame = _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")
    _made_here_from(db, frame)
    _deleted(db, shown)

    trash_collection.purge(db, db.get_trashed(shown["prompt_id"]))

    assert db.get_generation(frame["prompt_id"]) is not None
    assert Path(json.loads(frame["output_files"])[0]["path"]).exists()


def _brought_in(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    shown = _by_source(db)[GenerationSource.OUTSIDE]
    return video, shown, _frame_of(db, shown)


def test_a_video_from_another_source_plays_from_its_place_in_the_library(tmp_path):
    video, shown, _frame = _brought_in(tmp_path)

    assert resolve_preview(shown, OutputPlaces.in_one_folder(tmp_path / "comfyui output")) == (video, MediaType.VIDEO)


def test_a_run_started_from_a_starting_frame_loads_the_frame_from_where_it_is_kept(tmp_path):
    _video, _shown, frame = _brought_in(tmp_path)
    [file] = json.loads(frame["output_files"])

    assert output_file_reference([file]) == file["path"]


def test_deleting_a_video_from_another_source_takes_none_of_the_librarys_files(tmp_path):
    _video, shown, frame = _brought_in(tmp_path)

    assert output_disk_files(shown, OutputPlaces.in_one_folder(tmp_path / "comfyui output")) == []
    assert output_disk_files(frame, OutputPlaces.in_one_folder(tmp_path / "comfyui output")) == [
        Path(json.loads(frame["output_files"])[0]["path"])]


def _comfyui_output(tmp_path) -> Path:
    output = tmp_path / "comfyui output"
    output.mkdir(parents=True)
    return output


def test_a_video_from_another_source_is_never_followed_into_comfyuis_output(tmp_path):
    _video, shown, _frame = _brought_in(tmp_path)
    output = _comfyui_output(tmp_path)
    (output / "video").mkdir()
    (output / "video" / "c1_topaz.mp4").write_bytes(b"a namesake")
    db = Database(tmp_path / "test.db")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output)) == 0
    assert db.get_generation(shown["prompt_id"])["output_files"] == shown["output_files"]


def test_the_funscript_sweep_writes_nothing_for_a_video_from_another_source(tmp_path):
    _brought_in(tmp_path)
    written = []

    funscript_backfill.backfill(Database(tmp_path / "test.db"), OutputPlaces.in_one_folder(_comfyui_output(tmp_path)),
                                steps=funscript_backfill.Steps(write=lambda path, **_: written.append(path),
                                                rewrite=lambda *_args, **_kw: False))

    assert written == []


def test_a_video_from_another_source_is_never_stamped_with_this_apps_workflows(tmp_path):
    _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")

    assert stamp_unstamped(db, history=lambda _workflow: []) == 0
    assert db.completed_without_duration() == []


def test_the_look_reads_this_apps_folders():
    assert places_here() == Places(
        kino=config.KINO_DIR,
        frames_dir=config.STARTING_FRAMES_DIR, thumb_dir=config.THUMB_DIR,
        skip_sources=frozenset({config.EVOLVER_SOURCE, config.GENAU_SOURCE}),
        library_root=config.LIBRARY_ROOT)


def test_an_image_in_comfyuis_output_named_like_another_sources_video_stays_an_image(tmp_path):
    _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")
    db.insert_rows([{"prompt_id": "pic", "source": GenerationSource.IMPORTED,
                     "workflow_name": "unknown", "workflow_version": "imported",
                     "status": "completed", "params_json": "{}", "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": "c1_topaz.png", "subfolder": ""}])}])

    assert merge_video_sidecar_rows(db) == 0


def test_a_video_from_another_source_whose_thumbnail_went_missing_gets_one_back(tmp_path):
    _video, shown, _frame = _brought_in(tmp_path)
    Path(shown["thumbnail_path"]).unlink()

    repaired = backfill_shared_thumbnails(Database(tmp_path / "test.db"),
                                          OutputPlaces.in_one_folder(_comfyui_output(tmp_path)), tmp_path / "thumbs")

    assert repaired == 1


def _source_image_folders(groups):
    for group in groups:
        if isinstance(group, SourceImageGroup):
            yield group
        yield from _source_image_folders(child_groups(group))


def _made_here_from(db, frame: dict) -> None:
    db.insert_rows([{
        "prompt_id": "made-from-the-frame", "workflow_name": "wan22_i2v",
        "workflow_version": "1", "workflow_json": "{}", "status": "completed",
        "params_json": json.dumps({"input_image": output_file_reference(
            json.loads(frame["output_files"]))}),
        "output_files": json.dumps([{"filename": "wan22_i2v_00001_.mp4", "subfolder": "video"}]),
    }])


def test_a_video_made_from_a_hidden_starting_frame_is_filed_under_the_frames_item_name(tmp_path):
    _video, _shown, frame = _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")
    _made_here_from(db, frame)
    names = ItemNames.from_library(db)

    [folder] = _source_image_folders(build_gallery_tree(db.list_generations(),
                                                        name_of=names.of))

    assert folder.label == names.of(frame["prompt_id"])
    assert re.fullmatch(r"\S+ \d{3}", folder.label)


def test_a_hidden_starting_frame_goes_by_its_videos_name(tmp_path):
    _video, shown, frame = _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")
    _made_here_from(db, frame)

    names = ItemNames.from_library(db)

    [folder] = _source_image_folders(build_gallery_tree(db.list_generations(),
                                                        name_of=names.of))
    assert folder.label == names.of(frame["prompt_id"]) == names.of(shown["prompt_id"])
    assert names.prompt_id_of(folder.label) == shown["prompt_id"]


def _leaves(db, media_label: str) -> list[list[str]]:
    rows = db.list_generations()
    [media] = [group for group in build_gallery_tree(rows, image_index=start_frame_index(rows))
               if group.label == media_label]

    def walk(group):
        if not child_groups(group):
            return [sorted(json.loads(row["output_files"])[0]["filename"] for row in group.rows)]
        return [leaf for child in child_groups(group) for leaf in walk(child)]

    return sorted(walk(media))


def _brought_in_with_records(tmp_path, records: dict[str, dict]) -> Database:
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    filed = {name: _filed(places.upscaled_dir, "portrait", "a-site", name) for name in records}
    scan(db, places, grab=_still)
    for name, record in records.items():
        _record(tmp_path, filed[name], record)
    return db


def _made_from_an_image(video_prompt: str, image_prompt: str, image_seed: str,
                        video_seed: str | None = None) -> dict:
    return {"video": {"prompt": video_prompt, "seed": video_seed or image_seed,
                      "model": "Video Model"},
            "source_image": {"positive_prompt": image_prompt, "seed": image_seed,
                             "model": "Image Model"}}


def test_videos_made_from_one_image_that_differ_only_by_seed_share_a_folder(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22", "31"),
        "c2_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22", "32"),
        "c3_topaz.mp4": _made_from_an_image("turn to the right", "a busy street", "24")})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4", "c2_topaz.mp4"], ["c3_topaz.mp4"]]


def test_videos_made_from_two_images_with_one_prompt_are_two_folders(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "23")})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4"], ["c2_topaz.mp4"]]


def _made_from_words(prompt: str, seed: str, action: str = "Wave") -> dict:
    return {"video": {"prompt": prompt, "seed": seed, "action": action, "model": "Video Model"}}


def test_videos_made_from_words_that_differ_only_by_seed_or_action_share_a_folder(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "12"),
        "c3_topaz.mp4": _made_from_words("a slow walk on the shore", "13", action="Bow"),
        "c4_topaz.mp4": _made_from_words("a run in the rain", "14")})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4", "c2_topaz.mp4", "c3_topaz.mp4"],
                                     ["c4_topaz.mp4"]]


def test_each_video_whose_record_names_no_prompt_is_a_folder_of_its_own_keeping_its_action(
        tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": {"video": {"action": "Wave", "duration_seconds": 5.0}},
        "c2_topaz.mp4": {"video": {"action": "Wave", "orientation": "portrait"}},
        "c3_topaz.mp4": {"video": {"action": "Bow"}}})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4"], ["c2_topaz.mp4"], ["c3_topaz.mp4"]]
    assert sorted(row["action"] for row in _videos(db)) == ["Bow", "Wave", "Wave"]


def _workflow_folders(db, media_label: str) -> list[str]:
    rows = db.list_generations()
    [media] = [group for group in build_gallery_tree(rows, image_index=start_frame_index(rows))
               if group.label == media_label]
    return sorted(group.label for group in child_groups(media))


def test_a_sites_videos_made_from_images_and_from_words_are_two_workflows_named_for_each(
        tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})

    assert _workflow_folders(db, "Videos") == ["I2V a-site", "T2V a-site"]


def test_a_site_whose_videos_are_all_made_from_words_keeps_its_own_name(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a run in the rain", "12")})

    assert _workflow_folders(db, "Videos") == ["a-site"]


def test_a_site_whose_videos_are_all_made_from_images_names_their_kind(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22")})

    assert _workflow_folders(db, "Videos") == ["I2V a-site"]


def test_a_video_made_from_an_image_is_filed_under_that_images_folder(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_an_image("turn to the right", "a quiet shore", "22")})
    names, rows = ItemNames.from_library(db), db.list_generations()
    [image] = _images(db)

    [folder] = _source_image_folders(build_gallery_tree(
        rows, image_index=start_frame_index(rows), name_of=names.of))

    assert folder.label == names.of(image["prompt_id"])
    assert sorted(len(leaf.rows) for leaf in child_groups(folder)) == [1, 1]


def test_videos_brought_in_under_their_sites_name_move_to_their_kinds_at_the_next_look(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})
    first_preview = sqlite3.connect(tmp_path / "test.db")
    with closing(first_preview), first_preview:
        first_preview.executemany(
            "UPDATE generations SET workflow_name = ? WHERE prompt_id = ?",
            [(outside_workflow("a-site"), video["prompt_id"]) for video in _videos(db)])

    scan(db, _places(tmp_path), grab=_still)

    assert _workflow_folders(db, "Videos") == ["I2V a-site", "T2V a-site"]


def test_a_family_animated_with_two_models_is_a_folder_of_its_own_under_each(tmp_path):
    first, second = (_made_from_an_image("turn to the left", "a quiet shore", seed)
                     for seed in ("22", "23"))
    second["video"]["model"] = "Another Video Model"
    db = _brought_in_with_records(tmp_path, {"c1_topaz.mp4": first, "c2_topaz.mp4": second})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4"], ["c2_topaz.mp4"]]
    assert len({settings_folder_key(row) for row in _videos(db)}) == 2


def test_videos_from_other_sites_are_on_latest_by_when_they_came_not_when_they_were_made(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    for name, made, filed in (("c1_topaz.mp4", "2025-01-01", 1_790_000_000),
                              ("c2_topaz.mp4", "2025-06-01", 1_780_000_000)):
        video = _filed(places.upscaled_dir, "portrait", "a-site", name)
        os.utime(video, (filed, filed))
        _record(tmp_path, video, {"video": {"prompt": "a slow walk on the shore", "seed": "11",
                                            "created": made}})

    shown = [row for row in recent_generations(db.list_generations())
             if media_type_of_row(row) == MediaType.VIDEO]
    assert [json.loads(row["output_files"])[0]["filename"] for row in shown] == [
        "c1_topaz.mp4", "c2_topaz.mp4"]
    assert [row["created_at"] for row in shown] == ["2025-01-01 00:00:00", "2025-06-01 00:00:00"]


def test_a_record_brings_a_video_already_brought_in_up_to_it(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)

    assert _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _IMAGE_BLOCK}) is True

    [shown] = _videos(db)
    image = _frame_of(db, shown)
    assert (shown["positive_prompt"], shown["seed"], shown["action"],
            shown["created_at"]) == ("a slow walk on the shore", 11, "Wave", "2025-03-02 00:00:00")
    assert (image["source"], image["positive_prompt"], image["seed"]) == (
        GenerationSource.OUTSIDE, "a quiet shore", 22)


def test_a_look_files_an_image_brought_in_under_its_videos_workflow_under_its_own(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _IMAGE_BLOCK})
    [image] = _images(db)
    first_preview = sqlite3.connect(tmp_path / "test.db")
    with closing(first_preview), first_preview:
        first_preview.execute("UPDATE generations SET workflow_name = ? WHERE prompt_id = ?",
                              (outside_workflow("a-site"), image["prompt_id"]))

    scan(db, places, grab=_still)

    assert db.get_generation(image["prompt_id"])["workflow_name"] == outside_workflow(
        "a-site", MediaType.IMAGE)


def test_an_outside_image_keeps_the_workflow_name_its_row_and_folder_keys_were_saved_under():
    assert outside_workflow("a-site", MediaType.IMAGE) == "outside picture:a-site"


def test_a_look_rewrites_no_row_whose_record_is_unchanged(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _IMAGE_BLOCK})
    written, write = [], db.set_recorded_fields
    db.set_recorded_fields = lambda rows: (written.extend(rows), write(rows))

    scan(db, places, grab=_still)

    assert written == []


def test_items_numbered_in_a_folder_the_look_no_longer_files_them_in_are_numbered_afresh(
        tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a run in the rain", "12")})
    db.record_item_numbers({row["prompt_id"]: ("an old folder", 40 + number)
                            for number, row in enumerate(db.list_generations())})

    scan(db, _places(tmp_path), grab=_still)

    names = ItemNames.from_library(db)
    assert [names.of(row["prompt_id"])[-3:] for row in db.list_generations()] == ["000"] * 4


def test_videos_moved_to_their_kinds_folder_are_numbered_afresh_in_it(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22", "31"),
        "c2_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22", "32"),
        "c3_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})
    first_preview = sqlite3.connect(tmp_path / "test.db")
    with closing(first_preview), first_preview:
        first_preview.executemany(
            "UPDATE generations SET workflow_name = ? WHERE prompt_id = ?",
            [(outside_workflow("a-site"), video["prompt_id"]) for video in _videos(db)])
    db.record_item_numbers({video["prompt_id"]: ("an old folder", 40 + number)
                            for number, video in enumerate(_videos(db))})

    scan(db, _places(tmp_path), grab=_still)

    names = ItemNames.from_library(db)
    assert sorted(names.of(video["prompt_id"])[-3:] for video in _videos(db)) == [
        "000", "000", "001"]


def _images(db) -> list[dict]:
    return sorted((row for row in db.list_generations()
                   if row["source"] == GenerationSource.OUTSIDE
                   and media_type_of_row(row) == MediaType.IMAGE), key=lambda row: row["id"])


def test_videos_animated_from_one_image_bring_it_in_once(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_an_image("turn to the right", "a quiet shore", "22")})

    [image] = _images(db)
    assert {_frame_of(db, row)["prompt_id"] for row in _videos(db)} == {image["prompt_id"]}


def test_a_video_made_from_an_image_already_in_points_at_it_at_a_site_of_both_kinds(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})
    places = _places(tmp_path)
    later = _filed(places.upscaled_dir, "portrait", "a-site", "c3_topaz.mp4")

    assert _record(tmp_path, later, _made_from_an_image("turn to the right", "a quiet shore", "22"))

    assert len(_images(db)) == 1


def test_at_a_site_of_both_kinds_each_video_still_starts_from_its_own_frame(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})

    started_from = {json.loads(video["output_files"])[0]["filename"]: _frame_of(db, video)["source"]
                    for video in _videos(db)}

    assert started_from == {"c1_topaz.mp4": GenerationSource.OUTSIDE,
                            "c2_topaz.mp4": GenerationSource.STARTING_FRAME}


def test_images_whose_records_name_no_seed_are_never_taken_for_one_image(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", ""),
        "c2_topaz.mp4": _made_from_an_image("turn to the right", "a quiet shore", "")})

    assert [len(leaf) for leaf in _leaves(db, "Images")] == [2]


def _brought_in_one_by_one(tmp_path, records: dict[str, dict]) -> Database:
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    for name, recorded in records.items():
        video = _filed(places.upscaled_dir, "portrait", "a-site", name)
        db.insert_rows(rows_bringing_in(
            OutsideVideo(video, "a-site"), record_from(recorded),
            FrameFolders(places.frames_dir, places.thumb_dir), grab=_still))
    return db


_ONE_IMAGE_TWICE = {
    "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22"),
    "c2_topaz.mp4": _made_from_an_image("turn to the right", "a quiet shore", "22")}


def test_a_look_folds_an_image_brought_in_twice_into_one(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_IMAGE_TWICE)
    first, second = _images(db)

    scan(db, _places(tmp_path), grab=_still)

    assert [row["prompt_id"] for row in _images(db)] == [first["prompt_id"]]
    assert {_frame_of(db, row)["prompt_id"] for row in _videos(db)} == {first["prompt_id"]}
    assert not Path(json.loads(second["output_files"])[0]["path"]).exists()


def test_an_image_folded_into_its_twin_hands_it_its_star(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_IMAGE_TWICE)
    first, second = _images(db)
    db.set_generation_favorite(second["prompt_id"], True)

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(first["prompt_id"])["starred"] == 1


def test_what_an_image_shows_said_by_hand_survives_the_next_look(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_an_image("turn to the left", "a quiet shore", "22")})
    [image] = _images(db)
    db.set_image_state(image["prompt_id"], "Standing")

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(image["prompt_id"])["image_state"] == "Standing"


def test_an_image_folded_into_its_twin_hands_it_what_it_was_said_to_show(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_IMAGE_TWICE)
    first, second = _images(db)
    db.set_image_state(second["prompt_id"], "Standing")

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(first["prompt_id"])["image_state"] == "Standing"


def test_a_twin_image_a_video_here_was_made_from_is_kept(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_IMAGE_TWICE)
    _first, second = _images(db)
    _made_here_from(db, second)

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(second["prompt_id"]) is not None


def _outside_video(prompt_id: str, **params) -> dict:
    return {
        "prompt_id": prompt_id,
        "source": GenerationSource.OUTSIDE,
        "workflow_name": outside_workflow("a-site"),
        "workflow_version": "outside",
        "status": "completed",
        "params_json": json.dumps(params),
        "output_files": json.dumps([{"filename": f"{prompt_id}_topaz.mp4"}]),
    }


def test_a_video_from_another_source_is_filed_under_the_source_its_model_and_its_style():
    [videos] = build_gallery_tree([_outside_video("v1", model="Model One", style="Style One")])

    [workflow] = videos.children
    [model] = workflow.children
    [lora] = model.children
    assert (workflow.label, model.label, lora.label) == ("a-site", "Model One", "Style One")


def test_a_source_named_like_one_of_this_apps_workflows_is_still_a_folder_of_its_own():
    video = _outside_video("v1", model="Model One")
    video["workflow_name"] = outside_workflow("sdxl_t2i")
    made_here = {"prompt_id": "p1", "workflow_name": "sdxl_t2i", "status": "completed",
                 "params_json": "{}", "output_files": json.dumps([{"filename": "p1.mp4"}])}

    [videos] = build_gallery_tree([video, made_here])

    assert len(videos.children) == 2


def test_a_record_of_a_video_that_has_no_row_brings_it_in_with_what_the_record_says(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")

    assert _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _IMAGE_BLOCK}) is True

    [shown] = _videos(db)
    assert (shown["positive_prompt"], shown["action"]) == ("a slow walk on the shore", "Wave")
    assert _frame_of(db, shown)["source"] == GenerationSource.OUTSIDE


def test_a_record_of_a_video_outside_kinos_upscales_with_no_row_brings_nothing_in(tmp_path):
    db = Database(tmp_path / "test.db")
    elsewhere = _filed(tmp_path / "elsewhere", "portrait", "a-site", "c4_topaz.mp4")

    assert _record(tmp_path, elsewhere, {"video": _VIDEO_BLOCK}) is False
    assert _videos(db) == []


def test_a_record_keeps_the_action_picked_here_and_fills_in_one_where_none_was_picked(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": {"video": {"prompt": "a run in the rain"}}})
    picked, unpicked = sorted(_videos(db), key=lambda row: row["output_files"])
    db.set_action(picked["prompt_id"], "Bow")
    places = _places(tmp_path)

    for name in ("c1_topaz.mp4", "c2_topaz.mp4"):
        _record(tmp_path, places.upscaled_dir / "portrait" / "a-site" / name,
                _made_from_words("a slow walk on the shore", "11", action="Kneel"))

    assert [db.get_generation(row["prompt_id"])["action"] for row in (picked, unpicked)] == [
        "Bow", "Kneel"]


def test_a_record_leaves_the_star_set_here_alone(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    [shown] = _videos(db)
    db.set_generation_favorite(shown["prompt_id"], True)

    _record(tmp_path, video, {"favorite": False, "video": _VIDEO_BLOCK})

    assert db.get_generation(shown["prompt_id"])["starred"] == 1


def test_a_record_keeps_the_page_a_video_came_from_and_its_upscale_on_its_row(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    upscale = {"app": "an-upscaler", "model": "made-up"}

    _record(tmp_path, video, {"video": _VIDEO_BLOCK, "web_url": "https://example.com/watch/1",
                              "provenance": {"upscale": upscale}})

    [shown] = _videos(db)
    assert (shown["web_url"], json.loads(shown["upscale_provenance"])) == (
        "https://example.com/watch/1", upscale)


def test_a_scan_brings_a_new_upscale_in_with_no_record_at_all(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    beside = tmp_path / "videos" / "metadata" / "kino" / "portrait" / "a-site" / "c1_topaz.json"
    beside.parent.mkdir(parents=True)
    beside.write_text(json.dumps({"favorite": True, "video": _VIDEO_BLOCK}), encoding="utf-8")

    scan(db, places, grab=_still)

    [shown] = _videos(db)
    assert (shown["starred"], shown["positive_prompt"], shown["action"]) == (0, None, None)


def test_a_record_waits_its_turn_while_another_program_is_bringing_videos_in(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")

    with turn_at(db).taken():
        taken = take_record(db, video, {"video": _VIDEO_BLOCK}, places=places, grab=_still)

    assert (taken, _videos(db)) == (False, [])


def test_a_record_of_a_video_this_app_made_keeps_only_its_page_and_its_upscale(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    db.insert_rows([{"prompt_id": "made-1", "workflow_name": "wan22_i2v", "workflow_version": "1",
                     "workflow_json": "{}", "status": "completed",
                     "params_json": json.dumps({"seed": 5}),
                     "output_files": json.dumps([{"filename": "wan22_i2v_00001_.mp4",
                                                  "subfolder": "video"}])}])
    copy = _filed(places.upscaled_dir, "portrait", "this-app", "wan22_i2v_00001__topaz.mp4")

    assert take_record(db, copy, {"video": _VIDEO_BLOCK, "web_url": "https://example.com/watch/2"},
                       places=places, grab=_still) is True

    made = db.get_generation("made-1")
    assert (json.loads(made["params_json"]), made["action"], made["web_url"]) == (
        {"seed": 5}, None, "https://example.com/watch/2")
