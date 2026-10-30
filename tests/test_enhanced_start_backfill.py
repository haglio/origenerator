"""Making a kept video again from its image's enhancement, when it started from the plain image.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from origenerator import downtime, gallery, recovery
from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.enhanced_start_backfill import (
    Evolver,
    backfill_params_for,
    cancel_backfill,
    fold_completed_backfill,
    hand_the_remakes_down_again,
    pay_the_owed_favorites,
    queue_backfill,
    videos_to_backfill,
)
from origenerator.evolver_export import EvolverInbox
from origenerator.export_lane import EXPORT_LANES, KINO
from origenerator.funscript import funscript_path_for
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_state import GenerationSource
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.job_queue import JobQueue
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import record_of
from origenerator.trash import Trash
from tests.comfyui_folders import SUITE_FOLDERS
from tests.story_voices import voices_asked_for


def _file(name, subfolder):
    return {"filename": name, "subfolder": subfolder, "type": "output"}


def _plain(prompt_id):
    return _file(f"{prompt_id}_00001_.png", "image")


def _enhancement(prompt_id):
    return _file(f"image_enhance_{prompt_id}_.png", "image")


def _image(db, prompt_id, *, enhanced=False):
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v1",
                         params_json=json.dumps({"seed": 1}), workflow_json="{}")
    files = [_enhancement(prompt_id), _plain(prompt_id)] if enhanced else [_plain(prompt_id)]
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(files))
    if enhanced:
        db.update_generation(prompt_id, original_files=json.dumps([_plain(prompt_id)]))
    return db.get_generation(prompt_id)


def _reference(file):
    return f"{file['subfolder']}/{file['filename']} [output]"


def _video(db, prompt_id, *, made_from, starred=False, start=None, source="generated",
           workflow="wan22_i2v", lines=None):
    params = {"input_image": _reference(start or _plain(made_from)),
              "noise_seed": 7, "audio_seed": 8, **({"scene_lines": lines} if lines else {})}
    db.insert_generation(prompt_id=prompt_id, workflow_name=workflow, workflow_version="v1",
                         params_json=json.dumps(params), workflow_json="{}", source=source)
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([_file(f"{prompt_id}_00001.mp4", "video")]))
    if starred:
        db.set_generation_favorite(prompt_id, True)
    return db.get_generation(prompt_id)


def _backfilled(db):
    return [(video["prompt_id"], image["prompt_id"])
            for video, image in videos_to_backfill(db.list_generations())]


def test_a_starred_video_from_an_image_never_enhanced_is_backfilled(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True)

    assert _backfilled(db) == [("video", "image")]


def test_a_video_from_the_plain_original_of_an_image_enhanced_since_is_backfilled(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))

    assert _backfilled(db) == [("video", "image")]


def test_a_video_sent_to_kino_or_genau_is_backfilled_and_one_taken_back_is_not(tmp_path):
    db = Database(tmp_path / "t.db")
    for prompt_id in ("kino", "genau", "taken back", "never kept"):
        _image(db, f"{prompt_id} image")
        _video(db, prompt_id, made_from=f"{prompt_id} image")
    db.mark_evolver_exported("kino")
    db.mark_genau_exported("genau")
    db.mark_evolver_exported("taken back")
    db.mark_evolver_unsent("taken back")

    assert sorted(video for video, _image in _backfilled(db)) == ["genau", "kino"]


def test_an_experiment_waiting_for_its_verdict_is_left_alone_and_one_kept_is_backfilled(tmp_path):
    db = Database(tmp_path / "t.db")
    for prompt_id in ("waiting", "kept"):
        _image(db, f"{prompt_id} image")
        _video(db, prompt_id, made_from=f"{prompt_id} image", starred=True,
               source="experiment")
    db.set_experiment_verdict("kept", "up")

    assert [video for video, _image in _backfilled(db)] == ["kept"]


def test_a_video_from_an_image_listing_its_own_file_as_its_original_is_not_remade_from_it(
        tmp_path):
    # Such an image has no enhanced file to start from, so each remake started from
    # the file the last one did, and one video was remade at every closing.
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    db.update_generation("image", original_files=json.dumps([_plain("image")]))
    _video(db, "video", made_from="image", starred=True)

    assert _backfilled(db) == []


def test_a_video_already_on_its_way_through_the_backfill_is_not_queued_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True)
    db.insert_generation(prompt_id="on its way", workflow_name="wan22_i2v", workflow_version="v1",
                         params_json="{}", workflow_json="{}", source=GenerationSource.BACKFILL)
    db.set_backfill_of("on its way", "video")

    assert _backfilled(db) == []


@pytest.mark.parametrize("source", ["backfill", "outside", "stroke_trim", "base_render"])
def test_a_video_this_app_did_not_make_as_a_generation_is_left_alone(tmp_path, source):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True, source=source)

    assert _backfilled(db) == []


def test_a_video_whose_workflow_this_app_cannot_run_is_left_alone(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True, workflow="a workflow from elsewhere")

    assert _backfilled(db) == []


def test_an_imported_video_is_backfilled_like_a_generated_one(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True, source="imported")

    assert _backfilled(db) == [("video", "image")]


def _namesake(db, prompt_id, filename):
    db.insert_generation(prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version="v1",
                         params_json="{}", workflow_json="{}")
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([_file(filename, "video")]))


def test_a_sent_video_sharing_its_name_with_another_is_left_alone(tmp_path):
    # Evolver takes a send back by the video's name, so taking this one's back
    # would take the namesake's copies with it.
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image")
    db.mark_evolver_exported("video")
    _namesake(db, "namesake", "video_00001.webm")

    assert _backfilled(db) == []


def test_a_video_only_starred_is_backfilled_whatever_shares_its_name(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True)
    _namesake(db, "namesake", "video_00001.webm")

    assert _backfilled(db) == [("video", "image")]


def test_a_backfill_run_uses_the_old_settings_and_seeds_from_the_images_enhancement(tmp_path):
    db = Database(tmp_path / "t.db")
    image = _image(db, "image", enhanced=True)
    video = _video(db, "video", made_from="image", starred=True, start=_plain("image"))

    params = backfill_params_for(video, image)

    assert params["input_image"] == _reference(_enhancement("image"))
    assert (params["noise_seed"], params["audio_seed"]) == (7, 8)


class _Absence:
    """What the work left for while the app is closed hands ComfyUI, recorded."""

    def __init__(self):
        self.enhanced, self.launched = [], []

    def launch(self, video, workflow, params):
        self.launched.append((video["prompt_id"], workflow.name, params))
        return f"backfill of {video['prompt_id']}"

    def enhance(self, images):
        self.enhanced.extend(image["prompt_id"] for image in images)
        return len(images)

    def queue(self, db, **budget):
        return queue_backfill(db.list_generations(), self.launch, enhance=self.enhance, **budget)


def test_an_image_never_enhanced_is_enhanced_first_and_its_video_waits(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True)
    absence = _Absence()

    assert absence.queue(db) == 1

    assert (absence.enhanced, absence.launched) == (["image"], [])


def test_an_image_two_kept_videos_started_from_is_enhanced_once(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "one", made_from="image", starred=True)
    _video(db, "two", made_from="image", starred=True)
    absence = _Absence()

    absence.queue(db)

    assert absence.enhanced == ["image"]


def test_a_video_whose_image_was_enhanced_since_is_backfilled_with_the_same_workflow(tmp_path):
    db = Database(tmp_path / "t.db")
    image = _image(db, "image", enhanced=True)
    video = _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    absence = _Absence()

    assert absence.queue(db) == 1

    assert absence.launched == [("video", "wan22_i2v", backfill_params_for(video, image))]
    assert absence.enhanced == []


def test_an_absence_takes_as_many_backfill_runs_as_its_minutes_hold_and_always_one(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(3):
        _image(db, f"image {i}", enhanced=True)
        _video(db, f"video {i}", made_from=f"image {i}", starred=True,
               start=_plain(f"image {i}"))
        db.update_generation(f"video {i}", duration_seconds=600)

    assert _Absence().queue(db, budget_minutes=25) == 2
    assert _Absence().queue(db, budget_minutes=1) == 1


def test_the_work_left_for_while_closed_backfills_videos_and_enhances_their_images(qtbot, tmp_path,
                                                                          monkeypatch):
    # Everything but the socket is the real path, as for the base re-renders.
    monkeypatch.setattr(GenerationJob, "start", lambda self, submit=None: None)
    db = Database(tmp_path / "t.db")
    _image(db, "plain image")
    _video(db, "from plain", made_from="plain image", starred=True)
    _image(db, "enhanced image", enhanced=True)
    _video(db, "from enhanced", made_from="enhanced image", starred=True,
           start=_plain("enhanced image"))
    jobs = JobQueue(db, ComfyUIClient(folders=SUITE_FOLDERS))

    assert downtime.queue_the_backfill(jobs, db, db.list_generations(),
                                      enhance_settings=gallery.EnhanceSettings.parse(None)) == 2

    queued = [row for row in db.list_generations() if row["source"] == GenerationSource.BACKFILL]
    assert sorted((row["workflow_name"], row["backfill_of"] or row["enhance_of"])
                  for row in queued) == [("image_enhance", "plain image"),
                                         ("wan22_i2v", "from enhanced")]


def _comfyui_taking_everything():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-X")
    client.fetch_history = MagicMock(return_value={})
    return client


def test_a_story_the_backfill_remakes_while_the_app_is_closed_is_spoken_before_comfyui_gets_it(
        qtbot, tmp_path, monkeypatch):
    # The program that hands ComfyUI the backfill ends once it has, so a voice it
    # left speaking answered nobody, and the story never reached ComfyUI.
    voices = voices_asked_for(monkeypatch)
    client = _comfyui_taking_everything()
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "story", made_from="image", starred=True, start=_plain("image"),
           lines=["Come in."])

    assert downtime.hand_comfyui_more_of_the_backfill(
        db, client, AppState(tmp_path / "ui_state.json")) == 1

    (run,) = [row for row in db.list_generations() if row["source"] == GenerationSource.BACKFILL]
    assert [voice.how for voice in voices] == ["here"]
    assert [call.args[1] for call in client.submit_job.call_args_list] == [run["prompt_id"]]
    assert run["status"] == "running"


@pytest.mark.parametrize("status", ["running", "pending"])
def test_a_backfill_run_comfyui_has_no_record_of_is_cleared_so_its_video_is_remade_while_closed(
        qtbot, tmp_path, monkeypatch, status):
    # One ComfyUI lost, or one an earlier pass left waiting in its line, kept its
    # video from being offered again until Origenerator next opened (2026-10-29).
    monkeypatch.setattr(downtime.config, "OUTPUT_PLACES", _places(tmp_path))
    monkeypatch.setattr(downtime.config, "THUMB_DIR", _thumbnails(tmp_path))
    client = _comfyui_taking_everything()
    client.fetch_queue = MagicMock(return_value=set())
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _backfill_run(db, "lost", of="video", status=status, made=False)

    assert downtime.hand_comfyui_more_of_the_backfill(
        db, client, AppState(tmp_path / "ui_state.json")) == 1

    assert [(row["prompt_id"] == "lost", row["backfill_of"]) for row in db.list_generations()
            if row["source"] == GenerationSource.BACKFILL] == [(False, "video")]


# --- putting a finished backfill run in the old video's place -----------------


def _backfill_run(db, prompt_id, *, of, status="completed", made=True):
    db.insert_generation(prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version="v1",
                         params_json=json.dumps({"noise_seed": 7, "audio_seed": 8}),
                         workflow_json="{}", source=GenerationSource.BACKFILL)
    db.set_backfill_of(prompt_id, of)
    fields = {"status": status}
    if made:
        fields["output_files"] = json.dumps([_file(f"{prompt_id}_00001.mp4", "video")])
    db.update_generation(prompt_id, **fields)


def _evolver(tmp_path):
    return Evolver(places=OutputPlaces.in_one_folder(tmp_path / "output"),
                   upscaled_dir=tmp_path / "library" / "videos" / "upscaled",
                   records_folder=tmp_path / "library" / "metadata")


def _kino_copy(tmp_path, prompt_id, *, favorite=False):
    filed_under = Path("upscaled") / "landscape" / KINO.source / f"{prompt_id}_00001_topaz"
    copy = (tmp_path / "library" / "videos" / filed_under).with_suffix(".mp4")
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"upscaled")
    record = (tmp_path / "library" / "metadata" / filed_under).with_suffix(".json")
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"favorite": True} if favorite else {}), encoding="utf-8")
    return copy


def _places(tmp_path):
    return OutputPlaces.in_one_folder(tmp_path / "output")


def _thumbnails(tmp_path):
    return tmp_path / "thumbnails"


def _fold(db, tmp_path):
    trash = GalleryActions(db, _places(tmp_path), Trash(tmp_path / "trash")).delete_rows
    folded = fold_completed_backfill(db, _places(tmp_path), _thumbnails(tmp_path), trash=trash)
    return folded, [record["prompt_id"] for record in db.list_deletions()
                    if not record["row"].get("old_version_of")]


def _old_versions_in_trash(db, tmp_path):
    return [row for row in recovery.bin_items(db.list_deletions()) if row.get("old_version_of")]


def test_a_finished_backfill_run_becomes_its_old_video_which_keeps_its_star_and_sends(
        tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _sent_everywhere(db, "video")
    sent = {lane.flag: db.get_generation("video")[lane.flag] for lane in EXPORT_LANES}
    _finished_backfill_run(db, tmp_path, "again", of="video")

    assert _fold(db, tmp_path) == (1, [])

    listed = {row["prompt_id"]: row for row in db.list_generations()}
    assert "again" not in listed
    video = listed["video"]
    assert json.loads(video["params_json"]) == {"noise_seed": 7, "audio_seed": 8}
    assert video["starred"] and video["source"] == GenerationSource.GENERATED
    assert {flag: video[flag] for flag in sent} == sent


def test_the_remade_video_takes_its_old_videos_file_name(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    first = _made_on_disk(tmp_path, "video", b"first made")
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    assert first.read_bytes() == b"made again"
    assert not (first.parent / "again_00001.mp4").exists()
    named = [entry["filename"] for entry in gallery.row_output_files(db.get_generation("video"))]
    assert named == [first.name]


def test_the_old_version_waits_in_trash_as_an_item_of_its_own_marked_as_the_old_version(
        tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.mark_evolver_exported("video")
    _made_on_disk(tmp_path, "video", b"first made")
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    [old] = _old_versions_in_trash(db, tmp_path)
    assert old["old_version_of"] == "video" and old["prompt_id"] != "video"
    assert not old["starred"] and not old["evolver_exported_at"]
    [held] = gallery.row_output_files(old)
    assert gallery.output_file_path(held, _places(tmp_path)).read_bytes() == b"first made"


def test_a_video_remade_in_place_says_when_so_evolver_takes_the_new_one(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    assert db.get_generation("video")["remade_at"]


def test_a_video_the_earlier_fold_put_beside_its_old_one_is_remade_into_it(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", start=_plain("image"))
    first = _made_on_disk(tmp_path, "video", b"first made")
    db.set_source("video", GenerationSource.REPLACED)
    _finished_backfill_run(db, tmp_path, "again", of="video")
    db.set_source("again", GenerationSource.GENERATED)
    db.set_generation_favorite("again", True)

    assert _fold(db, tmp_path) == (1, [])

    video = db.get_generation("video")
    assert video["source"] == GenerationSource.GENERATED and video["starred"]
    assert db.get_generation("again") is None
    assert first.read_bytes() == b"made again"


def test_the_video_wears_the_remade_thumbnails_and_its_old_version_keeps_its_own(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _made_on_disk(tmp_path, "video", b"first made")
    thumbnails = _thumbnails(tmp_path)
    thumbnails.mkdir()
    (thumbnails / "video.jpg").write_bytes(b"first frame")
    (thumbnails / "again.jpg").write_bytes(b"remade frame")
    (thumbnails / "video_anim.webp").write_bytes(b"first frames")
    (thumbnails / "again_anim.webp").write_bytes(b"remade frames")
    db.update_generation("video", thumbnail_path=str(thumbnails / "video.jpg"))
    _finished_backfill_run(db, tmp_path, "again", of="video")
    db.update_generation("again", thumbnail_path=str(thumbnails / "again.jpg"))

    _fold(db, tmp_path)

    assert Path(db.get_generation("video")["thumbnail_path"]).read_bytes() == b"remade frame"
    assert (thumbnails / "video_anim.webp").read_bytes() == b"remade frames"
    [old] = _old_versions_in_trash(db, tmp_path)
    assert Path(old["thumbnail_path"]).read_bytes() == b"first frame"
    assert (thumbnails / f"{old['prompt_id']}_anim.webp").read_bytes() == b"first frames"


def _script_on_disk(tmp_path, video, content):
    script = funscript_path_for(video, places=_places(tmp_path))
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(content, encoding="utf-8")
    return script


def test_the_remade_videos_script_takes_the_old_scripts_name(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    first = _script_on_disk(tmp_path, _made_on_disk(tmp_path, "video", b"first made"), "first")
    _finished_backfill_run(db, tmp_path, "again", of="video")
    again = _script_on_disk(tmp_path, tmp_path / "output" / "video" / "again_00001.mp4", "again")

    _fold(db, tmp_path)

    assert first.read_text(encoding="utf-8") == "again"
    assert not again.exists()


@pytest.mark.parametrize("held", ["video", "script"])
def test_a_remake_stopped_by_a_file_held_open_finishes_at_the_next_launch(
        tmp_path, monkeypatch, held):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    first = _made_on_disk(tmp_path, "video", b"first made")
    script = _script_on_disk(tmp_path, first, "first")
    _finished_backfill_run(db, tmp_path, "again", of="video")
    remade = tmp_path / "output" / "video" / "again_00001.mp4"
    held_file = {"video": remade, "script": _script_on_disk(tmp_path, remade, "again")}[held]
    replace = Path.replace

    def held_open(path, target):
        if Path(path) == held_file:
            raise PermissionError("held open")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", held_open)
    assert _fold(db, tmp_path) == (0, [])
    monkeypatch.undo()

    assert _fold(db, tmp_path) == (1, [])

    assert first.read_bytes() == b"made again"
    assert script.read_text(encoding="utf-8") == "again"
    assert len(_old_versions_in_trash(db, tmp_path)) == 1


def _latest_videos(db):
    return [row["prompt_id"] for row in gallery.recent_generations(db.list_generations())
            if gallery.media_type_of_row(row) == MediaType.VIDEO]


def test_a_video_remade_in_place_keeps_its_place_in_latest(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.update_generation("video", completed_at="2026-10-24T06:01:56+00:00")
    _video(db, "made later", made_from="image", start=_enhancement("image"))
    db.update_generation("made later", completed_at="2026-10-25T06:01:56+00:00")
    _finished_backfill_run(db, tmp_path, "again", of="video")
    db.update_generation("again", completed_at="2026-10-29T18:58:24+00:00")

    _fold(db, tmp_path)

    assert _latest_videos(db) == ["made later", "video"]


def _asked_for(db_path, prompt_id, when):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE generations SET created_at = ? WHERE prompt_id = ?",
                     (when, prompt_id))


def _sent_long_ago(db_path, prompt_id):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE generations SET evolver_exported_at = '2026-01-02 03:04:05'"
                     " WHERE prompt_id = ?", (prompt_id,))


def test_a_video_remade_in_place_is_handed_down_the_lane_its_old_one_went_down(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _made_on_disk(tmp_path, "video", b"first made")
    db.mark_evolver_exported("video")
    _sent_long_ago(tmp_path / "t.db", "video")
    _finished_backfill_run(db, tmp_path, "again", of="video")
    _fold(db, tmp_path)
    inbox = tmp_path / "0_inbox"

    assert [hand_the_remakes_down_again(db, _places(tmp_path), EvolverInbox(inbox))
            for _launch in range(2)] == [1, 0]

    assert [path.read_bytes() for path in (inbox / KINO.source).iterdir()] == [b"made again"]


def test_a_video_remade_in_place_after_its_send_was_taken_back_stays_taken_back(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _made_on_disk(tmp_path, "video", b"first made")
    db.mark_evolver_exported("video")
    _sent_long_ago(tmp_path / "t.db", "video")
    db.mark_evolver_unsent("video")
    _finished_backfill_run(db, tmp_path, "again", of="video")
    _fold(db, tmp_path)

    assert hand_the_remakes_down_again(
        db, _places(tmp_path), EvolverInbox(tmp_path / "0_inbox")) == 0


def test_a_video_remade_in_place_keeps_the_sitting_latest_heads_it_with(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _asked_for(tmp_path / "t.db", "video", "2026-10-24 05:46:14")
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    assert gallery.section_headings([db.get_generation("video")], zone=UTC,
                                    today=date(2026, 10, 29)) == ["Sat Oct 24, 5:46 AM"]


def _made_on_disk(tmp_path, prompt_id, content=b"made again"):
    video = tmp_path / "output" / "video" / f"{prompt_id}_00001.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(content)
    return video


def _finished_backfill_run(db, tmp_path, prompt_id, *, of):
    _backfill_run(db, prompt_id, of=of)
    _made_on_disk(tmp_path, prompt_id)


def _sent_everywhere(db, prompt_id):
    db.mark_evolver_exported(prompt_id)
    db.mark_genau_exported(prompt_id)


def test_a_video_remade_in_place_keeps_its_act_and_its_source_video(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.set_settings_source("video", category="alpha", video_prompt_id="its source video")
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    video = db.get_generation("video")
    assert (video["act"], video["source_video"]) == ("alpha", "its source video")


def test_a_fun_time_favorite_stays_on_the_kino_copy_of_a_video_remade_in_place(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", start=_plain("image"))
    db.mark_evolver_exported("video")
    _made_on_disk(tmp_path, "video", b"first made")
    copy = _kino_copy(tmp_path, "video", favorite=True)
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    assert copy.read_bytes() == b"upscaled"
    assert record_of(copy, tmp_path / "library" / "metadata").favorite


def _owed_a_favorite(db_path, prompt_id):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE generations SET fun_time_favorite_owed = 1 WHERE prompt_id = ?",
                     (prompt_id,))


def test_an_owed_favorite_is_marked_on_the_new_videos_copy_once_evolver_has_filed_it(tmp_path):
    db = Database(tmp_path / "t.db")
    _video(db, "again", made_from="image")
    _made_on_disk(tmp_path, "again")
    _owed_a_favorite(tmp_path / "t.db", "again")

    assert pay_the_owed_favorites(db, _evolver(tmp_path)) == 0
    assert db.get_generation("again")["fun_time_favorite_owed"]

    copy = _kino_copy(tmp_path, "again")
    assert pay_the_owed_favorites(db, _evolver(tmp_path)) == 1

    assert record_of(copy, tmp_path / "library" / "metadata").favorite
    assert not db.get_generation("again")["fun_time_favorite_owed"]


def test_a_backfill_run_that_failed_is_cleared_so_the_next_absence_tries_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _backfill_run(db, "again", of="video", status="error", made=False)

    assert _fold(db, tmp_path) == (0, [])

    assert db.get_generation("again") is None
    assert _backfilled(db) == [("video", "image")]


def test_a_finished_enhancement_the_backfill_queued_is_left_for_its_image_to_take(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    db.insert_generation(prompt_id="enhancement", workflow_name="image_enhance",
                         workflow_version="v1", workflow_json="{}",
                         params_json=json.dumps({"input_image": _reference(_plain("image"))}),
                         source=GenerationSource.BACKFILL)
    db.update_generation("enhancement", status="completed",
                         output_files=json.dumps([_enhancement("image")]))

    assert _fold(db, tmp_path) == (0, [])

    assert db.get_generation("enhancement") is not None


def test_a_backfill_run_for_a_video_deleted_while_it_ran_goes_to_the_trash(tmp_path):
    db = Database(tmp_path / "t.db")
    _backfill_run(db, "again", of="a video deleted since")

    assert _fold(db, tmp_path) == (0, ["again"])


def test_a_video_asked_for_out_loud_as_a_genau_stays_asked_for_once_remade(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.mark_genau_requested("video")
    _finished_backfill_run(db, tmp_path, "again", of="video")

    _fold(db, tmp_path)

    assert db.get_generation("video")["genau_requested_at"]


def test_a_backfill_run_whose_video_is_not_on_disk_leaves_both_videos_for_the_next_launch(
        tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.mark_evolver_exported("video")
    _backfill_run(db, "again", of="video")

    assert _fold(db, tmp_path) == (0, [])

    assert db.get_generation("again")["source"] == GenerationSource.BACKFILL
    old = db.get_generation("video")
    assert old["source"] == GenerationSource.GENERATED
    assert old["evolver_exported_at"] and old["starred"]


def test_a_backfill_run_never_shows_beside_the_video_it_is_to_replace(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _backfill_run(db, "on its way", of="video", status="running", made=False)
    _backfill_run(db, "landed", of="video")

    tree = gallery.build_gallery_tree(db.list_generations())

    assert sorted(row["prompt_id"] for media in tree for row in gallery.rows_under(media)) \
        == ["image", "video"]


class _Client:
    def __init__(self):
        self.cancelled, self.interrupted = [], []

    def cancel_prompt(self, prompt_id):
        self.cancelled.append(prompt_id)

    def interrupt(self, prompt_id=None):
        self.interrupted.append(prompt_id)


def test_opening_the_app_drops_the_backfill_runs_the_absence_had_not_reached(tmp_path):
    db = Database(tmp_path / "t.db")
    _backfill_run(db, "queued", of="video", status="pending", made=False)
    _backfill_run(db, "landed", of="video")
    client = _Client()

    assert cancel_backfill(db, client) == 1

    assert client.cancelled == ["queued"]
    assert db.get_generation("queued") is None
    assert db.get_generation("landed") is not None


def test_a_video_made_from_the_enhancement_is_left_alone(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_enhancement("image"))

    assert _backfilled(db) == []
