from __future__ import annotations

import json
import subprocess
import types
from datetime import datetime
from pathlib import Path

from origenerator import config, fix_training
from origenerator.workflows import detail_parts
from tools import fix_lora_trainer


def _part(name):
    return next(part for part in detail_parts.part_table() if part.name == name)


def test_each_fix_takes_its_photos_from_a_folder_named_for_it():
    assert fix_training.photos_folder(_part("hands")) == config.FIX_PHOTOS_DIR / "Hands"


def test_only_photos_in_a_fixs_folder_are_trained_on(tmp_path):
    for name in ("b.jpg", "a.PNG", "notes.txt", "c.webp"):
        (tmp_path / name).write_bytes(b"")

    assert [path.name for path in fix_training.photo_files(tmp_path)] == ["a.PNG", "b.jpg", "c.webp"]
    assert fix_training.photo_files(tmp_path / "not made yet") == []


def test_a_training_job_names_the_fixs_photos_its_detector_and_the_model_to_train_for(
        monkeypatch, tmp_path):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["hand_yolov8s.pt"])
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path)
    (tmp_path / "Hands").mkdir()
    (tmp_path / "Hands" / "one.jpg").write_bytes(b"")
    monkeypatch.setattr(config, "LORA_TRAINING_SCRIPTS", Path("C:/sd-scripts"))
    models = config.COMFYUI_DIR / "models"

    job = fix_training.training_job(_part("hands"), "base.safetensors",
                                    datetime(2026, 10, 19, 1, 30))

    assert job["photos"] == [str(tmp_path / "Hands" / "one.jpg")]
    assert job["photos_folder"] == str(tmp_path / "Hands")
    assert job["detector"] == str(models / "ultralytics" / "bbox" / "hand_yolov8s.pt")
    assert job["base_model"] == str(models / "checkpoints" / "base.safetensors")
    assert job["output_dir"] == str(models / "loras" / "fixes")
    assert job["output_name"] == "hands 2026-10-19 0130"
    assert job["sd_scripts"] == str(Path("C:/sd-scripts"))


def _started(monkeypatch) -> list:
    started = []

    def popen(args, **options):
        started.append((args, options))
        options["stdout"].write(b"what the training printed\n")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(fix_training.subprocess, "Popen", popen)
    monkeypatch.setattr(fix_training, "process_started", lambda pid: 1111 if pid == 4321 else None)
    monkeypatch.setattr(fix_training, "comfyui_python", lambda: Path("C:/comfyui/python.exe"))
    monkeypatch.setattr(config, "LORA_TRAINING_PYTHON", Path("C:/training/python.exe"))
    return started


def _work(tmp_path) -> dict:
    work = tmp_path / "work"
    return {"part": "hands", "work": str(work), "status": str(work / "status.json"),
            "log": str(work / "training.log"), "job_file": str(work / "job.json"),
            "process": str(work / "process.json")}


def test_a_training_runs_whole_under_the_training_python_with_no_window_into_its_log(
        monkeypatch, tmp_path):
    started = _started(monkeypatch)
    job = _work(tmp_path)

    fix_training.start(job)

    ((args, options),) = started
    assert args == [str(Path("C:/training/python.exe")), str(fix_training.TRAINER), "run",
                    job["job_file"]]
    assert args[2] in fix_lora_trainer.STEPS
    assert json.loads(Path(job["job_file"]).read_text(encoding="utf-8")) == dict(
        job, comfyui_python=str(Path("C:/comfyui/python.exe")))
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert Path(job["log"]).read_text(encoding="utf-8") == "what the training printed\n"


def test_a_new_training_starts_its_log_and_its_word_afresh(monkeypatch, tmp_path):
    _started(monkeypatch)
    job = _work(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["log"]).write_text("the last training\n", encoding="utf-8")
    Path(job["status"]).write_text('{"state": "done"}', encoding="utf-8")

    fix_training.start(job)

    assert Path(job["log"]).read_text(encoding="utf-8") == "what the training printed\n"
    assert fix_training.read_status(job) is None


