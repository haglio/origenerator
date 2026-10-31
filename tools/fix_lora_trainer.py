"""Train a fix's LoRA from photos of its part, for Origenerator -- run by path,
never imported by the app, each step under the Python that can run it:

    python fix_lora_trainer.py run job.json     # the one kohya's sd-scripts is installed in
    python fix_lora_trainer.py crop job.json    # ComfyUI's, which reads every detector a fix uses

``run`` is the whole training, and crops by starting ``crop`` under ComfyUI's
Python, so the training is one program that goes on if the app closes.

Only the plain functions are imported by the app's tests; everything heavy is
imported inside the step that needs it, so this file loads anywhere.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import card_claim  # noqa: E402

# How many times the training sees a photo in all, spread over however many
# photos there are, so a small set is not under-trained.
_SIGHTINGS = 150


def training_environment(base: dict) -> dict:
    return dict(base, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def dataset_folder(work: str, part: str, count: int) -> str:
    return f"{work}/{max(1, math.ceil(_SIGHTINGS / count))}_{part}"


def train_command(job: dict, dataset: str, python: str = sys.executable) -> list[str]:
    return [
        python, f"{job['sd_scripts']}/sdxl_train_network.py",
        "--pretrained_model_name_or_path", job["base_model"],
        "--train_data_dir", dataset,
        "--output_dir", job["output_dir"],
        "--output_name", job["output_name"],
        "--save_model_as", "safetensors",
        "--resolution", "1024,1024",
        "--network_module", "networks.lora",
        "--network_dim", "16",
        "--network_alpha", "8",
        "--network_train_unet_only",
        "--learning_rate", "1e-4",
        "--optimizer_type", "AdamW",
        "--lr_scheduler", "cosine",
        "--max_train_epochs", "10",
        "--train_batch_size", "1",
        "--mixed_precision", "bf16",
        "--save_precision", "bf16",
        "--gradient_checkpointing",
        "--sdpa",
        "--cache_latents",
        "--no_half_vae",
        "--caption_extension", ".txt",
        "--seed", "1",
    ]


def square_crop(box, size) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width, height = size
    side = min(2 * max(right - left, bottom - top), width, height)
    x = min(max((left + right) / 2 - side / 2, 0), width - side)
    y = min(max((top + bottom) / 2 - side / 2, 0), height - side)
    return round(x), round(y), round(x + side), round(y + side)


_IN_THE_BACKGROUND = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                      | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))


def _status(job: dict, **fields) -> None:
    import json  # noqa: PLC0415

    Path(job["status"]).write_text(json.dumps(fields), encoding="utf-8")


class Stopped(Exception):
    pass


def _finder(job: dict):

    from ultralytics import YOLO  # noqa: PLC0415

    try:
        model = YOLO(job["detector"])
    except Exception as error:
        raise Stopped(f"The {job['part'].capitalize()} detector, {Path(job['detector']).name}, "
                      "couldn't be read, so no photo was cropped. Nothing about your photos "
                      f"caused it; an agent can read why in {job['log']}.") from error

    def find(image):
        boxes = model.predict(image, verbose=False)[0].boxes
        if len(boxes) == 0:
            return None
        best = max(range(len(boxes)), key=lambda i: float(boxes.conf[i]))
        return [float(value) for value in boxes.xyxy[best]]

    return find


def crop(job: dict, find=None) -> int:
    import shutil  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    work = Path(job["work"])
    crops = work / "crops"
    shutil.rmtree(work / "images", ignore_errors=True)
    shutil.rmtree(crops, ignore_errors=True)
    crops.mkdir(parents=True)
    find = find or _finder(job)
    photos = job["photos"]
    kept = 0
    for index, photo in enumerate(photos, 1):
        _status(job, state="cropping", done=index, total=len(photos))
        try:
            with Image.open(photo) as opened:
                image = opened.convert("RGB")
        except (OSError, ValueError) as error:
            raise Stopped(f"{Path(photo).name} couldn't be opened as an image. Take it out of "
                          f"{Path(photo).parent} or replace it, then press Train "
                          "again.") from error
        box = find(image)
        if box is None:
            continue
        cropped = image.crop(square_crop(box, image.size)).resize((1024, 1024), Image.LANCZOS)
        cropped.save(crops / f"{kept:04d}.jpg", quality=95)
        (crops / f"{kept:04d}.txt").write_text(job["caption"], encoding="utf-8")
        kept += 1
    if not kept:
        name = job["part"].capitalize()
        raise Stopped(f"The {name} detector didn't find {name} in any of the {len(photos)} "
                      f"photos in {' and '.join(job['photos_folders'])}. Add photos where "
                      f"{name} is clearly visible, then press Train again.")
    return kept


def _train(job: dict, images: str) -> tuple[int, bytes]:
    import os  # noqa: PLC0415
    import re  # noqa: PLC0415

    process = subprocess.Popen(train_command(job, images), cwd=job["sd_scripts"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=_IN_THE_BACKGROUND,
                               env=training_environment(dict(os.environ)))
    tail = b""
    while chunk := process.stdout.read1(256):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        tail = (tail + chunk)[-4096:]
        steps = re.findall(rb"steps:\s+\d+%\|[^|]*\|\s*(\d+)/(\d+)", tail)
        if steps:
            done, total = steps[-1]
            _status(job, state="training", done=int(done), total=int(total))
    return process.wait(), tail


_MEMORY_RAN_OUT = (b"OutOfMemoryError", b"CUDA out of memory", b"CUDA error: out of memory")


def _why_the_training_stopped(tail: bytes, log: str) -> str:
    if any(sign in tail for sign in _MEMORY_RAN_OUT):
        return ("The graphics card ran out of memory while training. Close anything else "
                "using it, then press Train again.")
    return ("The training program stopped with an error. Nothing about your photos caused "
            f"it; an agent can read why in {log}.")


def train(job: dict) -> None:
    import json  # noqa: PLC0415

    work = Path(job["work"])
    crops = work / "crops"
    images = work / "images"
    images.mkdir(parents=True)
    crops.rename(dataset_folder(str(images), job["part"], len(list(crops.glob("*.jpg")))))
    _status(job, state="training", done=0, total=0)
    code, tail = _train(job, str(images))
    if code != 0:
        raise Stopped(_why_the_training_stopped(tail, job["log"]))
    Path(job["trained"]).write_text(
        json.dumps({"photo_stamps": job["photo_stamps"], "lora": job["lora"]}), encoding="utf-8")
    _status(job, state="done", lora=job["lora"])


def _said_why(job: dict) -> bool:
    import json  # noqa: PLC0415

    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))["state"] == "failed"
    except (OSError, ValueError, KeyError):
        return False


def _take_the_card(job: dict) -> None:
    while not card_claim.take(f"{job['part'].capitalize()} fix training", os.getpid()):
        _status(job, state="waiting")
        time.sleep(20)


def run(job: dict) -> None:
    try:
        _take_the_card(job)
        cropping = subprocess.run([job["comfyui_python"], str(Path(__file__).resolve()), "crop",
                                   job["job_file"]], creationflags=_IN_THE_BACKGROUND,
                                  check=False)
        if cropping.returncode != 0:
            if _said_why(job):
                raise Stopped()
            raise Stopped("The photo cropping quit without saying why. An agent can read what "
                          f"it printed in {job['log']}.")
        train(job)
    finally:
        card_claim.release(os.getpid())


STEPS = {"run": run, "crop": crop}
_DOING = {"run": "training", "crop": "cropping the photos"}


def main(argv: list[str]) -> int:
    import json  # noqa: PLC0415
    import traceback  # noqa: PLC0415

    step, job_path = argv
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
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
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
