from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from tools import card_claim, look_lora_trainer


@pytest.fixture(autouse=True)
def _a_claim_of_the_tests_own(tmp_path, monkeypatch):
    monkeypatch.setattr(card_claim, "CLAIM", tmp_path / "graphics_card_claim.json")


def _picture(size=(1024, 768), color=(200, 30, 30), kind="PNG") -> bytes:
    written = io.BytesIO()
    Image.new("RGB", size, color).save(written, kind)
    return written.getvalue()


def _job(tmp_path, pictures: dict | None = None, **more) -> dict:
    source = tmp_path / "pictures"
    source.mkdir(exist_ok=True)
    for name, data in (pictures or {}).items():
        (source / name).write_bytes(data)
    work = tmp_path / "work"
    return {
        "base": "Example Look", "pictures_folder": str(source), "picture_stamps": {},
        "output_name": "Example Look 1.1", "lora_folder": str(tmp_path / "loras"),
        "lora": "Example Look 1.1.safetensors", "display_name": "Example Look 1.1",
        "trigger_words": ["zz"], "base_model": str(tmp_path / "raw.safetensors"),
        "text_encoder": str(tmp_path / "te.safetensors"), "vae": str(tmp_path / "vae.safetensors"),
        "scripts": str(tmp_path / "musubi"), "steps": 1500, "save_every": 25,
        "comfyui": "http://127.0.0.1:8188",
        "work": str(work), "status": str(work / "status.json"), "log": str(work / "training.log"),
        "job_file": str(work / "job.json"), "process": str(work / "process.json"),
        "trained": str(work / "trained.json"),
        **more,
    }


def _status(job) -> dict:
    return json.loads(Path(job["status"]).read_text(encoding="utf-8"))


def _images(job) -> list[Path]:
    return sorted(Path(job["work"], "images").glob("*.jpg"))


# --- prepare ---------------------------------------------------------------------

def test_every_usable_picture_is_copied_in_as_a_jpeg_no_wider_than_the_trainer_wants(
        tmp_path, capsys):
    job = _job(tmp_path, {"qzx wide.png": _picture((3000, 1500)),
                          "qzx tiny.jpg": _picture((300, 300), kind="JPEG"),
                          "notes.txt": b"not a picture", "qzx broken.webp": b"not a picture either"})

    kept = look_lora_trainer.prepare(job)

    (copy,) = _images(job)
    with Image.open(copy) as opened:
        assert (opened.mode, opened.size) == ("RGB", (1536, 768))
    assert kept == 1
    assert _status(job) == {"state": "preparing", "done": 3, "total": 3}
    said = capsys.readouterr().out
    assert "1 copied" in said and "1 too small" in said and "1 unreadable" in said
    assert "qzx" not in said


def test_a_picture_already_copied_keeps_its_copy_and_its_description_across_trainings(tmp_path):
    job = _job(tmp_path, {"one.png": _picture()})
    look_lora_trainer.prepare(job)
    (copy,) = _images(job)
    caption = Path(job["work"], "captions", f"{copy.stem}.txt")
    caption.parent.mkdir(exist_ok=True)
    caption.write_text("a fabricated description", encoding="utf-8")
    first_written = copy.stat().st_mtime_ns

    look_lora_trainer.prepare(job)

    assert _images(job) == [copy]
    assert copy.stat().st_mtime_ns == first_written
    assert caption.read_text(encoding="utf-8") == "a fabricated description"


def test_a_picture_taken_out_of_the_folder_leaves_the_training_with_its_description(tmp_path):
    one, two = _picture(), _picture(color=(0, 0, 200))
    job = _job(tmp_path, {"one.png": one, "two.png": two})
    look_lora_trainer.prepare(job)
    kept = Path(job["work"], "images", f"{look_lora_trainer._copy_name(one)}.jpg")
    captions = Path(job["work"], "captions")
    for copy in _images(job):
        (captions / f"{copy.stem}.txt").write_text("a fabricated description", encoding="utf-8")
    Path(job["pictures_folder"], "two.png").unlink()

    look_lora_trainer.prepare(job)

    assert _images(job) == [kept]
    assert sorted(path.name for path in captions.iterdir()) == [f"{kept.stem}.txt"]


