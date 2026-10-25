"""Making a kept video again from its image's enhancement, when it started from the plain image.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import downtime, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.enhanced_start_backfill import (
    Evolver,
    backfill_params_for,
    cancel_backfill,
    fold_completed_backfill,
    queue_backfill,
    trash_what_the_backfill_replaced,
    videos_to_backfill,
)
from origenerator.evolver_export import EvolverInbox
from origenerator.export_lane import EXPORT_LANES, KINO
from origenerator.generation_state import GenerationSource
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.job_queue import JobQueue
from origenerator.output_places import OutputPlaces


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
           workflow="wan22_i2v"):
    params = {"input_image": _reference(start or _plain(made_from)),
              "noise_seed": 7, "audio_seed": 8}
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

    def queue(self, db, **budget):
        return queue_backfill(db.list_generations(), self.launch, enhance=self.enhance, **budget)


def test_an_image_never_enhanced_is_enhanced_first_and_its_video_waits(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image")
    _video(db, "video", made_from="image", starred=True)
    absence = _Absence()

    assert absence.queue(db) == 0

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
    jobs = JobQueue(db, ComfyUIClient())

    assert downtime.queue_the_backfill(jobs, db, db.list_generations(),
                                      enhance_settings=gallery.EnhanceSettings.parse(None)) == 1

    queued = [row for row in db.list_generations() if row["source"] == GenerationSource.BACKFILL]
    assert sorted((row["workflow_name"], row["backfill_of"] or row["enhance_of"])
                  for row in queued) == [("image_enhance", "plain image"),
                                         ("wan22_i2v", "from enhanced")]


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
    return Evolver(inbox=EvolverInbox(tmp_path / "inbox"),
                   places=OutputPlaces.in_one_folder(tmp_path / "output"),
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


def _fold(db, tmp_path):
    trashed = []
    folded = fold_completed_backfill(db, _evolver(tmp_path), trash=trashed.extend)
    return folded, [row["prompt_id"] for row in trashed]


def test_a_finished_backfill_run_takes_the_old_videos_place_and_its_star(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _backfill_run(db, "again", of="video")

    assert _fold(db, tmp_path) == (1, [])

    listed = {row["prompt_id"]: row for row in db.list_generations()}
    assert "video" not in listed
    assert listed["again"]["source"] == GenerationSource.GENERATED
    assert listed["again"]["starred"]
    assert not db.get_generation("video")["starred"]


def _made_on_disk(tmp_path, prompt_id, content=b"made again"):
    video = tmp_path / "output" / "video" / f"{prompt_id}_00001.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(content)
    return video


def _sent_everywhere(db, prompt_id):
    db.mark_evolver_exported(prompt_id)
    db.mark_genau_exported(prompt_id)


def test_the_new_video_goes_down_each_lane_the_old_one_went_and_the_old_send_is_taken_back(
        tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", start=_plain("image"))
    _sent_everywhere(db, "video")
    _backfill_run(db, "again", of="video")
    _made_on_disk(tmp_path, "again")

    _fold(db, tmp_path)

    again, old = db.get_generation("again"), db.get_generation("video")
    for lane in EXPORT_LANES:
        landed = tmp_path / "inbox" / lane.source / "again_00001.mp4"
        assert landed.read_bytes() == b"made again"
        assert again[lane.flag] and old[lane.unsent_flag] and not old[lane.flag]


def test_the_act_said_of_the_old_video_is_said_of_the_new_one(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.set_settings_source("video", category="alpha", video_prompt_id="its source video")
    _backfill_run(db, "again", of="video")

    _fold(db, tmp_path)

    again = db.get_generation("again")
    assert (again["act"], again["source_video"]) == ("alpha", "its source video")


def test_a_fun_time_favorite_on_the_old_videos_copy_is_owed_to_the_new_one(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", start=_plain("image"))
    db.mark_evolver_exported("video")
    _made_on_disk(tmp_path, "video", b"first made")
    _kino_copy(tmp_path, "video", favorite=True)
    _backfill_run(db, "again", of="video")
    _made_on_disk(tmp_path, "again")

    _fold(db, tmp_path)

    assert db.get_generation("again")["fun_time_favorite_owed"]


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


def test_a_video_asked_for_out_loud_as_a_genau_stays_asked_for_once_backfilled(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    db.mark_genau_requested("video")
    _backfill_run(db, "again", of="video")

    _fold(db, tmp_path)

    assert db.get_generation("again")["genau_requested_at"]


def test_a_send_that_fails_leaves_both_videos_as_they_were_for_the_next_launch(tmp_path):
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


# --- and the old video to the Trash, once Evolver has let go of it ------------


def _trashed_after_the_fold(db, tmp_path):
    _fold(db, tmp_path)
    trashed = []
    trash_what_the_backfill_replaced(db, _evolver(tmp_path), trash=trashed.extend)
    return trashed


def test_an_old_video_sent_nowhere_goes_to_the_trash_as_a_video_of_the_gallery(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_plain("image"))
    _backfill_run(db, "again", of="video")

    trashed = _trashed_after_the_fold(db, tmp_path)

    assert [(row["prompt_id"], row["source"]) for row in trashed] == \
        [("video", GenerationSource.GENERATED)]


def _sent_and_backfilled(db, tmp_path):
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", start=_plain("image"))
    _sent_everywhere(db, "video")
    _made_on_disk(tmp_path, "video", b"first made")
    _backfill_run(db, "again", of="video")
    _made_on_disk(tmp_path, "again")


def test_an_old_video_waits_out_of_sight_while_the_new_one_waits_in_evolvers_inbox(tmp_path):
    # Evolver takes the old copies back on the run that takes the new one in, and
    # it can only take them back for a row that is still here to say so.
    db = Database(tmp_path / "t.db")
    _sent_and_backfilled(db, tmp_path)

    assert _trashed_after_the_fold(db, tmp_path) == []

    assert "video" not in [row["prompt_id"] for row in db.list_generations()]


def _evolver_ran(tmp_path):
    for lane in EXPORT_LANES:
        (tmp_path / "inbox" / lane.source / "again_00001.mp4").unlink()


def test_once_evolver_has_taken_the_new_one_in_the_old_video_goes_to_the_trash(tmp_path):
    db = Database(tmp_path / "t.db")
    _sent_and_backfilled(db, tmp_path)
    _trashed_after_the_fold(db, tmp_path)
    _evolver_ran(tmp_path)

    trashed = []
    trash_what_the_backfill_replaced(db, _evolver(tmp_path), trash=trashed.extend)

    assert [row["prompt_id"] for row in trashed] == ["video"]


def test_an_old_video_waits_while_evolver_still_holds_its_copy_in_kino(tmp_path):
    db = Database(tmp_path / "t.db")
    _sent_and_backfilled(db, tmp_path)
    _kino_copy(tmp_path, "video")
    _trashed_after_the_fold(db, tmp_path)
    _evolver_ran(tmp_path)

    trashed = []
    trash_what_the_backfill_replaced(db, _evolver(tmp_path), trash=trashed.extend)

    assert trashed == []


def test_a_video_made_from_the_enhancement_is_left_alone(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "image", enhanced=True)
    _video(db, "video", made_from="image", starred=True, start=_enhancement("image"))

    assert _backfilled(db) == []
