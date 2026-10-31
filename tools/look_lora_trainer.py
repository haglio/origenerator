from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import card_claim  # noqa: E402

PICTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".bmp", ".tif", ".tiff"}
LONG_SIDE = 1536
SHORT_SIDE_AT_LEAST = 512
DESCRIBER = "florence-community/Florence-2-large"
DESCRIBING_TASK = "<MORE_DETAILED_CAPTION>"
IDLE_CHECKS = 6
IDLE_CHECK_SECONDS = 20
GRAPHICS_CARD_FREE_MIB = 3000
POLL_SECONDS = 5
ROUNDS = 12
_STEPS = re.compile(rb"steps:\s+\d+%\|[^|]*\|\s*(\d+)/(\d+)")
_MEMORY_RAN_OUT = (b"OutOfMemoryError", b"CUDA out of memory", b"CUDA error: out of memory")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_IN_THE_BACKGROUND = _NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


class Stopped(Exception):
    pass


def _status(job: dict, **fields) -> None:
    Path(job["status"]).write_text(json.dumps(fields), encoding="utf-8")


def _images_folder(job: dict) -> Path:
    return Path(job["work"]) / "images"


def _captions_folder(job: dict) -> Path:
    return Path(job["work"]) / "captions"


def _cache_folder(job: dict) -> Path:
    return Path(job["work"]) / "cache"


def _output_folder(job: dict) -> Path:
    return Path(job["work"]) / "output"


def _copy_name(picture: bytes) -> str:
    return hashlib.sha256(picture).hexdigest()[:16]


def prepare(job: dict) -> int:
    from PIL import Image  # noqa: PLC0415

    folder = Path(job["pictures_folder"])
    images, captions = _images_folder(job), _captions_folder(job)
    images.mkdir(parents=True, exist_ok=True)
    captions.mkdir(exist_ok=True)
    sources = sorted(path for path in folder.iterdir() if path.suffix.lower() in PICTURE_SUFFIXES)
    kept: set[str] = set()
    copied = too_small = unreadable = 0
    for index, source in enumerate(sources, 1):
        _status(job, state="preparing", done=index, total=len(sources))
        name = _copy_name(source.read_bytes())
        if (images / f"{name}.jpg").exists():
            kept.add(name)
            continue
        try:
            with Image.open(source) as opened:
                picture = opened.convert("RGB")
        except Exception:
            unreadable += 1
            continue
        if min(picture.size) < SHORT_SIDE_AT_LEAST:
            too_small += 1
            continue
        if max(picture.size) > LONG_SIDE:
            scale = LONG_SIDE / max(picture.size)
            picture = picture.resize((round(picture.width * scale), round(picture.height * scale)),
                                     Image.LANCZOS)
        picture.save(images / f"{name}.jpg", quality=95)
        kept.add(name)
        copied += 1
    for copy in images.glob("*.jpg"):
        if copy.stem not in kept:
            copy.unlink()
            copy.with_suffix(".txt").unlink(missing_ok=True)
            (captions / f"{copy.stem}.txt").unlink(missing_ok=True)
            for cached in _cache_folder(job).glob(f"{copy.stem}*"):
                cached.unlink()
    print(f"pictures: {len(sources)} in the folder, {copied} copied, {len(kept) - copied} already "
          f"copied, {too_small} too small, {unreadable} unreadable", flush=True)
    if not kept:
        raise Stopped(f"No picture in {folder} can be trained on: a picture has to be at least "
                      f"{SHORT_SIDE_AT_LEAST} pixels on its shorter side. Add some there, then "
                      "press Train again.")
    return len(kept)


def _florence():
    import torch  # noqa: PLC0415
    from transformers import AutoProcessor, Florence2ForConditionalGeneration  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    model = Florence2ForConditionalGeneration.from_pretrained(DESCRIBER, dtype=dtype).to(device).eval()
    processor = AutoProcessor.from_pretrained(DESCRIBER)

    def describe(picture) -> str:
        inputs = processor(text=DESCRIBING_TASK, images=picture, return_tensors="pt").to(device)
        inputs["pixel_values"] = inputs["pixel_values"].to(dtype)
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=256, num_beams=3, do_sample=False)
        text = processor.batch_decode(ids, skip_special_tokens=False)[0]
        description = processor.post_process_generation(
            text, task=DESCRIBING_TASK, image_size=picture.size)[DESCRIBING_TASK]
        return " ".join(str(description).split())

    return describe