def test_a_folder_with_no_usable_picture_stops_the_training_and_says_where_to_put_them(tmp_path):
    job = _job(tmp_path, {"qzx tiny.jpg": _picture((300, 300), kind="JPEG")})

    with pytest.raises(look_lora_trainer.Stopped) as stopped:
        look_lora_trainer.prepare(job)

    assert job["pictures_folder"] in str(stopped.value)
    assert "qzx" not in str(stopped.value)


# --- describe ---------------------------------------------------------------------

def test_every_copy_without_a_description_gets_one_and_none_is_ever_printed(tmp_path, capsys):
    job = _job(tmp_path, {"one.png": _picture(), "two.png": _picture(color=(0, 0, 200))})
    look_lora_trainer.prepare(job)
    one, two = _images(job)
    captions = Path(job["work"], "captions")
    captions.mkdir(exist_ok=True)
    (captions / f"{one.stem}.txt").write_text("kept as it was", encoding="utf-8")
    described = []

    def describer(image):
        described.append(image.size)
        return "a fabricated description of the picture"

    look_lora_trainer.describe(job, describer=describer, wait_for_idle=lambda job: None)

    assert described == [(1024, 768)]
    assert (captions / f"{two.stem}.txt").read_text(encoding="utf-8") == (
        "a fabricated description of the picture")
    assert (captions / f"{one.stem}.txt").read_text(encoding="utf-8") == "kept as it was"
    assert _status(job) == {"state": "describing", "done": 2, "total": 2}
    assert "fabricated description" not in capsys.readouterr().out


def test_describing_waits_for_the_graphics_card_before_it_loads_its_model(tmp_path):
    job = _job(tmp_path, {"one.png": _picture()})
    look_lora_trainer.prepare(job)
    order = []

    look_lora_trainer.describe(job, describer=lambda image: order.append("described") or "text",
                               wait_for_idle=lambda job: order.append("waited"))

    assert order == ["waited", "described"]


# --- dataset ---------------------------------------------------------------------

def test_the_dataset_puts_the_trigger_words_before_every_description(tmp_path):
    job = _job(tmp_path, {"one.png": _picture()})
    look_lora_trainer.prepare(job)
    (copy,) = _images(job)
    captions = Path(job["work"], "captions")
    captions.mkdir(exist_ok=True)
    (captions / f"{copy.stem}.txt").write_text("a fabricated description", encoding="utf-8")

    look_lora_trainer.dataset(job)

    assert copy.with_suffix(".txt").read_text(encoding="utf-8") == "zz, a fabricated description"
    settings = Path(job["work"], "dataset.toml").read_text(encoding="utf-8")
    assert "resolution = [1024, 1024]" in settings
    assert f'image_directory = "{Path(job["work"], "images").as_posix()}"' in settings
    assert f'cache_directory = "{Path(job["work"], "cache").as_posix()}"' in settings
    assert "enable_bucket = true" in settings and "bucket_no_upscale = true" in settings


def test_a_lora_trained_on_no_word_gets_the_bare_descriptions(tmp_path):
    job = _job(tmp_path, {"one.png": _picture()}, trigger_words=[])
    look_lora_trainer.prepare(job)
    (copy,) = _images(job)
    captions = Path(job["work"], "captions")
    captions.mkdir(exist_ok=True)
    (captions / f"{copy.stem}.txt").write_text("a fabricated description", encoding="utf-8")

    look_lora_trainer.dataset(job)

    assert copy.with_suffix(".txt").read_text(encoding="utf-8") == "a fabricated description"


# --- cache ------------------------------------------------------------------------

