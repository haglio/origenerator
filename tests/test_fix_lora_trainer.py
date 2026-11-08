from __future__ import annotations

import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from origenerator import card_claim
from tests.training_machine import AComfyUIJobComesOnceAStateIsSaved, TrainingMachine
from tools import fix_lora_trainer


@pytest.fixture(autouse=True)
def _a_claim_of_the_tests_own(tmp_path, monkeypatch):
    monkeypatch.setattr(card_claim, "CLAIM", tmp_path / "graphics_card_claim.json")


def _image(size=(64, 48)) -> bytes:
    written = io.BytesIO()
    Image.new("RGB", size).save(written, "PNG")
    return written.getvalue()


def _job(tmp_path, images: dict, shared: dict | None = None) -> dict:
    folders = {tmp_path / "hands": images, tmp_path / "shared": shared or {}}
    for folder, these in folders.items():
        folder.mkdir()
        for name, data in these.items():
            (folder / name).write_bytes(data)
    work = tmp_path / "work"
    return {"part": "hands",
            "images": [str(folder / name) for folder, these in folders.items() for name in these],
            "images_folders": [str(folder) for folder in folders], "image_stamps": {},
            "trained": str(work / "trained.json"),
            "caption": "close-up photo of hands",
            "detector": str(tmp_path / "hand_yolov8s.pt"), "work": str(work),
            "status": str(work / "status.json"), "log": str(work / "training.log")}


def test_a_file_that_is_no_image_stops_the_cropping_and_says_which_to_take_out_of_where(
        tmp_path):
    job = _job(tmp_path, {"fine.png": _image()}, shared={"broken.jpg": b"not an image"})

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.crop(job, find=lambda image: None)

    assert f"Take it out of {tmp_path / 'shared'}" in str(stopped.value)
    assert "broken.jpg" in str(stopped.value)


def test_images_the_detector_finds_the_part_in_none_of_stop_the_training_and_say_so(tmp_path):
    job = _job(tmp_path, {"one.png": _image(), "two.png": _image()})

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.crop(job, find=lambda image: None)

    assert "any of the 2 images" in str(stopped.value)
    assert all(folder in str(stopped.value) for folder in job["images_folders"])


def test_each_image_the_part_is_found_in_becomes_a_square_crop_with_the_fixs_caption(tmp_path):
    job = _job(tmp_path, {"found.png": _image((400, 300)), "not.png": _image()})

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
    job = _job(tmp_path, {"one.png": _image()})

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
    monkeypatch.setattr(fix_lora_trainer, "train", lambda job, machine: done.append("trained"))
    return job, done


def test_a_fix_training_waits_until_comfyuis_line_is_empty_before_it_crops(tmp_path, monkeypatch):
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=0)
    machine = TrainingMachine(waiting=[2, 0, 0, 0, 0, 0, 0, 0], memory=[100])

    fix_lora_trainer.run(job, machine)

    assert machine.claimed == 1
    assert machine.slept.count(20) == 7
    assert done[-1] == "trained"
    assert not card_claim.CLAIM.exists()


def test_a_whole_training_crops_under_comfyuis_python_and_then_trains(tmp_path, monkeypatch):
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=0)

    fix_lora_trainer.run(job, _idle())

    crop, trained = done
    assert crop[0] == "C:/comfyui/python.exe"
    assert crop[2:] == ["crop", job["job_file"]]
    assert trained == "trained"


def test_images_the_cropping_stopped_on_are_not_trained_on_and_its_reason_stands(
        tmp_path, monkeypatch):
    said = {"state": "failed", "message": "Take broken.jpg out."}
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=1, crop_says=said)
    monkeypatch.setitem(fix_lora_trainer.STEPS, "run", lambda job: fix_lora_trainer.run(job, _idle()))

    assert fix_lora_trainer.main(["run", job["job_file"]]) == 1
    assert "trained" not in done
    assert _status(job) == said


def test_a_cropping_that_quit_without_a_word_says_so_and_where_its_log_is(
        tmp_path, monkeypatch):
    job, done = _whole_run(tmp_path, monkeypatch, crop_code=3221225786)

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.run(job, _idle())

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
    (crops / "0000.jpg").write_bytes(_image())
    return dict(job, sd_scripts=str(scripts), base_model="base.safetensors",
                lora_folder=str(tmp_path / "loras" / "fixes"), output_name="hands 1.1",
                lora=r"fixes\hands 1.1.safetensors", save_every=100)