def describe(job: dict, describer=None, wait_for_idle=None) -> int:
    from PIL import Image  # noqa: PLC0415

    images = sorted(_images_folder(job).glob("*.jpg"))
    captions = _captions_folder(job)
    captions.mkdir(exist_ok=True)
    _status(job, state="describing", done=0, total=len(images))
    missing = [image for image in images if not (captions / f"{image.stem}.txt").exists()]
    if missing:
        (wait_for_idle or _wait_for_the_graphics_card)(job)
        describer = describer or _florence()
    for index, image in enumerate(images, 1):
        if image in missing:
            with Image.open(image) as opened:
                picture = opened.convert("RGB")
            (captions / f"{image.stem}.txt").write_text(describer(picture), encoding="utf-8")
        _status(job, state="describing", done=index, total=len(images))
    print(f"descriptions: {len(missing)} written, {len(images) - len(missing)} kept", flush=True)
    return len(missing)


def dataset(job: dict) -> None:
    images, captions = _images_folder(job), _captions_folder(job)
    words = list(job["trigger_words"])
    for image in sorted(images.glob("*.jpg")):
        description = (captions / f"{image.stem}.txt").read_text(encoding="utf-8").strip()
        image.with_suffix(".txt").write_text(", ".join([*words, description]), encoding="utf-8")
    Path(job["work"], "dataset.toml").write_text(
        "[general]\nresolution = [1024, 1024]\ncaption_extension = \".txt\"\nbatch_size = 1\n"
        "enable_bucket = true\nbucket_no_upscale = true\n\n[[datasets]]\n"
        f"image_directory = \"{images.as_posix()}\"\n"
        f"cache_directory = \"{_cache_folder(job).as_posix()}\"\nnum_repeats = 1\n",
        encoding="utf-8")


def _musubi(job: dict, program: str) -> str:
    return str(Path(job["scripts"], "src", "musubi_tuner", program))


def cache(job: dict, wait_for_idle=None) -> None:
    (wait_for_idle or _wait_for_the_graphics_card)(job)
    _status(job, state="caching")
    settings = str(Path(job["work"], "dataset.toml"))
    for command in (
        [sys.executable, _musubi(job, "krea2_cache_latents.py"), "--dataset_config", settings,
         "--vae", job["vae"], "--skip_existing"],
        [sys.executable, _musubi(job, "krea2_cache_text_encoder_outputs.py"), "--dataset_config",
         settings, "--text_encoder", job["text_encoder"], "--batch_size", "1", "--skip_existing"],
    ):
        if subprocess.run(command, creationflags=_IN_THE_BACKGROUND, check=False).returncode != 0:
            raise Stopped("Preparing the pictures for the training failed. Nothing about your "
                          f"pictures caused it; an agent can read why in {job['log']}.")


class Machine:
    def __init__(self, comfyui: str, holder: str = ""):
        self._comfyui = comfyui
        self._holder = holder

    def graphics_card_held_by_another(self) -> bool:
        return card_claim.held_by_another(os.getpid())

    def claim_graphics_card(self) -> bool:
        return card_claim.take(self._holder, os.getpid())

    def release_graphics_card(self) -> None:
        card_claim.release(os.getpid())

    def jobs_waiting(self) -> int | None:
        try:
            with urllib.request.urlopen(f"{self._comfyui}/prompt", timeout=5) as answer:
                return int(json.load(answer)["exec_info"]["queue_remaining"])
        except Exception:
            return None

    def unload_comfyui(self) -> None:
        request = urllib.request.Request(
            f"{self._comfyui}/free", method="POST",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except Exception:
            return
        time.sleep(5)

    def graphics_card_memory_mib(self) -> int | None:
        try:
            said = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=30,
                                  creationflags=_NO_WINDOW, check=False).stdout
            return int(said.strip().splitlines()[0])
        except Exception:
            return None

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def wait_for_idle(job: dict, machine) -> None:
    _status(job, state="waiting")
    while True:
        quiet = 0
        while quiet < IDLE_CHECKS:
            free = machine.jobs_waiting() in (0, None) and not machine.graphics_card_held_by_another()
            quiet = quiet + 1 if free else 0
            machine.sleep(IDLE_CHECK_SECONDS)
        memory = machine.graphics_card_memory_mib()
        if memory is not None and memory >= GRAPHICS_CARD_FREE_MIB:
            machine.unload_comfyui()
            machine.sleep(10)
            memory = machine.graphics_card_memory_mib()
        if memory is not None and memory >= GRAPHICS_CARD_FREE_MIB:
            print(f"== the graphics card still holds {memory} MiB with ComfyUI's line empty; waiting on",
                  flush=True)
        elif machine.claim_graphics_card():
            return
        else:
            print("== another trainer took the graphics card first; waiting on", flush=True)
        machine.sleep(60)


