from __future__ import annotations

import json

from origenerator import gallery
from origenerator.db import Database, NewGeneration
from origenerator.db_requests import NewRequest
from origenerator.gallery_edits import GalleryEdits
from origenerator.generation_state import GenerationSource
from origenerator.item_actions import ItemActions
from origenerator.output_places import OutputPlaces
from origenerator.request_seed_remake import (
    RemakesInTheQueue,
    put_in_place,
    remake_what_took_the_wrong_seed,
    wrong_seed_request_images,
)
from origenerator.trash import Trash
from origenerator.workflows import workflow_named


def _image(db, prompt_id, seed, *, workflow="sdxl_t2i", prompt="a red kite over a beach"):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name=workflow, workflow_version="v1",
        positive_prompt=prompt, seed=seed,
        params_json=json.dumps({**workflow_named(workflow).default_params(),
                                "positive_prompt": prompt, "seed": seed}),
        workflow_json="{}"))
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": f"{prompt_id}_00001_.png", "subfolder": "", "type": "output"}]))


def _asked(db, prompt_id, of, *, said="two kites"):
    db.record_request(NewRequest(prompt_id=prompt_id, source_prompt_id=of, heard=said, asked=said))


def _modified(db, prompt_id, of):
    db.record_request(NewRequest(prompt_id=prompt_id, source_prompt_id=of, heard=""))


def _found(db):
    return [(remake.item["prompt_id"], remake.seeds)
            for remake in wrong_seed_request_images(db.list_generations(), db.list_requests())]


def test_an_image_a_request_made_with_another_seed_than_the_item_it_was_asked_of_is_found(
        tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "asked wrong", 9)
    _asked(db, "asked wrong", "first")
    _image(db, "asked right", 7)
    _asked(db, "asked right", "first")

    assert _found(db) == [("asked wrong", {"seed": 7})]


def test_an_image_asked_on_a_request_image_takes_the_seed_the_chain_started_from(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9)
    _asked(db, "second", "first")
    _image(db, "third", 9)
    _asked(db, "third", "second")

    assert _found(db) == [("second", {"seed": 7}), ("third", {"seed": 7})]


def test_a_modify_batchs_row_is_no_request_and_starts_a_chain_of_its_own(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "modified", 9)
    _modified(db, "modified", "first")
    _image(db, "asked of the modified", 9)
    _asked(db, "asked of the modified", "modified")

    assert _found(db) == []


def test_a_request_asked_of_an_item_of_another_workflow_starts_a_chain_of_its_own(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7, workflow="krea2_t2i")
    _image(db, "asked across", 9)
    _asked(db, "asked across", "first")

    assert _found(db) == []


def _places(tmp_path):
    return OutputPlaces.in_one_folder(tmp_path / "output")


def _on_disk(tmp_path, row_or_entry, made: bytes):
    entry = row_or_entry if "filename" in row_or_entry else gallery.row_output_files(row_or_entry)[0]
    path = gallery.output_file_path(entry, _places(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(made)
    return path


def _finished_remake(db, tmp_path, prompt_id, *, of, seed=7, number=31):
    item = db.get_generation(of)
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name=item["workflow_name"], workflow_version="v2",
        positive_prompt=item["positive_prompt"], seed=seed,
        params_json=json.dumps({**json.loads(item["params_json"]), "seed": seed}),
        workflow_json="{}", source=GenerationSource.REMAKE))
    db.set_backfill_of(prompt_id, of)
    files = [{"filename": f"sdxl_t2i_{number:05d}_.png", "subfolder": "", "type": "output"}]
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(files),
                         thumbnail_path=str(tmp_path / f"{prompt_id}.jpg"))
    _on_disk(tmp_path, files[0], b"made again")
    return db.get_generation(prompt_id)


def _trash(db, tmp_path):
    return GalleryEdits(db, _places(tmp_path), Trash(tmp_path / "trash")).delete_rows


def _put_in_place(db, tmp_path, run):
    return put_in_place(db, run, places=_places(tmp_path), trash=_trash(db, tmp_path))


