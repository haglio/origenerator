from __future__ import annotations

import json
import types
from pathlib import Path

from origenerator import config, fix_training, lora_training
from origenerator.workflows import detail_parts
from tools import fix_lora_trainer


def _part(name):
    return next(part for part in detail_parts.part_table() if part.name == name)


def test_each_fix_takes_its_photos_from_a_folder_of_fixes_named_for_it_in_lowercase():
    assert fix_training.photos_folder(_part("hands")).parts[-2:] == ("fixes", "hands")


def test_only_photos_in_a_fixs_folder_are_trained_on(tmp_path):
    for name in ("b.jpg", "a.PNG", "notes.txt", "c.webp"):
        (tmp_path / name).write_bytes(b"")

    assert [path.name for path in fix_training.photo_files(tmp_path)] == ["a.PNG", "b.jpg", "c.webp"]
    assert fix_training.photo_files(tmp_path / "not made yet") == []


def test_a_fix_trains_on_its_own_photos_and_the_shared_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path)
    for folder, name in (("hands", "own.jpg"), ("shared", "everyone.jpg"), ("faces", "other.jpg")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).write_bytes(b"")

    assert [path.name for path in fix_training.training_photos(_part("hands"))] == [
        "own.jpg", "everyone.jpg"]


def test_a_fix_its_settings_keep_off_the_shared_folder_trains_on_its_own_photos_alone(
        monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path)
    for folder in ("alpha", "shared"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / f"{folder}.jpg").write_bytes(b"")
    (alpha,) = detail_parts.part_table({"detail_fix_parts": [
        {"name": "alpha", "shared_photos": False}]})[-1:]

    assert [path.name for path in fix_training.training_photos(alpha)] == ["alpha.jpg"]


def test_a_fix_is_untrained_until_a_training_keeps_its_photos_then_current_until_one_changes(
        monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path / "fixes")
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    hands = _part("hands")
    (tmp_path / "fixes" / "shared").mkdir(parents=True)
    (tmp_path / "fixes" / "shared" / "one.jpg").write_bytes(b"one")
    assert fix_training.training_state(hands) is lora_training.TrainingState.UNTRAINED

    record = tmp_path / "fix training" / "hands" / "trained.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"photo_stamps": fix_training.photo_stamps(hands)}),
                      encoding="utf-8")
    assert fix_training.training_state(hands) is lora_training.TrainingState.CURRENT

    (tmp_path / "fixes" / "shared" / "one.jpg").write_bytes(b"one, retouched")
    assert fix_training.training_state(hands) is lora_training.TrainingState.OUT_OF_DATE


def test_the_next_fix_to_train_is_the_first_with_photos_and_a_detector_not_trained_on_them(
        monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path / "fixes")
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["face_yolov8m.pt", "hand_yolov8s.pt"])
    for folder in ("faces", "hands", "teeth"):
        (tmp_path / "fixes" / folder).mkdir(parents=True)
        (tmp_path / "fixes" / folder / "one.jpg").write_bytes(b"one")
    record = tmp_path / "fix training" / "faces" / "trained.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"photo_stamps": fix_training.photo_stamps(_part("faces"))}),
                      encoding="utf-8")

    assert fix_training.fix_to_train().name == "hands"

    (tmp_path / "fixes" / "hands" / "one.jpg").unlink()
    assert fix_training.fix_to_train() is None


def test_a_training_job_names_the_fixs_photos_its_detector_and_the_model_to_train_for(
        monkeypatch, tmp_path, installed_models):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["hand_yolov8s.pt"])
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path)
    for folder, name in (("hands", "one.jpg"), ("shared", "two.jpg")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).write_bytes(b"")
    monkeypatch.setattr(config, "LORA_TRAINING_SCRIPTS", Path("C:/sd-scripts"))
    models = config.COMFYUI_DIR / "models"

    job = fix_training.training_job(_part("hands"), "base.safetensors")

    assert job["photos"] == [str(tmp_path / "hands" / "one.jpg"), str(tmp_path / "shared" / "two.jpg")]
    assert job["photos_folders"] == [str(tmp_path / "hands"), str(tmp_path / "shared")]
    assert list(job["photo_stamps"]) == ["hands/one.jpg", "shared/two.jpg"]
    assert job["automatic"] is False
    assert fix_training.training_job(_part("hands"), "base.safetensors",
                                     automatic=True)["automatic"] is True
    assert job["detector"] == str(models / "ultralytics" / "bbox" / "hand_yolov8s.pt")
    assert job["base_model"] == str(models / "checkpoints" / "base.safetensors")
    assert job["output_dir"] == str(models / "loras" / "fixes")
    assert job["output_name"] == "hands 1.0"
    assert job["display_name"] == "Hands fix 1.0"
    assert job["lora"] == str(Path("fixes") / "hands 1.0.safetensors")
    assert job["sd_scripts"] == str(Path("C:/sd-scripts"))