def _idle():
    return TrainingMachine(waiting=[0], memory=[100])


_BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def _at_the_suites_priority(command, **options):
    options["creationflags"] = options.get("creationflags", 0) & ~_BELOW_NORMAL
    return subprocess.Popen(command, **options)


_MAKES_THE_LORA = ("import sys\nargs = sys.argv[1:]\nout = args[args.index('--output_dir') + 1]\n"
                   "open(out + '/hands 1.1.safetensors', 'wb').write(b'lora')\n")


def test_the_training_starts_below_normal_priority_and_without_a_window(tmp_path):
    started = {}
    job = _cropped_job(tmp_path, "")

    class Finished:
        stdout = io.BytesIO(b"")
        returncode = 0

        def poll(self):
            return 0

        def wait(self):
            return 0

    def start(command, **options):
        started.update(options)
        Path(fix_lora_trainer.output_folder(job), "hands 1.1.safetensors").write_bytes(b"lora")
        return Finished()

    fix_lora_trainer.train(job, _idle(), popen=start)

    assert started["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS
    assert started["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert started["cwd"] == job["sd_scripts"]


@pytest.mark.parametrize("said", ["torch.OutOfMemoryError: CUDA out of memory.",
                                  "torch.AcceleratorError: CUDA error: out of memory"])
def test_a_training_the_graphics_card_runs_out_of_memory_for_says_so(tmp_path, said):
    job = _cropped_job(tmp_path, f"import sys\nprint({said!r})\nsys.exit(1)\n")

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.train(job, _idle(), popen=_at_the_suites_priority)

    assert "graphics card ran out of memory" in str(stopped.value)


def test_a_training_that_keeps_breaking_gives_up_and_names_the_log(tmp_path):
    job = _cropped_job(tmp_path, "import sys\nprint('ValueError: bad option')\nsys.exit(1)\n")

    with pytest.raises(fix_lora_trainer.Stopped) as stopped:
        fix_lora_trainer.train(job, _idle(), popen=_at_the_suites_priority)

    assert "Nothing about your images caused it" in str(stopped.value)
    assert job["log"] in str(stopped.value)


def test_a_training_says_how_many_of_its_steps_are_done_as_it_goes(tmp_path):
    job = _cropped_job(tmp_path, "import sys\n"
                                 "print('steps:  30%|###       | 3/1500 [00:03<00:07]')\n"
                                 "sys.stdout.flush()\nsys.exit(1)\n")

    with pytest.raises(fix_lora_trainer.Stopped):
        fix_lora_trainer.train(job, _idle(), popen=_at_the_suites_priority)

    assert _status(job) == {"state": "training", "done": 3, "total": 1500}


def test_a_finished_training_installs_its_lora_in_comfyuis_fix_folder_and_names_it(
        tmp_path, capfd):
    job = _cropped_job(tmp_path, "print('steps:  50%|#####     | 5/10 [00:05<00:05]')\n" + _MAKES_THE_LORA)

    fix_lora_trainer.train(job, _idle(), popen=_at_the_suites_priority)

    assert Path(job["lora_folder"], "hands 1.1.safetensors").read_bytes() == b"lora"
    assert _status(job) == {"state": "done", "lora": r"fixes\hands 1.1.safetensors"}
    assert "5/10" in capfd.readouterr().out


def test_a_finished_training_keeps_a_record_of_the_images_it_trained_on(tmp_path):
    stamps = {"hands/one.png": [10, 20], "shared/two.png": [30, 40]}
    job = dict(_cropped_job(tmp_path, _MAKES_THE_LORA), image_stamps=stamps)

    fix_lora_trainer.train(job, _idle(), popen=_at_the_suites_priority)

    assert json.loads(Path(job["trained"]).read_text(encoding="utf-8")) == {
        "photo_stamps": stamps, "lora": r"fixes\hands 1.1.safetensors"}


_SAVES_A_STATE_THEN_WAITS_UNLESS_RESUMED = """
import os, sys, time
args = sys.argv[1:]
out = args[args.index("--output_dir") + 1]
os.makedirs(os.path.join(out, "hands 1.1-step00000100-state"), exist_ok=True)
print("asked for", args[args.index("--max_train_steps") + 1], "steps", flush=True)
if "--resume" not in args:
    time.sleep(120)
print("resumed from", args[args.index("--resume") + 1], "skipping:", "--skip_until_initial_step" in args, flush=True)
open(os.path.join(out, "hands 1.1.safetensors"), "wb").write(b"lora")
"""


def test_a_fix_training_stopped_for_a_comfyui_job_resumes_where_its_newest_state_left_off(
        tmp_path, capsys):
    job = _cropped_job(tmp_path, _SAVES_A_STATE_THEN_WAITS_UNLESS_RESUMED)
    state = fix_lora_trainer.output_folder(job) / "hands 1.1-step00000100-state"
    machine = AComfyUIJobComesOnceAStateIsSaved(state)
    killed = []

    def kill(process):
        killed.append(process.pid)
        process.kill()

    fix_lora_trainer.train(job, machine, popen=_at_the_suites_priority, kill=kill)

    said = capsys.readouterr().out
    assert len(killed) == 1
    assert said.count("asked for 1500 steps") == 2
    assert f"resumed from {state} skipping: True" in said
    assert Path(job["lora_folder"], "hands 1.1.safetensors").is_file()


def test_a_part_is_cropped_to_a_square_twice_its_size_around_it():
    assert fix_lora_trainer.square_crop((100, 200, 160, 240), (1000, 800)) == (70, 160, 190, 280)


def test_a_crop_near_the_images_edge_or_bigger_than_it_stays_inside_it():
    assert fix_lora_trainer.square_crop((0, 0, 60, 40), (1000, 800)) == (0, 0, 120, 120)
    assert fix_lora_trainer.square_crop((100, 100, 900, 700), (1000, 800)) == (100, 0, 900, 800)


def _option(command, name):
    return command[command.index(name) + 1]


def _training(**more) -> dict:
    return {"sd_scripts": "C:/sd-scripts", "base_model": "C:/models/base.safetensors",
            "work": "C:/work", "output_name": "hands 1.1", "steps": 1500, "save_every": 100, **more}


def test_the_training_makes_an_sdxl_lora_from_the_crops_saving_its_state_as_it_goes():
    command = fix_lora_trainer.train_command(_training(), "C:/work/images", python="py.exe")

    assert command[:2] == ["py.exe", "C:/sd-scripts/sdxl_train_network.py"]
    assert _option(command, "--pretrained_model_name_or_path") == "C:/models/base.safetensors"
    assert _option(command, "--train_data_dir") == "C:/work/images"
    assert _option(command, "--output_dir") == str(Path("C:/work", "output"))
    assert _option(command, "--output_name") == "hands 1.1"
    assert _option(command, "--network_module") == "networks.lora"
    assert _option(command, "--max_train_steps") == "1500"
    assert _option(command, "--save_every_n_steps") == "100"
    assert "--save_state" in command
    assert "--resume" not in command


def test_a_resumed_training_picks_up_its_own_step_count_and_learning_rate_from_the_state():
    state = Path("C:/work/output/hands 1.1-step00000300-state")

    command = fix_lora_trainer.train_command(_training(), "C:/work/images", resume=state, python="py.exe")

    assert _option(command, "--resume") == str(state)
    assert "--skip_until_initial_step" in command
    assert _option(command, "--max_train_steps") == "1500"


def test_the_steps_are_ten_rounds_of_the_crops_each_seen_its_share_of_times():
    assert fix_lora_trainer.training_steps(10) == 1500
    assert fix_lora_trainer.training_steps(400) == 4000


def test_the_training_writes_its_log_as_utf8_so_a_line_in_japanese_does_not_stop_it():
    assert fix_lora_trainer.training_environment({"PATH": "C:/bin"}) == {
        "PATH": "C:/bin", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def test_fewer_images_are_each_seen_more_times_and_every_image_at_least_once():
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 10) == "C:/work/15_hands"
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 100) == "C:/work/2_hands"
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 400) == "C:/work/1_hands"