def _kept_item(db, tmp_path):
    _image(db, "first", 7)
    _image(db, "asked wrong", 9)
    _asked(db, "asked wrong", "first")
    db.set_generation_favorite("asked wrong", True)
    db.set_actions("asked wrong", "image", ItemActions(("alpha",), ("beta",)))
    db.mark_evolver_exported("asked wrong")
    return db.get_generation("asked wrong")


def test_a_finished_remake_becomes_the_item_it_remakes_which_keeps_everything_he_gave_it(
        tmp_path):
    db = Database(tmp_path / "t.db")
    before = _kept_item(db, tmp_path)
    run = _finished_remake(db, tmp_path, "again", of="asked wrong")

    assert _put_in_place(db, tmp_path, run)

    item = db.get_generation("asked wrong")
    assert db.get_generation("again") is None
    assert (item["seed"], json.loads(item["params_json"])["seed"]) == (7, 7)
    assert item["remade_at"]
    kept = ("created_at", "completed_at", "starred", "image_actions", "image_checked",
            "evolver_exported_at", "source")
    assert {column: item[column] for column in kept} == {column: before[column] for column in kept}
    assert [request["prompt_id"] for request in db.requests_about("first")] == ["asked wrong"]
    assert _found(db) == []


def test_the_remade_image_takes_the_file_name_of_the_image_it_remakes(tmp_path):
    db = Database(tmp_path / "t.db")
    first_made = _on_disk(tmp_path, _kept_item(db, tmp_path), b"first made")
    run = _finished_remake(db, tmp_path, "again", of="asked wrong")

    _put_in_place(db, tmp_path, run)

    assert first_made.read_bytes() == b"made again"
    assert not (first_made.parent / "sdxl_t2i_00031_.png").exists()
    assert [entry["filename"] for entry in
            gallery.row_output_files(db.get_generation("asked wrong"))] == [first_made.name]


def test_the_old_version_waits_in_trash_as_an_item_of_its_own_with_none_of_the_marks(tmp_path):
    db = Database(tmp_path / "t.db")
    _on_disk(tmp_path, _kept_item(db, tmp_path), b"first made")
    run = _finished_remake(db, tmp_path, "again", of="asked wrong")

    _put_in_place(db, tmp_path, run)

    [old] = [record["row"] for record in db.list_trashed()]
    assert (old["old_version_of"], old["seed"]) == ("asked wrong", 9)
    assert old["prompt_id"] != "asked wrong"
    assert [old[mark] for mark in ("starred", "evolver_exported_at", "image_actions")] == [
        0, None, None]
    assert db.requests_about("asked wrong") == []


def test_an_image_already_gone_from_disk_is_not_sent_to_trash_as_an_old_version_of_nothing(
        tmp_path):
    db = Database(tmp_path / "t.db")
    first_made = _on_disk(tmp_path, _kept_item(db, tmp_path), b"first made")
    run = _finished_remake(db, tmp_path, "again", of="asked wrong")
    first_made.unlink()

    assert _put_in_place(db, tmp_path, run)

    assert first_made.read_bytes() == b"made again"
    assert db.list_trashed() == []


class _Queue:
    def __init__(self, db):
        self._db = db
        self.asked = []

    def __call__(self, item, workflow, params):
        prompt_id = f"remake {len(self.asked) + 1}"
        self.asked.append((item["prompt_id"], workflow.name, params["seed"]))
        self._db.insert_generation(NewGeneration(
            prompt_id=prompt_id, workflow_name=workflow.name, workflow_version="v2",
            params_json=json.dumps(params), workflow_json="{}", source=GenerationSource.REMAKE))
        return prompt_id


def _remake(db, tmp_path, queue, *, why_not=lambda _item: None, environ=None):
    return remake_what_took_the_wrong_seed(
        db, queue=queue, places=_places(tmp_path), trash=_trash(db, tmp_path), why_not=why_not,
        environ=environ or {})