def _machine(job: dict) -> Machine:
    return Machine(job["comfyui"], f"{job['display_name']} training")


def _wait_for_the_graphics_card(job: dict) -> None:
    wait_for_idle(job, _machine(job))


def train_command(job: dict, steps: int, resume: Path | None = None) -> list[str]:
    output = _output_folder(job)
    return [
        sys.executable, "-m", "accelerate.commands.launch", "--num_cpu_threads_per_process", "1",
        "--mixed_precision", "bf16", "--num_processes", "1", "--num_machines", "1",
        "--dynamo_backend", "no",
        _musubi(job, "krea2_train_network.py"),
        "--dit", job["base_model"], "--vae", job["vae"], "--text_encoder", job["text_encoder"],
        "--dataset_config", str(Path(job["work"], "dataset.toml")),
        "--network_module", "networks.lora_krea2", "--network_dim", "32", "--network_alpha", "32",
        "--learning_rate", "1e-4", "--optimizer_type", "adamw8bit",
        "--lr_scheduler", "constant_with_warmup", "--lr_warmup_steps", "50",
        "--mixed_precision", "bf16", "--fp8_base", "--fp8_scaled", "--blocks_to_swap", "26",
        "--gradient_checkpointing", "--sdpa", "--timestep_sampling", "krea2_shift",
        "--weighting_scheme", "none",
        "--max_train_steps", str(steps), "--save_every_n_steps", str(job["save_every"]),
        "--save_state", "--save_last_n_steps", str(3 * job["save_every"]),
        "--save_precision", "bf16", "--seed", "42",
        "--max_data_loader_n_workers", "2", "--persistent_data_loader_workers",
        "--logging_dir", str(output / "logs"), "--log_with", "tensorboard",
        "--output_dir", str(output), "--output_name", job["output_name"],
        *(["--resume", str(resume)] if resume is not None else []),
    ]


def _newest_state(output: Path) -> Path | None:
    states = [path for path in output.glob("*-state") if path.is_dir()]
    return max(states, key=lambda path: path.stat().st_mtime) if states else None


def _state_step(state: Path) -> int | None:
    found = re.search(r"-step(\d+)-state$", state.name)
    return int(found[1]) if found else None


def _tally(file: Path) -> int:
    try:
        return int(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0


class _Progress(threading.Thread):
    def __init__(self, process, job: dict, done: int):
        super().__init__(daemon=True)
        self._process, self._job, self._done = process, job, done
        self.tail = b""

    def run(self) -> None:
        while chunk := self._process.stdout.read1(256):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            self.tail = (self.tail + chunk)[-4096:]
            steps = _STEPS.findall(self.tail)
            if steps:
                _status(self._job, state="training", done=self._done + int(steps[-1][0]),
                        total=self._job["steps"])


def _end(process) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True,
                   creationflags=_NO_WINDOW, check=False)