def test_caching_runs_musubis_two_cache_programs_on_the_dataset_while_the_card_is_idle(
        tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    ran = []
    monkeypatch.setattr(look_lora_trainer.subprocess, "run",
                        lambda command, **options: ran.append(command) or types.SimpleNamespace(returncode=0))

    look_lora_trainer.cache(job, wait_for_idle=lambda job: ran.append("waited"))

    waited, latents, text = ran
    assert waited == "waited"
    assert latents[1:4] == [str(Path(job["scripts"], "src", "musubi_tuner", "krea2_cache_latents.py")),
                            "--dataset_config", str(Path(job["work"], "dataset.toml"))]
    assert latents[latents.index("--vae") + 1] == job["vae"]
    assert "--skip_existing" in latents
    assert text[1] == str(Path(job["scripts"], "src", "musubi_tuner", "krea2_cache_text_encoder_outputs.py"))
    assert text[text.index("--text_encoder") + 1] == job["text_encoder"]
    assert "--batch_size" in text and "--skip_existing" in text
    assert _status(job)["state"] == "caching"


def test_a_cache_program_that_fails_stops_the_training_and_names_the_log(tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    monkeypatch.setattr(look_lora_trainer.subprocess, "run",
                        lambda command, **options: types.SimpleNamespace(returncode=1))

    with pytest.raises(look_lora_trainer.Stopped) as stopped:
        look_lora_trainer.cache(job, wait_for_idle=lambda job: None)

    assert job["log"] in str(stopped.value)


# --- waiting for the card ---------------------------------------------------------

class _Machine:
    def __init__(self, waiting=(), memory=(), held=(False,), claims=(True,)):
        self.waiting = list(waiting)
        self.memory = list(memory)
        self.held = list(held)
        self.claims = list(claims)
        self.unloaded = self.claimed = self.released = 0
        self.slept: list[float] = []

    def card_held_by_another(self):
        return self.held.pop(0) if len(self.held) > 1 else self.held[0]

    def claim_card(self):
        self.claimed += 1
        return self.claims.pop(0) if len(self.claims) > 1 else self.claims[0]

    def release_card(self):
        self.released += 1

    def jobs_waiting(self):
        return self.waiting.pop(0) if len(self.waiting) > 1 else self.waiting[0]

    def unload_comfyui(self):
        self.unloaded += 1

    def card_memory_mib(self):
        return self.memory.pop(0) if len(self.memory) > 1 else self.memory[0]

    def sleep(self, seconds):
        self.slept.append(seconds)


def test_the_card_is_idle_once_comfyuis_line_has_been_empty_two_minutes_and_its_memory_is_back(
        tmp_path):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    machine = _Machine(waiting=[1, 0, 0, 0, None, 0, 0, 0, 0, 0, 0], memory=[9000, 800])

    look_lora_trainer.wait_for_idle(job, machine)

    assert machine.slept.count(20) == 7
    assert machine.unloaded == 1
    assert machine.claimed == 1
    assert _status(job)["state"] == "waiting"


def test_the_card_is_not_idle_while_another_trainer_holds_it(tmp_path):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    machine = _Machine(waiting=[0], memory=[100], held=[True, True, False])

    look_lora_trainer.wait_for_idle(job, machine)

    assert machine.slept.count(20) == 8
    assert machine.claimed == 1


def test_a_card_another_trainer_took_first_is_waited_for_again(tmp_path):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    machine = _Machine(waiting=[0], memory=[100], claims=[False, True])

    look_lora_trainer.wait_for_idle(job, machine)

    assert machine.slept.count(20) == 12
    assert machine.claimed == 2


# --- training ---------------------------------------------------------------------

def _fake_trainer(tmp_path, body: str) -> Path:
    script = tmp_path / "fake_trainer.py"
    script.write_text(body, encoding="utf-8")
    return script


def _training_job(tmp_path, body: str, **more) -> dict:
    job = _job(tmp_path, steps=50, save_every=25, **more)
    Path(job["work"]).mkdir(parents=True, exist_ok=True)
    job["trainer_program"] = str(_fake_trainer(tmp_path, body))
    return job


def _popen_the_fake(job):
    def popen(command, **options):
        return subprocess.Popen([sys.executable, job["trainer_program"], *command], **options)
    return popen


_SAVES_A_STATE = '''
import os, sys, time
args = sys.argv[1:]
out = args[args.index("--output_dir") + 1]
steps = int(args[args.index("--max_train_steps") + 1])
print(f"steps:  40%|####      | {steps // 2}/{steps} [00:02<00:03]", flush=True)
os.makedirs(os.path.join(out, "Example Look 1.1-step00000025-state"), exist_ok=True)
print("resumed from", args[args.index("--resume") + 1] if "--resume" in args else "nothing", flush=True)
'''


def test_a_training_runs_its_steps_under_accelerate_and_says_how_far_it_has_got(tmp_path):
    job = _training_job(tmp_path, _SAVES_A_STATE + "open(os.path.join(out, 'Example Look 1.1.safetensors'), 'wb').write(b'lora')\n")
    machine = _Machine(waiting=[0], memory=[100])

    look_lora_trainer.train(job, machine, popen=_popen_the_fake(job), kill=lambda process: None)

    assert Path(job["work"], "output", "Example Look 1.1.safetensors").is_file()
    assert Path(job["work"], "steps_done.txt").read_text() == "50"
    assert _status(job) == {"state": "training", "done": 25, "total": 50}


def test_a_training_stopped_for_a_comfyui_job_resumes_from_its_newest_state_for_the_steps_left(
        tmp_path):
    job = _training_job(tmp_path, _SAVES_A_STATE + '''
if "--resume" not in args:
    time.sleep(30)
open(os.path.join(out, 'Example Look 1.1.safetensors'), 'wb').write(b'lora')
''')
    machine = _Machine(waiting=[*([0] * 6), 2, *([0] * 20)], memory=[100])
    killed = []

    def kill(process):
        killed.append(process.pid)
        process.kill()

    look_lora_trainer.train(job, machine, popen=_popen_the_fake(job), kill=kill)

    assert len(killed) == 1
    assert (machine.claimed, machine.released) == (2, 1)
    assert Path(job["work"], "steps_done.txt").read_text() == "50"


def test_a_training_whose_card_ran_out_of_memory_says_so(tmp_path):
    job = _training_job(tmp_path, "import sys\nprint('torch.OutOfMemoryError: CUDA out of memory')\nsys.exit(1)\n")

    with pytest.raises(look_lora_trainer.Stopped) as stopped:
        look_lora_trainer.train(job, _Machine(waiting=[0], memory=[100]), popen=_popen_the_fake(job), kill=lambda p: None)

    assert "graphics card ran out of memory" in str(stopped.value)


def test_a_training_that_keeps_breaking_gives_up_after_twelve_tries_and_names_the_log(tmp_path):
    job = _training_job(tmp_path, "import sys\nprint('ValueError: bad option')\nsys.exit(1)\n")
    machine = _Machine(waiting=[0], memory=[100])

    with pytest.raises(look_lora_trainer.Stopped) as stopped:
        look_lora_trainer.train(job, machine, popen=_popen_the_fake(job), kill=lambda p: None)

    assert job["log"] in str(stopped.value)
    assert machine.slept.count(60) == 11


def test_the_training_command_asks_musubi_for_a_krea_2_lora_at_the_settings_his_look_was_trained_at(
        tmp_path):
    job = _job(tmp_path, steps=1500, save_every=25)
    state = tmp_path / "work" / "output" / "Example Look 1.1-step00000300-state"

    command = look_lora_trainer.train_command(job, 1200, resume=state)

    assert command[1:3] == ["-m", "accelerate.commands.launch"]
    assert str(Path(job["scripts"], "src", "musubi_tuner", "krea2_train_network.py")) in command
    for option, value in (("--dit", job["base_model"]), ("--vae", job["vae"]), ("--text_encoder", job["text_encoder"]),
                          ("--network_module", "networks.lora_krea2"), ("--network_dim", "32"), ("--network_alpha", "32"),
                          ("--learning_rate", "1e-4"), ("--optimizer_type", "adamw8bit"), ("--max_train_steps", "1200"),
                          ("--save_every_n_steps", "25"), ("--save_last_n_steps", "75"), ("--output_name", "Example Look 1.1"),
                          ("--resume", str(state)),
                          ("--timestep_sampling", "krea2_shift"), ("--blocks_to_swap", "26")):
        assert command[command.index(option) + 1] == value, option
    assert "--save_state" in command and "--fp8_base" in command and "--fp8_scaled" in command
    assert "--sample_prompts" not in command and "--turbo_lora" not in command


# --- install ----------------------------------------------------------------------

def test_the_finished_lora_is_installed_under_its_version_and_the_training_records_what_it_trained_on(tmp_path):
    job = _job(tmp_path, picture_stamps={"pictures/one.png": [10, 20]})
    output = Path(job["work"], "output")
    output.mkdir(parents=True)
    (output / "Example Look 1.1.safetensors").write_bytes(b"lora")
    (output / "Example Look 1.1-step00000025-state").mkdir()
    Path(job["work"], "steps_done.txt").write_text("50")

    look_lora_trainer.install(job)

    assert (Path(job["lora_folder"]) / "Example Look 1.1.safetensors").read_bytes() == b"lora"
    assert json.loads(Path(job["trained"]).read_text(encoding="utf-8")) == {
        "photo_stamps": {"pictures/one.png": [10, 20]}, "lora": "Example Look 1.1.safetensors"}
    assert _status(job) == {"state": "done", "lora": "Example Look 1.1.safetensors", "trigger_words": ["zz"]}
    assert not output.exists()
    assert not Path(job["work"], "steps_done.txt").exists()


def test_no_installed_lora_is_ever_overwritten(tmp_path):
    job = _job(tmp_path)
    output = Path(job["work"], "output")
    output.mkdir(parents=True)
    (output / "Example Look 1.1.safetensors").write_bytes(b"new")
    Path(job["lora_folder"]).mkdir()
    (Path(job["lora_folder"]) / "Example Look 1.1.safetensors").write_bytes(b"old")

    with pytest.raises(look_lora_trainer.Stopped):
        look_lora_trainer.install(job)

    assert (Path(job["lora_folder"]) / "Example Look 1.1.safetensors").read_bytes() == b"old"


# --- the whole run and its entry point ------------------------------------------------

def test_a_whole_run_takes_the_steps_in_order_and_describes_in_a_program_of_its_own(tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    done = []
    for step in ("prepare", "dataset", "install"):
        monkeypatch.setattr(look_lora_trainer, step, lambda job, step=step: done.append(step))
    monkeypatch.setattr(look_lora_trainer, "cache", lambda job, wait_for_idle: done.append("cache"))
    monkeypatch.setattr(look_lora_trainer, "train", lambda job, machine, **options: done.append("train"))
    monkeypatch.setattr(look_lora_trainer.subprocess, "run",
                        lambda command, **options: done.append(("describe", command[2:])) or types.SimpleNamespace(returncode=0))

    look_lora_trainer.run(job)

    assert done == ["prepare", ("describe", ["describe", job["job_file"]]), "dataset", "cache", "train", "install"]


def test_a_run_lets_go_of_the_card_however_it_ends(tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    monkeypatch.setattr(look_lora_trainer, "prepare",
                        lambda job: (_ for _ in ()).throw(look_lora_trainer.Stopped("No pictures.")))
    assert card_claim.take("Example Look 1.1 training", os.getpid())

    with pytest.raises(look_lora_trainer.Stopped):
        look_lora_trainer.run(job)

    assert not card_claim.CLAIM.exists()


def test_a_step_run_on_its_own_lets_go_of_the_card_too(tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    monkeypatch.setitem(look_lora_trainer.STEPS, "describe", lambda job: card_claim.take("Example Look 1.1 training", os.getpid()))

    assert look_lora_trainer.main(["describe", job["job_file"]]) == 0
    assert not card_claim.CLAIM.exists()


def test_a_step_that_stops_leaves_its_reason_where_the_app_reads_it(tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    monkeypatch.setitem(look_lora_trainer.STEPS, "prepare", lambda job: (_ for _ in ()).throw(look_lora_trainer.Stopped("No pictures.")))

    assert look_lora_trainer.main(["prepare", job["job_file"]]) == 1
    assert _status(job) == {"state": "failed", "message": "No pictures."}


def test_a_step_that_breaks_says_what_it_was_doing_and_prints_why_into_the_log(tmp_path, monkeypatch, capsys):
    job = _job(tmp_path)
    Path(job["work"]).mkdir()
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")

    def breaks(job):
        raise KeyError("no such thing")

    monkeypatch.setitem(look_lora_trainer.STEPS, "run", breaks)

    assert look_lora_trainer.main(["run", job["job_file"]]) == 1
    assert _status(job)["state"] == "failed"
    assert job["log"] in _status(job)["message"]
    assert "no such thing" in capsys.readouterr().err