def test_each_image_that_took_the_wrong_seed_is_queued_with_its_own_settings_and_the_right_seed(
        tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    queue = _Queue(db)

    _remake(db, tmp_path, queue)

    assert queue.asked == [("second", "sdxl_t2i", 7)]
    [run] = [row for row in db.list_generations() if row["prompt_id"] == "remake 1"]
    assert run["backfill_of"] == "second"
    assert json.loads(run["params_json"])["positive_prompt"] == "two red kites over a beach"


def test_an_image_whose_remake_is_still_waiting_is_not_queued_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    _remake(db, tmp_path, _Queue(db))
    again = _Queue(db)

    _remake(db, tmp_path, again)

    assert again.asked == []


def test_a_remake_that_would_make_an_image_already_there_makes_nothing(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9)
    _asked(db, "second", "first")
    queue = _Queue(db)

    _remake(db, tmp_path, queue)

    assert queue.asked == []
    assert db.get_generation("second")["seed"] == 9


def test_two_images_whose_remakes_would_come_out_the_same_are_made_once(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    _image(db, "third", 9, prompt="two red kites over a beach")
    _asked(db, "third", "second")
    queue = _Queue(db)

    tally = _remake(db, tmp_path, queue)

    assert queue.asked == [("second", "sdxl_t2i", 7)]
    assert tally.left == {"already made": ["third"]}


def test_an_image_the_app_cannot_make_again_is_left_as_it_is(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    queue = _Queue(db)

    tally = _remake(db, tmp_path, queue, why_not=lambda _item: "Example Model isn't installed")

    assert queue.asked == []
    assert tally.left == {"cannot be made again": ["second"]}


def test_a_remake_finished_while_the_app_was_closed_is_put_in_place_at_the_next_launch(tmp_path):
    db = Database(tmp_path / "t.db")
    _kept_item(db, tmp_path)
    _finished_remake(db, tmp_path, "again", of="asked wrong")
    queue = _Queue(db)

    tally = _remake(db, tmp_path, queue)

    assert (tally.remade, queue.asked) == (1, [])
    assert db.get_generation("asked wrong")["seed"] == 7


def test_once_every_image_is_remade_the_pass_finds_nothing_and_queues_nothing(tmp_path):
    db = Database(tmp_path / "t.db")
    _kept_item(db, tmp_path)
    _finished_remake(db, tmp_path, "again", of="asked wrong")
    _remake(db, tmp_path, _Queue(db))
    queue = _Queue(db)

    tally = _remake(db, tmp_path, queue)

    assert (tally.found, tally.remade, queue.asked) == (0, 0, [])


def test_a_preview_leaves_the_remakes_to_production(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    queue = _Queue(db)

    _remake(db, tmp_path, queue, environ={"ORIGENERATOR_BRANCH_SESSION": "1"})

    assert queue.asked == []


class _Finished:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *said):
        for slot in self._slots:
            slot(*said)


class _Jobs:
    def __init__(self, db):
        self._db = db
        self.finished = _Finished()
        self.started = []

    def start_prepared(self, key, workflow, params, *, source):
        self.started.append((key, params["seed"], source))
        return _Queue(self._db)({"prompt_id": key}, workflow, params)


def _in_the_queue(db, tmp_path, jobs):
    return RemakesInTheQueue(db, jobs, client=object(), places=_places(tmp_path),
                             trash_dir=tmp_path / "trash", why_not=lambda _item: None)


def test_the_app_puts_each_remake_in_its_job_queue_as_a_remake(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    jobs = _Jobs(db)

    _in_the_queue(db, tmp_path, jobs).start()

    assert jobs.started == [("remake/second", 7, GenerationSource.REMAKE)]


def test_a_remake_that_lands_from_the_job_queue_takes_its_items_place_at_once(tmp_path):
    db = Database(tmp_path / "t.db")
    _kept_item(db, tmp_path)
    _finished_remake(db, tmp_path, "again", of="asked wrong")
    jobs = _Jobs(db)
    _in_the_queue(db, tmp_path, jobs)

    jobs.finished.emit("remake/asked wrong", "again", "again")

    assert db.get_generation("asked wrong")["seed"] == 7
    assert db.get_generation("again") is None


def test_with_no_comfyui_nothing_is_put_in_the_job_queue(tmp_path):
    db = Database(tmp_path / "t.db")
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    _asked(db, "second", "first")
    jobs = _Jobs(db)

    RemakesInTheQueue(db, jobs, client=None, places=_places(tmp_path),
                      trash_dir=tmp_path / "trash").start()

    assert jobs.started == []
