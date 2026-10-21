from __future__ import annotations

import json
import subprocess
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
        options["stdout"].write(b"what the step printed\n")
        return "trainer"

    monkeypatch.setattr(fix_training.subprocess, "Popen", popen)
    return started


def _work(tmp_path) -> dict:
    work = tmp_path / "work"
    return {"work": str(work), "status": str(work / "status.json"),
            "log": str(work / "training.log")}


def test_cropping_runs_under_comfyuis_python_with_no_window_and_prints_into_the_log(
        monkeypatch, tmp_path):
    started = _started(monkeypatch)
    monkeypatch.setattr(fix_training, "comfyui_python", lambda: Path("C:/comfyui/python.exe"))
    job = _work(tmp_path)

    assert fix_training.start(job, "crop") == "trainer"

    ((args, options),) = started
    assert args[:3] == [str(Path("C:/comfyui/python.exe")), str(fix_training.TRAINER), "crop"]
    assert json.loads(Path(args[3]).read_text(encoding="utf-8")) == job
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert Path(job["log"]).read_text(encoding="utf-8") == "what the step printed\n"


def test_training_runs_under_the_training_python_and_adds_to_the_cropping_log(
        monkeypatch, tmp_path):
    started = _started(monkeypatch)
    monkeypatch.setattr(config, "LORA_TRAINING_PYTHON", Path("C:/training/python.exe"))
    job = _work(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["log"]).write_text("cropped\n", encoding="utf-8")

    fix_training.start(job, "train")

    ((args, _options),) = started
    assert args[:3] == [str(Path("C:/training/python.exe")), str(fix_training.TRAINER), "train"]
    assert Path(job["log"]).read_text(encoding="utf-8") == "cropped\nwhat the step printed\n"


def test_a_new_training_starts_its_log_and_its_word_afresh(monkeypatch, tmp_path):
    _started(monkeypatch)
    monkeypatch.setattr(fix_training, "comfyui_python", lambda: Path("C:/comfyui/python.exe"))
    job = _work(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["log"]).write_text("the last training\n", encoding="utf-8")
    Path(job["status"]).write_text('{"state": "done"}', encoding="utf-8")

    fix_training.start(job, "crop")

    assert Path(job["log"]).read_text(encoding="utf-8") == "what the step printed\n"
    assert fix_training.read_status(job) is None


def test_the_python_that_crops_is_the_one_comfyuis_own_launcher_runs_comfyui_on(
        monkeypatch, tmp_path):
    scripts = tmp_path / "ComfyUIApp" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "comfyui_server.py").write_text(
        "from pathlib import Path\n\n\ndef comfyui_python():\n"
        "    return Path('C:/envs/comfy/python.exe')\n", encoding="utf-8")
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUIApp" / "ComfyUI")

    assert fix_training.comfyui_python() == Path("C:/envs/comfy/python.exe")


def test_the_steps_the_app_runs_are_the_ones_the_trainer_has():
    assert list(fix_training.STEPS) == list(fix_lora_trainer.STEPS)


def test_the_trainers_word_is_read_back_and_is_none_until_it_has_said_something(tmp_path):
    job = {"status": str(tmp_path / "status.json")}
    assert fix_training.read_status(job) is None

    Path(job["status"]).write_text('{"state": "training", "done": 3, "total": 10}', encoding="utf-8")
    assert fix_training.read_status(job) == {"state": "training", "done": 3, "total": 10}
