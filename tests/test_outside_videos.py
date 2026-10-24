"""The AI videos other sources made, brought in from Evolver's library.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from app_support import haglio_settings
from funestra.video_families import seed_group_key
from PIL import Image

from origenerator import config, evolver_agreement, funscript_backfill, recovery
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
    JOURNAL_NAME,
    Made,
    OutsideVideo,
    Places,
    Record,
    journal_stars,
    outside_videos,
    pick_act,
    places_here,
    record_of,
    rows_bringing_in,
    scan,
)
from origenerator.picture_sorting import pictures_to_sort
from origenerator.provenance import stamp_unstamped
from origenerator.record_repair import repair_records
from origenerator.relocate import relocate_moved_outputs
from origenerator.workflows.outside import outside_workflow


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
    path = tmp_path / "videos" / "metadata" / video.relative_to(tmp_path / "videos" / "videos")
    path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


_VIDEO_BLOCK = {"prompt": "a slow walk on the shore", "seed": "11", "action": "Wave",
                "created": "2025-03-02", "model": "Video Model", "style": "Video Style",
                "resolution": "720p", "aspect_ratio": "9:16", "quality": "High",
                "creativity": "Low", "duration_seconds": 5.0, "orientation": "portrait",
                "type": "image"}
_PICTURE_BLOCK = {"positive_prompt": "a quiet shore", "negative_prompt": "rain", "seed": "22",
                  "created": "2025-03-01", "model": "Picture Model", "style": "Picture Style",
                  "resolution": "1024", "aspect_ratio": "9:16", "quality": "Medium",
                  "creativity": "High"}


def test_a_record_brings_every_field_this_app_has_a_place_for(tmp_path):
    video = _filed(tmp_path / "videos" / "videos" / "outbox", "portrait", "a-site", "c1_topaz.mp4")
    recorded = {"favorite": True, "watch": {"weight": 2.5},
                "provenance": {"upscale": {"app": "an-upscaler"}},
                "video": _VIDEO_BLOCK, "source_image": _PICTURE_BLOCK}
    _record(tmp_path, video, recorded)

    record = record_of(video, tmp_path / "videos" / "metadata")

    assert record == Record(
        video=Made({"positive_prompt": "a slow walk on the shore", "seed": "11",
                    "model": "Video Model", "style": "Video Style",
                    "resolution": "720p", "aspect_ratio": "9:16", "quality": "High",
                    "creativity": "Low"}, created="2025-03-02"),
        picture=Made({"positive_prompt": "a quiet shore", "negative_prompt": "rain",
                      "seed": "22", "model": "Picture Model", "style": "Picture Style",
                      "resolution": "1024", "aspect_ratio": "9:16", "quality": "Medium",
                      "creativity": "High"}, created="2025-03-01"),
        act="Wave", picture_key=seed_group_key(recorded),
        favorite=True)


def test_a_video_made_from_words_alone_has_no_picture_and_a_missing_record_says_nothing(tmp_path):
    video = _filed(tmp_path / "videos" / "videos" / "outbox", "portrait", "a-site", "c1_topaz.mp4")
    unrecorded = _filed(tmp_path / "videos" / "videos" / "outbox", "portrait", "a-site", "c2_topaz.mp4")
    _record(tmp_path, video, {"video": {"model": "Video Model"}})

    assert record_of(video, tmp_path / "videos" / "metadata") == Record(
        video=Made({"model": "Video Model"}))
    assert record_of(unrecorded, tmp_path / "videos" / "metadata") == Record()


def _bring_in(tmp_path, record: Record, *, grab=lambda _path: Image.new("RGB", (64, 96))):
    db = Database(tmp_path / "test.db")
    video = OutsideVideo(_filed(tmp_path / "outbox", "portrait", "a-site", "c1_topaz.mp4"), "a-site")
    db.insert_rows(rows_bringing_in(video, record, frames_dir=tmp_path / "frames",
                                    thumb_dir=tmp_path / "thumbs", grab=grab))
    return db, video


def _by_source(db) -> dict:
    return {row["source"]: row for row in db.list_generations()}


def _videos(db) -> list[dict]:
    return [row for row in db.list_generations() if media_type_of_row(row) == MediaType.VIDEO]


def _frame_of(db, video_row: dict) -> dict:
    return source_image_of(video_row, db.list_generations())


def test_a_video_comes_in_with_its_starting_frame_as_the_picture_it_starts_from(tmp_path):
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
    assert Path(frame_file["path"]).is_file() and Path(shown["thumbnail_path"]).is_file()


_VIDEO_PARAMS = {"positive_prompt": "a slow walk on the shore", "seed": "11",
                 "model": "Video Model", "style": "Video Style", "resolution": "720p",
                 "aspect_ratio": "9:16", "quality": "High", "creativity": "Low"}
_PICTURE_PARAMS = {"positive_prompt": "a quiet shore", "negative_prompt": "rain", "seed": "22",
                   "model": "Picture Model", "style": "Picture Style", "resolution": "1024",
                   "aspect_ratio": "9:16", "quality": "Medium", "creativity": "High"}


def test_a_video_and_the_picture_it_was_made_from_come_in_with_all_their_record_says(tmp_path):
    db, _video = _bring_in(tmp_path, Record(
        video=Made(_VIDEO_PARAMS, created="2025-03-02"),
        picture=Made(_PICTURE_PARAMS, created="2025-03-01"), act="Wave"))

    [shown] = _videos(db)
    picture = _frame_of(db, shown)
    assert {key: value for key, value in json.loads(shown["params_json"]).items()
            if key != "input_image"} == _VIDEO_PARAMS
    assert (shown["positive_prompt"], shown["seed"], shown["recipe_category"],
            shown["created_at"]) == ("a slow walk on the shore", 11, "Wave", "2025-03-02 00:00:00")
    assert json.loads(picture["params_json"]) == _PICTURE_PARAMS
    assert (picture["positive_prompt"], picture["negative_prompt"], picture["seed"],
            picture["created_at"]) == ("a quiet shore", "rain", 22, "2025-03-01 00:00:00")


def test_a_video_made_from_words_alone_keeps_its_starting_frame_out_of_the_toc(tmp_path):
    db, _video = _bring_in(tmp_path, Record())

    assert [media.label for media in build_gallery_tree(db.list_generations())] == ["Videos"]


def test_a_hidden_starting_frame_is_not_on_latest(tmp_path):
    db, _video = _bring_in(tmp_path, Record())

    assert [row["source"] for row in recent_generations(db.list_generations())] == [
        GenerationSource.OUTSIDE]


def test_a_hidden_starting_frame_never_waits_to_be_sorted(tmp_path):
    db, _video = _bring_in(tmp_path, Record())

    assert pictures_to_sort(db.list_generations()) == []


def test_a_video_made_from_a_picture_shows_its_frame_as_that_picture(tmp_path):
    db, _video = _bring_in(tmp_path, Record(picture=Made({"model": "Picture Model",
                                                          "style": "Picture Style"})))

    picture = [row for row in db.list_generations()
               if json.loads(row["output_files"])[0]["filename"].endswith(".jpg")][0]
    assert picture["source"] == GenerationSource.OUTSIDE
    assert json.loads(picture["params_json"]) == {"model": "Picture Model", "style": "Picture Style"}


def test_a_video_whose_first_frame_cannot_be_read_is_left_for_the_next_scan(tmp_path):
    db, _video = _bring_in(tmp_path, Record(), grab=lambda _path: None)

    assert db.list_generations() == []


def _places(tmp_path) -> Places:
    return Places(upscaled_dir=tmp_path / "videos" / "videos" / "outbox",
                  records_folder=tmp_path / "videos" / "metadata",
                  frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                  skip_sources=frozenset({"this-app"}), library_root=tmp_path,
                  journal=tmp_path / "videos" / "journals" / "origenerator.jsonl")


def _still(_path):
    return Image.new("RGB", (64, 96))


def test_a_scan_brings_each_new_video_in_once(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _filed(places.upscaled_dir, "landscape", "b-site", "c1_topaz.mp4")

    assert (scan(db, places, grab=_still), scan(db, places, grab=_still)) == (2, 0)
    assert len(_videos(db)) == 2


def test_a_scan_writes_what_it_brings_in_a_few_videos_at_a_time(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    for name in ("c1_topaz.mp4", "c2_topaz.mp4", "c3_topaz.mp4"):
        _filed(places.upscaled_dir, "portrait", "a-site", name)
    writes, insert = [], db.insert_rows
    db.insert_rows = lambda rows: (writes.append(len(rows)), insert(rows))

    scan(db, places, grab=_still, videos_per_write=2)

    assert writes == [4, 2]


def test_a_scan_stops_at_the_next_video_once_it_is_told_to(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    for name in ("c1_topaz.mp4", "c2_topaz.mp4", "c3_topaz.mp4"):
        _filed(places.upscaled_dir, "portrait", "a-site", name)
    asked = []

    brought_in = scan(db, places, grab=_still,
                      keep_going=lambda: asked.append(True) or len(asked) < 2)

    assert brought_in == 1 == len(_videos(db))


def _deleted(db, row: dict) -> None:
    db.delete_generation(row["prompt_id"])
    db.record_deletion(row["prompt_id"], row, {"moves": [], "subdir": None})


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

    recovery.purge(db, db.get_deletion(shown["prompt_id"]))

    assert scan(db, places, grab=_still) == 0


def test_a_video_made_from_words_alone_takes_its_starting_frame_when_deleted_for_good(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    [shown] = _videos(db)
    frame = _frame_of(db, shown)
    _deleted(db, shown)

    recovery.purge(db, db.get_deletion(shown["prompt_id"]))

    assert db.get_generation(frame["prompt_id"]) is None
    assert not Path(json.loads(frame["output_files"])[0]["path"]).exists()
    assert not Path(frame["thumbnail_path"]).exists()


def test_a_starting_frame_a_video_here_was_made_from_outlives_its_video_deleted_for_good(
        tmp_path):
    _video, shown, frame = _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")
    _made_here_from(db, frame)
    _deleted(db, shown)

    recovery.purge(db, db.get_deletion(shown["prompt_id"]))

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
    (output / "image").mkdir(parents=True)
    (output / "image" / "sdxl_t2i_00001_.png").write_bytes(b"a picture")
    return output


def test_the_launch_repair_keeps_every_video_from_another_source_and_its_frame(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _filed(places.upscaled_dir, "portrait", "b-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    before = db.list_generations()

    repair_records(db, OutputPlaces.in_one_folder(_comfyui_output(tmp_path)))

    assert db.list_generations() == before


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
                                write=lambda path, **_: written.append(path),
                                rewrite=lambda *_args, **_kw: False)

    assert written == []


def test_a_video_from_another_source_is_never_stamped_with_this_apps_recipes(tmp_path):
    _brought_in(tmp_path)
    db = Database(tmp_path / "test.db")

    assert stamp_unstamped(db, history=lambda _workflow: []) == 0
    assert db.completed_without_duration() == []


def test_the_look_reads_this_apps_folders_and_where_evolver_keeps_its_records(
        tmp_path, monkeypatch):
    checkout = tmp_path / "evolver"
    checkout.mkdir()
    (checkout / "evolver_contract.json").write_text(
        json.dumps({"library_record": {"folder": "videos/records"}}), encoding="utf-8")
    monkeypatch.setattr(evolver_agreement, "evolver_checkout", lambda: checkout)
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))

    assert places_here() == Places(
        upscaled_dir=config.EVOLVER_UPSCALED_DIR,
        records_folder=config.LIBRARY_ROOT / "videos" / "records",
        frames_dir=config.STARTING_FRAMES_DIR, thumb_dir=config.THUMB_DIR,
        skip_sources=frozenset({config.EVOLVER_SOURCE, config.GENAU_SOURCE}),
        library_root=config.LIBRARY_ROOT, journal=None)


def test_the_look_journals_where_the_shared_settings_say_the_journals_are(tmp_path, monkeypatch):
    checkout = tmp_path / "evolver"
    checkout.mkdir()
    (checkout / "evolver_contract.json").write_text(
        json.dumps({"library_record": {"folder": "videos/records"}}), encoding="utf-8")
    monkeypatch.setattr(evolver_agreement, "evolver_checkout", lambda: checkout)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"warm_gun_journal_dir": str(tmp_path / "journals")}),
                        encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))

    assert places_here().journal == tmp_path / "journals" / JOURNAL_NAME


def test_a_picture_in_comfyuis_output_named_like_another_sources_video_stays_a_picture(tmp_path):
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


def test_starring_a_video_from_another_source_tells_fun_time_through_the_journal(tmp_path):
    _video, shown, _frame = _brought_in(tmp_path)
    places = _places(tmp_path)

    journal_stars(places, [shown], True, now=lambda: 1_700_000_000.5)

    [line] = places.journal.read_text(encoding="utf-8").splitlines()
    assert json.loads(line) == {"t": 1_700_000_000_500, "event": "favorite",
                                "path": "videos/videos/outbox/portrait/a-site/c1_topaz.mp4"}


def test_picking_an_act_for_a_video_from_another_source_tells_evolver_through_the_journal(
        tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})
    [shown] = _videos(db)
    places = _places(tmp_path)

    pick_act(db, places, shown, "Bow", now=lambda: 1_700_000_000.5)

    [line] = places.journal.read_text(encoding="utf-8").splitlines()
    assert json.loads(line) == {"t": 1_700_000_000_500, "event": "action", "action": "Bow",
                                "path": "videos/videos/outbox/portrait/a-site/c1_topaz.mp4"}


def _two_word_made_videos_one_act_apart(tmp_path) -> tuple[Database, dict]:
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "12", act="Bow")})
    for record in (tmp_path / "videos" / "metadata").rglob("*.json"):
        os.utime(record, (1_700_000_000, 1_700_000_000))
    [picked] = [row for row in _videos(db) if "c1_topaz" in row["output_files"]]
    return db, picked


def test_picking_another_act_for_a_word_made_video_leaves_it_where_it_is(tmp_path):
    db, picked = _two_word_made_videos_one_act_apart(tmp_path)
    named = ItemNames.from_library(db).of(picked["prompt_id"])

    pick_act(db, _places(tmp_path), picked, "Bow", now=lambda: 1_700_000_100)

    assert db.get_generation(picked["prompt_id"])["recipe_category"] == "Bow"
    assert ItemNames.from_library(db).of(picked["prompt_id"]) == named


def test_the_next_look_keeps_a_pick_evolver_has_not_written_into_the_record_yet(tmp_path):
    db, picked = _two_word_made_videos_one_act_apart(tmp_path)
    pick_act(db, _places(tmp_path), picked, "Bow", now=lambda: 1_700_000_100)

    scan(db, _places(tmp_path), grab=_still)

    assert _leaves(db, "Videos") == [["c1_topaz.mp4", "c2_topaz.mp4"]]
    assert db.get_generation(picked["prompt_id"])["recipe_category"] == "Bow"


def test_a_record_written_since_the_pick_is_what_the_next_look_takes(tmp_path):
    db, picked = _two_word_made_videos_one_act_apart(tmp_path)
    pick_act(db, _places(tmp_path), picked, "Bow", now=lambda: 1_700_000_100)
    video = tmp_path / "videos" / "videos" / "outbox" / "portrait" / "a-site" / "c1_topaz.mp4"
    _record(tmp_path, video, _made_from_words("a slow walk on the shore", "11", act="Kneel"))

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(picked["prompt_id"])["recipe_category"] == "Kneel"


def test_a_pick_does_not_keep_a_video_from_taking_its_star_from_the_record(tmp_path):
    db, picked = _two_word_made_videos_one_act_apart(tmp_path)
    pick_act(db, _places(tmp_path), picked, "Bow", now=lambda: 1_700_000_100)
    video = tmp_path / "videos" / "videos" / "outbox" / "portrait" / "a-site" / "c1_topaz.mp4"
    _record(tmp_path, video, {**_made_from_words("a slow walk on the shore", "11", act="Bow"),
                              "favorite": True})
    record = tmp_path / "videos" / "metadata" / "outbox" / "portrait" / "a-site" / "c1_topaz.json"
    os.utime(record, (1_700_000_050, 1_700_000_050))

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(picked["prompt_id"])["starred"] == 1


def test_a_look_takes_each_videos_star_from_its_record(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)

    _record(tmp_path, video, {"favorite": True})
    scan(db, places, grab=_still)

    assert [row["starred"] for row in _videos(db)] == [1]


def test_a_star_set_here_since_its_record_was_written_stands_until_evolver_carries_it(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _record(tmp_path, video, {"favorite": False})
    record = tmp_path / "videos" / "metadata" / "outbox" / "portrait" / "a-site" / "c1_topaz.json"
    os.utime(record, (1_700_000_000, 1_700_000_000))
    scan(db, places, grab=_still)
    [shown] = _videos(db)

    db.set_generation_favorite(shown["prompt_id"], True)
    journal_stars(places, [shown], True, now=lambda: 1_700_000_100)
    scan(db, places, grab=_still)

    assert db.get_generation(shown["prompt_id"])["starred"] == 1


def _source_picture_folders(groups):
    for group in groups:
        if isinstance(group, SourceImageGroup):
            yield group
        yield from _source_picture_folders(child_groups(group))


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

    [folder] = _source_picture_folders(build_gallery_tree(db.list_generations(),
                                                          name_of=names.of))

    assert folder.label == names.of(frame["prompt_id"])
    assert re.fullmatch(r"\S+ \d{3}", folder.label)


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
    for name, record in records.items():
        _record(tmp_path, _filed(places.upscaled_dir, "portrait", "a-site", name), record)
    scan(db, places, grab=_still)
    return db


def _made_from_a_picture(video_prompt: str, picture_prompt: str, picture_seed: str,
                         video_seed: str | None = None) -> dict:
    return {"video": {"prompt": video_prompt, "seed": video_seed or picture_seed,
                      "model": "Video Model"},
            "source_image": {"positive_prompt": picture_prompt, "seed": picture_seed,
                             "model": "Picture Model"}}


def test_videos_made_from_one_picture_that_differ_only_by_seed_share_a_folder(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22", "31"),
        "c2_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22", "32"),
        "c3_topaz.mp4": _made_from_a_picture("turn to the right", "a busy street", "24")})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4", "c2_topaz.mp4"], ["c3_topaz.mp4"]]


def test_videos_made_from_two_pictures_with_one_prompt_are_two_folders(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "23")})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4"], ["c2_topaz.mp4"]]


def _made_from_words(prompt: str, seed: str, act: str = "Wave") -> dict:
    return {"video": {"prompt": prompt, "seed": seed, "action": act, "model": "Video Model"}}


def test_videos_made_from_words_that_differ_only_by_seed_or_act_share_a_folder(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "12"),
        "c3_topaz.mp4": _made_from_words("a slow walk on the shore", "13", act="Bow"),
        "c4_topaz.mp4": _made_from_words("a run in the rain", "14")})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4", "c2_topaz.mp4", "c3_topaz.mp4"],
                                     ["c4_topaz.mp4"]]


def test_videos_whose_records_name_no_prompt_share_one_folder_each_keeping_its_act(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": {"video": {"action": "Wave", "duration_seconds": 5.0}},
        "c2_topaz.mp4": {"video": {"action": "Wave", "orientation": "portrait"}},
        "c3_topaz.mp4": {"video": {"action": "Bow"}}})

    assert _leaves(db, "Videos") == [["c1_topaz.mp4", "c2_topaz.mp4", "c3_topaz.mp4"]]
    assert sorted(row["recipe_category"] for row in _videos(db)) == ["Bow", "Wave", "Wave"]


def _workflow_folders(db, media_label: str) -> list[str]:
    rows = db.list_generations()
    [media] = [group for group in build_gallery_tree(rows, image_index=start_frame_index(rows))
               if group.label == media_label]
    return sorted(group.label for group in child_groups(media))


def test_a_sites_videos_made_from_pictures_and_from_words_are_two_workflows_named_for_each(
        tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})

    assert _workflow_folders(db, "Videos") == ["a-site I2V", "a-site T2V"]


def test_a_site_whose_videos_are_all_made_from_words_keeps_its_own_name(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a run in the rain", "12")})

    assert _workflow_folders(db, "Videos") == ["a-site"]


def test_a_site_whose_videos_are_all_made_from_pictures_names_their_kind(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22")})

    assert _workflow_folders(db, "Videos") == ["a-site I2V"]


def test_a_video_made_from_a_picture_is_filed_under_that_pictures_folder(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_a_picture("turn to the right", "a quiet shore", "22")})
    names, rows = ItemNames.from_library(db), db.list_generations()
    [picture] = _pictures(db)

    [folder] = _source_picture_folders(build_gallery_tree(
        rows, image_index=start_frame_index(rows), name_of=names.of))

    assert folder.label == names.of(picture["prompt_id"])
    assert sorted(len(leaf.rows) for leaf in child_groups(folder)) == [1, 1]


def test_videos_brought_in_under_their_sites_name_move_to_their_kinds_at_the_next_look(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})
    first_preview = sqlite3.connect(tmp_path / "test.db")
    with closing(first_preview), first_preview:
        first_preview.executemany(
            "UPDATE generations SET workflow_name = ? WHERE prompt_id = ?",
            [(outside_workflow("a-site"), video["prompt_id"]) for video in _videos(db)])

    scan(db, _places(tmp_path), grab=_still)

    assert _workflow_folders(db, "Videos") == ["a-site I2V", "a-site T2V"]


def test_a_family_animated_with_two_models_is_a_folder_of_its_own_under_each(tmp_path):
    first, second = (_made_from_a_picture("turn to the left", "a quiet shore", seed)
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

    scan(db, places, grab=_still)

    shown = [row for row in recent_generations(db.list_generations())
             if media_type_of_row(row) == MediaType.VIDEO]
    assert [json.loads(row["output_files"])[0]["filename"] for row in shown] == [
        "c1_topaz.mp4", "c2_topaz.mp4"]
    assert [row["created_at"] for row in shown] == ["2025-01-01 00:00:00", "2025-06-01 00:00:00"]


def test_a_look_brings_a_video_already_brought_in_up_to_its_record(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    scan(db, places, grab=_still)
    _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _PICTURE_BLOCK})

    scan(db, places, grab=_still)

    [shown] = _videos(db)
    picture = _frame_of(db, shown)
    assert (shown["positive_prompt"], shown["seed"], shown["recipe_category"],
            shown["created_at"]) == ("a slow walk on the shore", 11, "Wave", "2025-03-02 00:00:00")
    assert (picture["source"], picture["positive_prompt"], picture["seed"]) == (
        GenerationSource.OUTSIDE, "a quiet shore", 22)


def test_a_look_files_a_picture_brought_in_under_its_videos_workflow_under_its_own(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _PICTURE_BLOCK})
    scan(db, places, grab=_still)
    [picture] = _pictures(db)
    first_preview = sqlite3.connect(tmp_path / "test.db")
    with closing(first_preview), first_preview:
        first_preview.execute("UPDATE generations SET workflow_name = ? WHERE prompt_id = ?",
                              (outside_workflow("a-site"), picture["prompt_id"]))

    scan(db, places, grab=_still)

    assert db.get_generation(picture["prompt_id"])["workflow_name"] == outside_workflow(
        "a-site", MediaType.IMAGE)


def test_a_look_rewrites_no_row_whose_record_is_unchanged(tmp_path):
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    video = _filed(places.upscaled_dir, "portrait", "a-site", "c1_topaz.mp4")
    _record(tmp_path, video, {"video": _VIDEO_BLOCK, "source_image": _PICTURE_BLOCK})
    scan(db, places, grab=_still)
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
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22", "31"),
        "c2_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22", "32"),
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


def test_a_word_made_videos_starting_frame_is_numbered_in_its_videos_family(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_words("a slow walk on the shore", "11"),
        "c2_topaz.mp4": _made_from_words("a run in the rain", "12")})

    names = ItemNames.from_library(db)

    assert [names.of(_frame_of(db, row)["prompt_id"])[-3:] for row in _videos(db)] == ["000", "000"]


def _pictures(db) -> list[dict]:
    return sorted((row for row in db.list_generations()
                   if row["source"] == GenerationSource.OUTSIDE
                   and media_type_of_row(row) == MediaType.IMAGE), key=lambda row: row["id"])


def test_videos_animated_from_one_picture_bring_it_in_once(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_a_picture("turn to the right", "a quiet shore", "22")})

    [picture] = _pictures(db)
    assert {_frame_of(db, row)["prompt_id"] for row in _videos(db)} == {picture["prompt_id"]}


def test_a_video_made_from_a_picture_already_in_points_at_it_at_a_site_of_both_kinds(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})
    places = _places(tmp_path)
    later = _filed(places.upscaled_dir, "portrait", "a-site", "c3_topaz.mp4")
    _record(tmp_path, later, _made_from_a_picture("turn to the right", "a quiet shore", "22"))

    scan(db, places, grab=_still)

    assert len(_pictures(db)) == 1


def test_at_a_site_of_both_kinds_each_video_still_starts_from_its_own_frame(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
        "c2_topaz.mp4": _made_from_words("a slow walk on the shore", "11")})

    started_from = {json.loads(video["output_files"])[0]["filename"]: _frame_of(db, video)["source"]
                    for video in _videos(db)}

    assert started_from == {"c1_topaz.mp4": GenerationSource.OUTSIDE,
                            "c2_topaz.mp4": GenerationSource.STARTING_FRAME}


def test_pictures_whose_records_name_no_seed_are_never_taken_for_one_picture(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", ""),
        "c2_topaz.mp4": _made_from_a_picture("turn to the right", "a quiet shore", "")})

    assert [len(leaf) for leaf in _leaves(db, "Images")] == [2]


def _brought_in_one_by_one(tmp_path, records: dict[str, dict]) -> Database:
    db, places = Database(tmp_path / "test.db"), _places(tmp_path)
    for name, recorded in records.items():
        video = _filed(places.upscaled_dir, "portrait", "a-site", name)
        _record(tmp_path, video, recorded)
        db.insert_rows(rows_bringing_in(
            OutsideVideo(video, "a-site"), record_of(video, places.records_folder),
            frames_dir=places.frames_dir, thumb_dir=places.thumb_dir, grab=_still))
    return db


_ONE_PICTURE_TWICE = {
    "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22"),
    "c2_topaz.mp4": _made_from_a_picture("turn to the right", "a quiet shore", "22")}


def test_a_look_folds_a_picture_brought_in_twice_into_one(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_PICTURE_TWICE)
    first, second = _pictures(db)

    scan(db, _places(tmp_path), grab=_still)

    assert [row["prompt_id"] for row in _pictures(db)] == [first["prompt_id"]]
    assert {_frame_of(db, row)["prompt_id"] for row in _videos(db)} == {first["prompt_id"]}
    assert not Path(json.loads(second["output_files"])[0]["path"]).exists()


def test_a_picture_folded_into_its_twin_hands_it_its_star(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_PICTURE_TWICE)
    first, second = _pictures(db)
    db.set_generation_favorite(second["prompt_id"], True)

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(first["prompt_id"])["starred"] == 1


def test_what_a_picture_shows_said_by_hand_survives_the_next_look(tmp_path):
    db = _brought_in_with_records(tmp_path, {
        "c1_topaz.mp4": _made_from_a_picture("turn to the left", "a quiet shore", "22")})
    [picture] = _pictures(db)
    db.set_picture_state(picture["prompt_id"], "Standing")

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(picture["prompt_id"])["picture_state"] == "Standing"


def test_a_picture_folded_into_its_twin_hands_it_what_it_was_said_to_show(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_PICTURE_TWICE)
    first, second = _pictures(db)
    db.set_picture_state(second["prompt_id"], "Standing")

    scan(db, _places(tmp_path), grab=_still)

    assert db.get_generation(first["prompt_id"])["picture_state"] == "Standing"


def test_a_twin_picture_a_video_here_was_made_from_is_kept(tmp_path):
    db = _brought_in_one_by_one(tmp_path, _ONE_PICTURE_TWICE)
    _first, second = _pictures(db)
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
