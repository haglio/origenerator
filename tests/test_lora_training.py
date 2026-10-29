from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

from origenerator import lora_training
from origenerator.lora_training import TrainingState


def _started(monkeypatch) -> list:
    started = []

    def popen(args, **options):
        started.append((args, options))
        options["stdout"].write(b"what the training printed\n")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(lora_training.subprocess, "Popen", popen)
    monkeypatch.setattr(lora_training, "process_started", lambda pid: 1111 if pid == 4321 else None)
    return started


def _job(tmp_path, **more) -> dict:
    return {"display_name": "Example Look 1.1", **lora_training.work_files(tmp_path / "work"), **more}


def _start(tmp_path, **for_the_program):
    return lora_training.start(_job(tmp_path), Path("C:/training/python.exe"),
                               Path("C:/trainers/example_trainer.py"), **for_the_program)


def test_a_training_runs_its_program_under_the_given_python_with_no_window_into_its_log(
        monkeypatch, tmp_path):
    started = _started(monkeypatch)
    job = _job(tmp_path)

    lora_training.start(job, Path("C:/training/python.exe"), Path("C:/trainers/example_trainer.py"),
                        comfyui_python="C:/comfyui/python.exe")

    ((args, options),) = started
    assert args == [str(Path("C:/training/python.exe")), str(Path("C:/trainers/example_trainer.py")),
                    "run", job["job_file"]]
    assert json.loads(Path(job["job_file"]).read_text(encoding="utf-8")) == dict(
        job, comfyui_python="C:/comfyui/python.exe")
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert Path(job["log"]).read_text(encoding="utf-8") == "what the training printed\n"


def test_a_new_training_starts_its_log_and_its_word_afresh(monkeypatch, tmp_path):
    _started(monkeypatch)
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["log"]).write_text("the last training\n", encoding="utf-8")
    Path(job["status"]).write_text('{"state": "done"}', encoding="utf-8")

    _start(tmp_path)

    assert Path(job["log"]).read_text(encoding="utf-8") == "what the training printed\n"
    assert lora_training.read_status(job) is None


def test_a_training_is_known_to_be_running_by_its_program_from_any_launch(monkeypatch, tmp_path):
    _started(monkeypatch)

    trainer = _start(tmp_path)

    assert trainer.running()
    assert lora_training.trainer_of(_job(tmp_path)).running()
    monkeypatch.setattr(lora_training, "process_started", lambda pid: None)
    assert not lora_training.trainer_of(_job(tmp_path)).running()


def test_a_program_that_took_a_finished_trainings_number_is_not_the_training(
        monkeypatch, tmp_path):
    _started(monkeypatch)
    _start(tmp_path)

    monkeypatch.setattr(lora_training, "process_started", lambda pid: 2222)

    assert not lora_training.trainer_of(_job(tmp_path)).running()


def test_no_training_was_ever_started_where_there_is_no_record_of_one(tmp_path):
    assert lora_training.trainer_of(_job(tmp_path)) is None


def test_a_training_from_before_its_program_was_recorded_has_none(tmp_path):
    job = _job(tmp_path)
    del job["process"]

    assert lora_training.trainer_of(job) is None


def test_stopping_a_training_ends_its_program_and_everything_it_started(monkeypatch, tmp_path):
    _started(monkeypatch)
    trainer = _start(tmp_path)
    ran = []
    monkeypatch.setattr(lora_training.subprocess, "run",
                        lambda args, **options: ran.append((args, options)))

    trainer.stop()

    ((args, options),) = ran
    assert args == ["taskkill", "/F", "/T", "/PID", "4321"]
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_a_training_that_has_ended_is_not_stopped_again(monkeypatch, tmp_path):
    _started(monkeypatch)
    trainer = _start(tmp_path)
    monkeypatch.setattr(lora_training, "process_started", lambda pid: None)
    ran = []
    monkeypatch.setattr(lora_training.subprocess, "run", lambda args, **options: ran.append(args))

    trainer.stop()

    assert ran == []


def test_how_long_trainings_take_is_kept_in_their_folder_so_the_next_can_be_counted_down(tmp_path):
    folder = tmp_path / "trainings"
    assert lora_training.typical_seconds(folder) is None

    for seconds in (3000.0, 2400.0, 2600.0):
        lora_training.note_duration(folder, seconds)

    assert lora_training.typical_seconds(folder) == 2600.0