def train(job: dict, machine, popen=subprocess.Popen, kill=_end) -> None:
    output = _output_folder(job)
    output.mkdir(parents=True, exist_ok=True)
    tally = Path(job["work"], "steps_done.txt")
    crashes = 0
    while True:
        done = _tally(tally)
        remaining = job["steps"] - done
        if remaining <= 0:
            return
        wait_for_idle(job, machine)
        machine.unload_comfyui()
        resume = _newest_state(output)
        _status(job, state="training", done=done, total=job["steps"])
        round_start = time.time()
        print(f"== training {remaining} more of {job['steps']} steps"
              + (f", resuming from {resume.name}" if resume is not None else ""), flush=True)
        process = popen(train_command(job, remaining, resume), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, creationflags=_IN_THE_BACKGROUND)
        progress = _Progress(process, job, done)
        progress.start()
        stopped_for_comfyui = False
        while process.poll() is None:
            machine.sleep(POLL_SECONDS)
            if machine.jobs_waiting() not in (0, None):
                print("== ComfyUI has a job; stopping the trainer until the graphics card is idle again",
                      flush=True)
                kill(process)
                stopped_for_comfyui = True
                process.wait()
        progress.join()
        if process.returncode == 0 and not stopped_for_comfyui:
            tally.write_text(str(job["steps"]), encoding="utf-8")
            return
        newest = _newest_state(output)
        if (newest is not None and newest.stat().st_mtime >= round_start
                and (step := _state_step(newest)) is not None):
            done += step
            tally.write_text(str(done), encoding="utf-8")
            print(f"== progress kept: {done} of {job['steps']} steps saved", flush=True)
        machine.release_graphics_card()
        if stopped_for_comfyui:
            machine.sleep(10)
            continue
        if any(sign in progress.tail for sign in _MEMORY_RAN_OUT):
            raise Stopped("The graphics card ran out of memory while training. Close anything "
                          "else using it, then press Train again.")
        crashes += 1
        if crashes >= ROUNDS:
            raise Stopped(f"The training program stopped {crashes} times. Nothing about your "
                          f"pictures caused it; an agent can read why in {job['log']}.")
        machine.sleep(60)


def install(job: dict) -> None:
    output = _output_folder(job)
    made = output / f"{job['output_name']}.safetensors"
    if not made.is_file():
        raise Stopped("The training ended without a LoRA to install. An agent can read why in "
                      f"{job['log']}.")
    destination = Path(job["lora_folder"]) / made.name
    if destination.exists():
        raise Stopped(f"{destination} is there already, so nothing was installed over it. An "
                      "agent can sort out which training made it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(made, destination)
    Path(job["trained"]).write_text(
        json.dumps({"photo_stamps": job["picture_stamps"], "lora": job["lora"]}), encoding="utf-8")
    shutil.rmtree(output)
    Path(job["work"], "steps_done.txt").unlink(missing_ok=True)
    _status(job, state="done", lora=job["lora"], trigger_words=job["trigger_words"])


def _said_why(job: dict) -> bool:
    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))["state"] == "failed"
    except (OSError, ValueError, KeyError):
        return False


def run(job: dict) -> None:
    try:
        prepare(job)
        describing = subprocess.run([sys.executable, str(Path(__file__).resolve()), "describe",
                                     job["job_file"]], creationflags=_IN_THE_BACKGROUND,
                                    check=False)
        if describing.returncode != 0:
            if _said_why(job):
                raise Stopped()
            raise Stopped("Describing the pictures quit without saying why. An agent can read "
                          f"what it printed in {job['log']}.")
        dataset(job)
        cache(job, wait_for_idle=_wait_for_the_graphics_card)
        train(job, _machine(job))
        install(job)
    finally:
        card_claim.release(os.getpid())


STEPS = {"run": run, "prepare": prepare, "describe": describe, "dataset": dataset, "cache": cache,
         "train": lambda job: train(job, _machine(job)), "install": install}
_DOING = {"run": "training", "prepare": "copying the pictures", "describe": "describing the pictures",
          "dataset": "writing the dataset", "cache": "preparing the pictures", "train": "training",
          "install": "installing the LoRA"}


def main(argv: list[str]) -> int:
    import traceback  # noqa: PLC0415

    step, job_path = argv
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    os.environ.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        STEPS[step](job)
    except Stopped as stopped:
        if str(stopped):
            _status(job, state="failed", message=str(stopped))
        return 1
    except Exception:
        traceback.print_exc()
        _status(job, state="failed", message=f"The training stopped with an error while "
                                             f"{_DOING[step]}. An agent can read why in "
                                             f"{job['log']}.")
        return 1
    finally:
        card_claim.release(os.getpid())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