def test_a_training_is_known_to_be_running_by_its_program_from_any_launch(monkeypatch, tmp_path):
    _started(monkeypatch)
    job = _work(tmp_path)

    trainer = fix_training.start(job)

    assert trainer.running()
    assert fix_training.trainer_of(job).running()
    monkeypatch.setattr(fix_training, "process_started", lambda pid: None)
    assert not fix_training.trainer_of(job).running()


def test_a_program_that_took_a_finished_trainings_number_is_not_the_training(
        monkeypatch, tmp_path):
    _started(monkeypatch)
    job = _work(tmp_path)
    fix_training.start(job)

    monkeypatch.setattr(fix_training, "process_started", lambda pid: 2222)

    assert not fix_training.trainer_of(job).running()


def test_no_training_was_ever_started_where_there_is_no_record_of_one(tmp_path):
    assert fix_training.trainer_of(_work(tmp_path)) is None


def test_the_python_that_crops_is_the_one_comfyuis_own_launcher_runs_comfyui_on(
        monkeypatch, tmp_path):
    scripts = tmp_path / "ComfyUIApp" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "comfyui_server.py").write_text(
        "from pathlib import Path\n\n\ndef comfyui_python():\n"
        "    return Path('C:/envs/comfy/python.exe')\n", encoding="utf-8")
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUIApp" / "ComfyUI")

    assert fix_training.comfyui_python() == Path("C:/envs/comfy/python.exe")


def test_stopping_a_training_ends_its_program_and_everything_it_started(monkeypatch, tmp_path):
    _started(monkeypatch)
    trainer = fix_training.start(_work(tmp_path))
    ran = []
    monkeypatch.setattr(fix_training.subprocess, "run",
                        lambda args, **options: ran.append((args, options)))

    trainer.stop()

    ((args, options),) = ran
    assert args == ["taskkill", "/F", "/T", "/PID", "4321"]
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_a_training_that_has_ended_is_not_stopped_again(monkeypatch, tmp_path):
    _started(monkeypatch)
    trainer = fix_training.start(_work(tmp_path))
    monkeypatch.setattr(fix_training, "process_started", lambda pid: None)
    ran = []
    monkeypatch.setattr(fix_training.subprocess, "run", lambda args, **options: ran.append(args))

    trainer.stop()

    assert ran == []


def test_how_long_trainings_take_is_kept_so_the_next_can_be_counted_down(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    assert fix_training.typical_seconds() is None

    for seconds in (3000.0, 2400.0, 2600.0):
        fix_training.note_duration(seconds)

    assert fix_training.typical_seconds() == 2600.0


def _job_kept(monkeypatch, tmp_path, part, **status) -> dict:
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path)
    work = tmp_path / part
    work.mkdir()
    job = {"part": part, "work": str(work), "status": str(work / "status.json"),
           "job_file": str(work / "job.json")}
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    if status:
        Path(job["status"]).write_text(json.dumps(status), encoding="utf-8")
    return job


def test_every_training_ever_started_is_found_by_its_job(monkeypatch, tmp_path):
    hands = _job_kept(monkeypatch, tmp_path, "hands")
    (tmp_path / "not a training").mkdir()

    assert fix_training.trainings() == [hands]


def test_a_lora_made_while_the_app_was_closed_is_taken_once(monkeypatch, tmp_path):
    job = _job_kept(monkeypatch, tmp_path, "hands", state="done",
                    lora="hands 2026-10-21 1500.safetensors")

    assert fix_training.untaken_lora(job) == fix_training.lora_of(
        {"lora": "hands 2026-10-21 1500.safetensors"})
    fix_training.mark_taken(job)
    assert fix_training.untaken_lora(job) is None


def test_a_training_that_did_not_finish_has_no_lora_to_take(monkeypatch, tmp_path):
    job = _job_kept(monkeypatch, tmp_path, "hands", state="failed", message="No photos.")

    assert fix_training.untaken_lora(job) is None


def test_the_trainers_word_is_read_back_and_is_none_until_it_has_said_something(tmp_path):
    job = {"status": str(tmp_path / "status.json")}
    assert fix_training.read_status(job) is None

    Path(job["status"]).write_text('{"state": "training", "done": 3, "total": 10}', encoding="utf-8")
    assert fix_training.read_status(job) == {"state": "training", "done": 3, "total": 10}
