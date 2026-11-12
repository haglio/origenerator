from __future__ import annotations

import json

import pytest

from origenerator import flick_finales
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.db_generations import NewGeneration
from origenerator.gallery import input_image_reference
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.job_queue import JobQueue
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.workflows.frame_rate import NATIVE_FPS
from tests.comfyui_folders import SUITE_FOLDERS
from tests.test_inflight_drop import FakeComfy


@pytest.fixture
def library(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(GenerationJob, "start", lambda self, submit=None: None)
    db = Database(tmp_path / "t.db")
    return db, JobQueue(db, ComfyUIClient(folders=SUITE_FOLDERS))


def _finished(db, prompt_id: str, workflow_name: str, file: str, **params) -> dict:
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name=workflow_name,
                                       workflow_version="v001", params_json=json.dumps(params),
                                       workflow_json="{}"))
    subfolder, filename = file.split("/")
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": filename, "subfolder": subfolder}]))
    return db.get_generation(prompt_id)


def a_flick_sent_to_genau(db, flick: str = "flick", *, image: str = "img",
                           image_actions=("alpha",), flick_actions=("alpha",)) -> None:
    start = _finished(db, image, "sdxl_t2i", f"image/jane_doe_{image}.png")
    db.set_actions(image, MediaType.IMAGE, ItemActions(tuple(image_actions), ()))
    _finished(db, flick, "wan22_flf2v_loop", f"video/jane_doe_{flick}.mp4",
              input_image=input_image_reference(start))
    db.set_actions(flick, MediaType.VIDEO, ItemActions(tuple(flick_actions), ()))
    db.mark_genau_exported(flick)


def _made(db) -> list[dict]:
    return [row for row in db.list_generations() if row.get("status") == "pending"]


def test_a_flick_sent_to_genau_gets_a_fifteen_second_video_of_its_action_with_the_box_ticked(
        library):
    db, jobs = library
    a_flick_sent_to_genau(db)

    assert flick_finales.queue_finales(jobs, db, db.list_generations()) == 1

    (finale,) = _made(db)
    params = json.loads(finale["params_json"])
    assert (finale["workflow_name"], params["frame_count"], params["input_image"]) == (
        "wan22_i2v", 15 * NATIVE_FPS + 1, input_image_reference(db.get_generation("img")))
    assert actions_of(finale, MediaType.VIDEO) == ItemActions(("alpha",), ("third box",))
    assert db.get_generation("flick")["finale_id"] == finale["prompt_id"]


def _queued(db, jobs) -> int:
    return flick_finales.queue_finales(jobs, db, db.list_generations())


def test_a_flick_whose_video_failed_gets_another(library):
    db, jobs = library
    a_flick_sent_to_genau(db)
    _queued(db, jobs)
    (failed,) = _made(db)
    db.update_generation(failed["prompt_id"], status="error")

    assert _queued(db, jobs) == 1

    (again,) = _made(db)
    assert db.get_generation("flick")["finale_id"] == again["prompt_id"] != failed["prompt_id"]


def test_a_flick_whose_video_was_deleted_is_left_without_one(library):
    db, jobs = library
    a_flick_sent_to_genau(db)
    _queued(db, jobs)
    (deleted,) = _made(db)
    db.delete_generation(deleted["prompt_id"])

    assert _queued(db, jobs) == 0
    assert _made(db) == []


def test_a_flick_with_no_action_gets_nothing(library):
    db, jobs = library
    a_flick_sent_to_genau(db, flick_actions=())

    assert _queued(db, jobs) == 0


def test_a_flick_whose_image_combine_would_not_animate_as_its_action_gets_nothing(library):
    db, jobs = library
    a_flick_sent_to_genau(db, image_actions=("gamma",))

    assert _queued(db, jobs) == 0


def test_nothing_is_made_while_the_overlay_names_no_video_checkbox_for_it(library, monkeypatch):
    db, jobs = library
    a_flick_sent_to_genau(db)
    monkeypatch.setattr(flick_finales, "finale_checkbox", lambda: "a box nobody drew")

    assert _queued(db, jobs) == 0


def test_opening_drops_each_video_still_being_made_and_the_next_closing_queues_it_again(library):
    db, jobs = library
    a_flick_sent_to_genau(db)
    a_flick_sent_to_genau(db, "flick two", image="img two")
    _queued(db, jobs)
    (waiting, stuck) = _made(db)
    comfyui = FakeComfy(refuses={stuck["prompt_id"]})

    assert flick_finales.drop_finales_in_flight(db, comfyui) == 1

    assert (comfyui.cancelled, db.get_generation(waiting["prompt_id"])) == ([waiting["prompt_id"]], None)
    assert _queued(db, jobs) == 1
    assert db.get_generation(stuck["prompt_id"]) is not None
