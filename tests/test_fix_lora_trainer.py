from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from tools import fix_lora_trainer


def _picture(size=(64, 48)) -> bytes:
    written = io.BytesIO()
    Image.new("RGB", size).save(written, "PNG")
    return written.getvalue()


def _job(tmp_path, photos: dict, shared: dict | None = None) -> dict:
    folders = {tmp_path / "hands": photos, tmp_path / "shared": shared or {}}
    for folder, these in folders.items():
        folder.mkdir()
        for name, data in these.items():
            (folder / name).write_bytes(data)
    work = tmp_path / "work"
    return {"part": "hands",
            "photos": [str(folder / name) for folder, these in folders.items() for name in these],
            "photos_folders": [str(folder) for folder in folders],
            "caption": "close-up photo of hands",
            "detector": str(tmp_path / "hand_yolov8s.pt"), "work": str(work),
            "status": str(work / "status.json"), "log": str(work / "training.log")}


def test_a_photo_that_is_no_picture_stops_the_cropping_and_says_which_to_take_out_of_where(
        tmp_path):
    job = _job(tmp_path, {"fine.png": _picture()}, shared={"broken.jpg": b"not a picture"})

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.crop(job, find=lambda image: None)

    assert f"Take it out of {tmp_path / 'shared'}" in str(stopped.value)
    assert "broken.jpg" in str(stopped.value)


def test_photos_the_detector_finds_the_part_in_none_of_stop_the_training_and_say_so(tmp_path):
    job = _job(tmp_path, {"one.png": _picture(), "two.png": _picture()})

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.crop(job, find=lambda image: None)

    assert "any of the 2 photos" in str(stopped.value)
    assert all(folder in str(stopped.value) for folder in job["photos_folders"])


def test_each_photo_the_part_is_found_in_becomes_a_square_crop_with_the_fixs_caption(tmp_path):
    job = _job(tmp_path, {"found.png": _picture((400, 300)), "not.png": _picture()})

    kept = fix_lora_trainer.crop(
        job, find=lambda image: (10, 10, 50, 40) if image.size == (400, 300) else None)

    crops = tmp_path / "work" / "crops"
    assert kept == 1
    with Image.open(crops / "0000.jpg") as cropped:
        assert cropped.size == (1024, 1024)
    assert (crops / "0000.txt").read_text(encoding="utf-8") == "close-up photo of hands"
    assert sorted(path.name for path in crops.iterdir()) == ["0000.jpg", "0000.txt"]


def test_a_detector_that_cannot_be_read_says_so_and_where_an_agent_can_read_why(
        tmp_path, monkeypatch):
    def unreadable(path):
        raise AttributeError("Can't get attribute 'Segment26'")

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=unreadable))
    job = _job(tmp_path, {"one.png": _picture()})

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.crop(job)

    assert "hand_yolov8s.pt" in str(stopped.value)
    assert job["log"] in str(stopped.value)


def _job_file(tmp_path) -> tuple[dict, str]:
    job = _job(tmp_path, {})
    (tmp_path / "work").mkdir()
    path = tmp_path / "work" / "job.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    return job, str(path)


def _status(job) -> dict:
    with open(job["status"], encoding="utf-8") as read:
        return json.load(read)


def _whole_run(tmp_path, monkeypatch, *, crop_code: int, crop_says=None):
    job, _path = _job_file(tmp_path)
    job.update(comfyui_python="C:/comfyui/python.exe", job_file=str(tmp_path / "job.json"))
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    done = []

    def cropping(command, **options):
        done.append(command)
        if crop_says is not None:
            Path(job["status"]).write_text(json.dumps(crop_says), encoding="utf-8")
        return types.SimpleNamespace(returncode=crop_code)

    monkeypatch.setattr(fix_lora_trainer.subprocess, "run", cropping)
    monkeypatch.setattr(fix_lora_trainer, "train", lambda job: done.append("trained"))
    return job, done


def test_a_whole_training_crops_under_comfyuis_python_and_then_trains(tmp_path, monkeypatch):
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=0)

    fix_lora_trainer.run(job)

    crop, trained = done
    assert crop[0] == "C:/comfyui/python.exe"
    assert crop[2:] == ["crop", job["job_file"]]
    assert trained == "trained"


def test_photos_the_cropping_stopped_on_are_not_trained_on_and_its_reason_stands(
        tmp_path, monkeypatch):
    said = {"state": "failed", "message": "Take broken.jpg out."}
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=1, crop_says=said)
    monkeypatch.setitem(fix_lora_trainer.STEPS, "run", fix_lora_trainer.run)

    assert fix_lora_trainer.main(["run", job["job_file"]]) == 1
    assert "trained" not in done
    assert _status(job) == said


def test_a_cropping_that_quit_without_a_word_says_so_and_where_its_log_is(
        tmp_path, monkeypatch):
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=3221225786)

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.run(job)

    assert "quit without saying why" in str(stopped.value)
    assert job["log"] in str(stopped.value)
    assert "trained" not in done


