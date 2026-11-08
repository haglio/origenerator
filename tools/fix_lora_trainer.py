"""Train a fix's LoRA from images of its part, for Origenerator -- run by path,
never imported by the app, each step under the Python that can run it:

    python fix_lora_trainer.py run job.json     # the one kohya's sd-scripts is installed in
    python fix_lora_trainer.py crop job.json    # ComfyUI's, which reads every detector a fix uses

``run`` is the whole training, and crops by starting ``crop`` under ComfyUI's
Python, so the training is one program that goes on if the app closes.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from origenerator import training_rounds
from origenerator.training_rounds import IN_THE_BACKGROUND, Stopped, output_folder, said_why, status

_TOTAL_IMAGE_SIGHTINGS = 150
_EPOCHS = 10


def training_environment(base: dict) -> dict:
    return dict(base, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def _repeats(count: int) -> int:
    return max(1, math.ceil(_TOTAL_IMAGE_SIGHTINGS / count))


def dataset_folder(work: str, part: str, count: int) -> str:
    return f"{work}/{_repeats(count)}_{part}"


def training_steps(count: int) -> int:
    return _EPOCHS * _repeats(count) * count


def train_command(job: dict, dataset: str, resume: Path | None = None,
                  python: str = sys.executable) -> list[str]:
    return [
        python, f"{job['sd_scripts']}/sdxl_train_network.py",
        "--pretrained_model_name_or_path", job["base_model"],
        "--train_data_dir", dataset,
        "--output_dir", str(output_folder(job)),
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
        "--max_train_steps", str(job["steps"]),
        "--save_every_n_steps", str(job["save_every"]),
        "--save_state", "--save_last_n_steps", str(3 * job["save_every"]),
        "--train_batch_size", "1",
        "--mixed_precision", "bf16",
        "--save_precision", "bf16",
        "--gradient_checkpointing",
        "--sdpa",
        "--cache_latents",
        "--no_half_vae",
        "--caption_extension", ".txt",
        "--seed", "1",
        *(["--resume", str(resume), "--skip_until_initial_step"] if resume is not None else []),
    ]


def square_crop(box, size) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width, height = size
    side = min(2 * max(right - left, bottom - top), width, height)
    x = min(max((left + right) / 2 - side / 2, 0), width - side)
    y = min(max((top + bottom) / 2 - side / 2, 0), height - side)
    return round(x), round(y), round(x + side), round(y + side)


def _finder(job: dict):

    from ultralytics import YOLO  # noqa: PLC0415

    try:
        model = YOLO(job["detector"])
    except Exception as error:
        raise Stopped(f"The {job['part'].capitalize()} detector, {Path(job['detector']).name}, "
                      "couldn't be read, so no image was cropped. Nothing about your images "
                      f"caused it; an agent can read why in {job['log']}.") from error

    def find(image):
        boxes = model.predict(image, verbose=False)[0].boxes
        if len(boxes) == 0:
            return None
        best = max(range(len(boxes)), key=lambda i: float(boxes.conf[i]))
        return [float(value) for value in boxes.xyxy[best]]

    return find


def _dataset(job: dict) -> Path:
    return Path(job["work"]) / "images"


def crop(job: dict, find=None) -> int:
    from PIL import Image  # noqa: PLC0415

    crops = Path(job["work"]) / "crops"
    shutil.rmtree(_dataset(job), ignore_errors=True)
    shutil.rmtree(output_folder(job), ignore_errors=True)
    shutil.rmtree(crops, ignore_errors=True)
    crops.mkdir(parents=True)
    find = find or _finder(job)
    images = job["images"]
    kept = 0
    for index, path in enumerate(images, 1):
        status(job, state="cropping", done=index, total=len(images))
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
        except (OSError, ValueError) as error:
            raise Stopped(f"{Path(path).name} couldn't be opened as an image. Take it out of "
                          f"{Path(path).parent} or replace it, then press Train "
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
        raise Stopped(f"The {name} detector didn't find {name} in any of the {len(images)} "
                      f"images in {' and '.join(job['images_folders'])}. Add images where "
                      f"{name} is clearly visible, then press Train again.")
    return kept


def train(job: dict, machine, popen=subprocess.Popen, kill=training_rounds.end_process) -> None:
    crops = Path(job["work"]) / "crops"
    dataset = _dataset(job)
    count = len(list(crops.glob("*.jpg")))
    dataset.mkdir(parents=True)
    crops.rename(dataset_folder(str(dataset), job["part"], count))
    job = dict(job, steps=training_steps(count))
    environment = training_environment(dict(os.environ))

    def in_sd_scripts(command, **options):
        return popen(command, cwd=job["sd_scripts"], env=environment, **options)

    training_rounds.train(job, machine, training_rounds.Rounds(
        lambda _done, resume: train_command(job, str(dataset), resume)),
        popen=in_sd_scripts, kill=kill)
    training_rounds.install(job)


def run(job: dict, machine=None) -> None:
    machine = machine or training_rounds.machine_of(job)
    try:
        training_rounds.wait_for_idle(job, machine)
        cropping = subprocess.run([job["comfyui_python"], str(Path(__file__).resolve()), "crop",
                                   job["job_file"]], creationflags=IN_THE_BACKGROUND,
                                  check=False)
        if cropping.returncode != 0:
            if said_why(job):
                raise Stopped()
            raise Stopped("The image cropping quit without saying why. An agent can read what "
                          f"it printed in {job['log']}.")
        train(job, machine)
    finally:
        training_rounds.let_go_of_the_graphics_card()


STEPS = {"run": run, "crop": crop}
_DOING = {"run": "training", "crop": "cropping the images"}


def main(argv: list[str]) -> int:
    return training_rounds.main(argv, STEPS, _DOING)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
