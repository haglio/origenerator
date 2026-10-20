from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from origenerator import config, fix_training
from origenerator.workflows import detail_parts


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
    assert job["detector"] == str(models / "ultralytics" / "bbox" / "hand_yolov8s.pt")
    assert job["base_model"] == str(models / "checkpoints" / "base.safetensors")
    assert job["output_dir"] == str(models / "loras" / "fixes")
    assert job["output_name"] == "hands 2026-10-19 0130"
    assert job["sd_scripts"] == str(Path("C:/sd-scripts"))


def test_training_runs_the_trainer_under_the_training_python_with_no_window(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(fix_training.subprocess, "Popen",
                        lambda args, **options: started.append((args, options)) or "trainer")
    monkeypatch.setattr(config, "LORA_TRAINING_PYTHON", Path("C:/training/python.exe"))
    job = {"work": str(tmp_path / "work"), "status": str(tmp_path / "work" / "status.json")}

    assert fix_training.start(job) == "trainer"

    ((args, options),) = started
    assert args[:2] == [str(Path("C:/training/python.exe")), str(fix_training.TRAINER)]
    assert json.loads(Path(args[2]).read_text(encoding="utf-8")) == job
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_the_trainers_word_is_read_back_and_is_none_until_it_has_said_something(tmp_path):
    job = {"status": str(tmp_path / "status.json")}
    assert fix_training.read_status(job) is None

    Path(job["status"]).write_text('{"state": "training", "done": 3, "total": 10}', encoding="utf-8")
    assert fix_training.read_status(job) == {"state": "training", "done": 3, "total": 10}