def test_a_step_that_stops_leaves_its_reason_where_the_app_reads_it(tmp_path, monkeypatch):
    def stops(job):
        raise fix_lora_trainer.Stopped("Take broken.jpg out.")

    monkeypatch.setitem(fix_lora_trainer.STEPS, "crop", stops)
    job, path = _job_file(tmp_path)

    assert fix_lora_trainer.main(["crop", path]) == 1
    assert _status(job) == {"state": "failed", "message": "Take broken.jpg out."}


def test_a_step_that_breaks_says_what_it_was_doing_and_prints_why_into_the_log(
        tmp_path, monkeypatch, capsys):
    def breaks(job):
        raise KeyError("no such column")

    monkeypatch.setitem(fix_lora_trainer.STEPS, "run", breaks)
    job, path = _job_file(tmp_path)

    assert fix_lora_trainer.main(["run", path]) == 1
    assert _status(job)["state"] == "failed"
    assert "while training" in _status(job)["message"]
    assert job["log"] in _status(job)["message"]
    assert "no such column" in capsys.readouterr().err


def _cropped_job(tmp_path, sd_script: str) -> dict:
    job = _job(tmp_path, {})
    scripts = tmp_path / "sd-scripts"
    scripts.mkdir()
    (scripts / "sdxl_train_network.py").write_text(sd_script, encoding="utf-8")
    crops = tmp_path / "work" / "crops"
    crops.mkdir(parents=True)
    (crops / "0000.jpg").write_bytes(_picture())
    return dict(job, sd_scripts=str(scripts), base_model="base.safetensors",
                output_dir=str(tmp_path / "loras"), output_name="hands 2026-10-21 1500")


@pytest.mark.parametrize("said", ["torch.OutOfMemoryError: CUDA out of memory.",
                                  "torch.AcceleratorError: CUDA error: out of memory"])
def test_a_training_the_graphics_card_runs_out_of_memory_for_says_so(tmp_path, said):
    job = _cropped_job(tmp_path, f"import sys\nprint({said!r})\nsys.exit(1)\n")

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.train(job)

    assert "graphics card ran out of memory" in str(stopped.value)


def test_a_training_that_breaks_otherwise_clears_the_photos_and_names_the_log(tmp_path):
    job = _cropped_job(tmp_path, "import sys\nprint('ValueError: bad option')\nsys.exit(1)\n")

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.train(job)

    assert "Nothing about your photos caused it" in str(stopped.value)
    assert job["log"] in str(stopped.value)


def test_a_training_says_how_many_of_its_steps_are_done_as_it_goes(tmp_path):
    job = _cropped_job(tmp_path, "import sys\n"
                                 "print('steps:  30%|###       | 3/10 [00:03<00:07]')\n"
                                 "sys.stdout.flush()\nsys.exit(1)\n")

    with pytest.raises(fix_lora_trainer.Stopped):
        fix_lora_trainer.train(job)

    assert _status(job) == {"state": "training", "done": 3, "total": 10}


def test_a_finished_training_names_its_lora_and_passes_on_what_it_printed(tmp_path, capfd):
    job = _cropped_job(tmp_path, "print('steps:  50%|#####     | 5/10 [00:05<00:05]')\n")

    fix_lora_trainer.train(job)

    assert _status(job) == {"state": "done", "lora": "hands 2026-10-21 1500.safetensors"}
    assert "5/10" in capfd.readouterr().out


def test_a_part_is_cropped_to_a_square_twice_its_size_around_it():
    assert fix_lora_trainer.square_crop((100, 200, 160, 240), (1000, 800)) == (70, 160, 190, 280)


def test_a_crop_near_the_photos_edge_or_bigger_than_it_stays_inside_it():
    assert fix_lora_trainer.square_crop((0, 0, 60, 40), (1000, 800)) == (0, 0, 120, 120)
    assert fix_lora_trainer.square_crop((100, 100, 900, 700), (1000, 800)) == (100, 0, 900, 800)


def _option(command, name):
    return command[command.index(name) + 1]


def test_the_training_makes_an_sdxl_lora_from_the_crops_in_comfyuis_lora_folder():
    job = {"sd_scripts": "C:/sd-scripts", "base_model": "C:/models/base.safetensors",
           "output_dir": "C:/loras/fixes", "output_name": "hands 2026-10-19 0130"}

    command = fix_lora_trainer.train_command(job, "C:/work/dataset", python="py.exe")

    assert command[:2] == ["py.exe", "C:/sd-scripts/sdxl_train_network.py"]
    assert _option(command, "--pretrained_model_name_or_path") == "C:/models/base.safetensors"
    assert _option(command, "--train_data_dir") == "C:/work/dataset"
    assert _option(command, "--output_dir") == "C:/loras/fixes"
    assert _option(command, "--output_name") == "hands 2026-10-19 0130"
    assert _option(command, "--network_module") == "networks.lora"


def test_the_training_writes_its_log_as_utf8_so_a_line_in_japanese_does_not_stop_it():
    assert fix_lora_trainer.training_environment({"PATH": "C:/bin"}) == {
        "PATH": "C:/bin", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def test_fewer_photos_are_each_seen_more_times_and_every_photo_at_least_once():
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 10) == "C:/work/15_hands"
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 100) == "C:/work/2_hands"
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 400) == "C:/work/1_hands"