def _job_kept(tmp_path, name, **status) -> dict:
    work = tmp_path / name
    work.mkdir(parents=True)
    job = {"display_name": name, **lora_training.work_files(work)}
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    if status:
        Path(job["status"]).write_text(json.dumps(status), encoding="utf-8")
    return job


def test_every_training_ever_started_in_a_folder_is_found_by_its_job(tmp_path):
    kept = _job_kept(tmp_path, "Example Look 1.1")
    (tmp_path / "not a training").mkdir()

    assert lora_training.trainings(tmp_path) == [kept]
    assert lora_training.running_trainings(tmp_path) == []


def test_a_lora_made_while_the_app_was_closed_is_taken_once(tmp_path):
    job = _job_kept(tmp_path, "Example Look 1.1", state="done", lora="Example Look 1.1.safetensors")

    assert lora_training.untaken_lora(job) == "Example Look 1.1.safetensors"
    lora_training.mark_taken(job)
    assert lora_training.untaken_lora(job) is None


def test_a_training_that_did_not_finish_has_no_lora_to_take(tmp_path):
    job = _job_kept(tmp_path, "Example Look 1.1", state="failed", message="No pictures.")

    assert lora_training.untaken_lora(job) is None


def test_the_trainers_word_is_read_back_and_is_none_until_it_has_said_something(tmp_path):
    job = {"status": str(tmp_path / "status.json")}
    assert lora_training.read_status(job) is None

    Path(job["status"]).write_text('{"state": "training", "done": 3, "total": 10}', encoding="utf-8")
    assert lora_training.read_status(job) == {"state": "training", "done": 3, "total": 10}


def test_what_a_training_came_to_names_it_the_way_its_button_does(tmp_path):
    outcome = lora_training.outcome_of(_job(tmp_path), ok=True, seconds=2952.0)

    assert (outcome.kind, outcome.display_name, outcome.ok, outcome.seconds) == (
        "Training", "Example Look 1.1", True, 2952.0)


class _KeptTrainer:
    def __init__(self, alive):
        self.alive = alive
        self.began = 0.0

    def running(self):
        return self.alive

    def stop(self):
        self.alive = False


def _kind(tmp_path, jobs):
    return types.SimpleNamespace(trainings=lambda: jobs)


def test_at_launch_a_running_training_is_adopted_and_a_finished_one_taken_once(
        tmp_path, monkeypatch):
    running = _job_kept(tmp_path, "running")
    finished = _job_kept(tmp_path, "finished", state="done", lora="finished.safetensors")
    never_started = _job_kept(tmp_path, "never started")
    trainers = {running["work"]: _KeptTrainer(alive=True), finished["work"]: _KeptTrainer(alive=False)}
    monkeypatch.setattr(lora_training, "trainer_of", lambda job: trainers.get(job["work"]))
    adopted, taken = [], []

    for _twice in range(2):
        lora_training.take_up(_kind(tmp_path, [running, finished, never_started]),
                              adopt=lambda job, trainer: adopted.append(job["display_name"]),
                              take=lambda job, lora: (taken.append(lora), lora_training.mark_taken(job)))

    assert (adopted, taken) == (["running", "running"], ["finished.safetensors"])


def test_at_launch_a_training_evolver_started_while_the_app_was_closed_is_stopped(
        tmp_path, monkeypatch):
    automatic = _job_kept(tmp_path, "automatic")
    automatic["automatic"] = True
    trainer = _KeptTrainer(alive=True)
    monkeypatch.setattr(lora_training, "trainer_of", lambda job: trainer)
    adopted = []

    lora_training.take_up(_kind(tmp_path, [automatic]),
                          adopt=lambda job, kept: adopted.append(job), take=lambda job, lora: None)

    assert not trainer.running()
    assert adopted == []


def test_a_training_is_current_while_the_pictures_it_kept_are_the_ones_in_the_folder(tmp_path):
    pictures = [tmp_path / "one.jpg"]
    pictures[0].write_bytes(b"one")
    trained = tmp_path / "trained.json"
    stamps = lora_training.picture_stamps(pictures)
    assert list(stamps) == [f"{tmp_path.name}/one.jpg"]
    assert lora_training.training_state(trained, stamps) is TrainingState.UNTRAINED

    trained.write_text(json.dumps({"photo_stamps": stamps}), encoding="utf-8")
    assert lora_training.training_state(trained, stamps) is TrainingState.CURRENT

    pictures[0].write_bytes(b"one, retouched")
    assert lora_training.training_state(
        trained, lora_training.picture_stamps(pictures)) is TrainingState.OUT_OF_DATE