def test_a_fix_trained_again_is_named_by_the_version_after_its_newest_lora(
        monkeypatch, tmp_path, installed_models):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["hand_yolov8s.pt"])
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path)
    installed_models.add("loras", "fixes/hands 2026-10-19 0130.safetensors", arch="sdxl", lora=True)

    assert fix_training.training_job(_part("hands"), "base.safetensors")["output_name"] == "hands 1.1"


def _started(monkeypatch) -> list:
    started = []

    def popen(args, **options):
        started.append((args, options))
        options["stdout"].write(b"what the training printed\n")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(lora_training.subprocess, "Popen", popen)
    monkeypatch.setattr(lora_training, "process_started", lambda pid: 1111 if pid == 4321 else None)
    monkeypatch.setattr(fix_training, "comfyui_python", lambda: Path("C:/comfyui/python.exe"))
    monkeypatch.setattr(config, "LORA_TRAINING_PYTHON", Path("C:/training/python.exe"))
    return started


def test_a_fix_trains_whole_under_the_training_python_and_tells_its_program_comfyuis(
        monkeypatch, tmp_path):
    started = _started(monkeypatch)
    job = {"part": "hands", **lora_training.work_files(tmp_path / "work")}

    fix_training.start(job)

    ((args, _options),) = started
    assert args == [str(Path("C:/training/python.exe")), str(fix_training.TRAINER), "run",
                    job["job_file"]]
    assert args[2] in fix_lora_trainer.STEPS
    assert json.loads(Path(job["job_file"]).read_text(encoding="utf-8")) == dict(
        job, comfyui_python=str(Path("C:/comfyui/python.exe")))


def test_the_python_that_crops_is_the_one_comfyuis_own_launcher_runs_comfyui_on(
        monkeypatch, tmp_path):
    scripts = tmp_path / "ComfyUIApp" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "comfyui_server.py").write_text(
        "from pathlib import Path\n\n\ndef comfyui_python():\n"
        "    return Path('C:/envs/comfy/python.exe')\n", encoding="utf-8")
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUIApp" / "ComfyUI")

    assert fix_training.comfyui_python() == Path("C:/envs/comfy/python.exe")


def test_how_long_fix_trainings_take_is_kept_with_the_fix_trainings(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    assert fix_training.typical_seconds() is None

    for seconds in (3000.0, 2400.0, 2600.0):
        fix_training.note_duration(seconds)

    assert fix_training.typical_seconds() == 2600.0
    assert (tmp_path / "fix training" / "durations.json").is_file()


def test_every_fix_training_ever_started_is_found_among_the_fix_trainings(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path)
    work = tmp_path / "hands"
    work.mkdir()
    job = {"part": "hands", **lora_training.work_files(work)}
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")

    assert fix_training.trainings() == [job]
    assert fix_training.running_trainings() == []


def _training_of(monkeypatch, tmp_path, **job) -> None:
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path)
    work = tmp_path / "hands"
    work.mkdir()
    files = lora_training.work_files(work)
    Path(files["job_file"]).write_text(json.dumps({"part": "hands", **files, **job}),
                                       encoding="utf-8")


def test_a_fixs_lora_was_trained_on_the_model_its_training_names(monkeypatch, tmp_path):
    checkpoints = config.COMFYUI_DIR / "models" / "checkpoints"
    _training_of(monkeypatch, tmp_path, output_name="hands 1.1",
                 base_model=str(checkpoints / "styles" / "base.safetensors"))

    assert fix_training.trained_on(str(Path("fixes") / "hands 1.1.safetensors")) == (
        str(Path("styles") / "base.safetensors"))


def test_a_lora_no_training_names_was_trained_on_no_model_anyone_knows(monkeypatch, tmp_path):
    _training_of(monkeypatch, tmp_path)

    assert fix_training.trained_on(str(Path("fixes") / "hands 1.2.safetensors")) is None
