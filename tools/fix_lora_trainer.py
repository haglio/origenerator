"""Train a fix's LoRA from photos of its part, for Origenerator -- run by path,
under the Python of the environment kohya's sd-scripts lives in, never imported
by the app.

    python fix_lora_trainer.py job.json

Only the plain functions are imported by the app's tests; everything heavy is
imported inside :func:`main`, so this file loads anywhere.
"""

from __future__ import annotations

import math
import sys

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


def _status(job: dict, **fields) -> None:
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    Path(job["status"]).write_text(json.dumps(fields), encoding="utf-8")


def _crop_photos(job: dict, crops) -> int:
    from PIL import Image  # noqa: PLC0415
    from ultralytics import YOLO  # noqa: PLC0415

    detector = YOLO(job["detector"])
    photos = job["photos"]
    crops.mkdir(parents=True, exist_ok=True)
    kept = 0
    for index, photo in enumerate(photos, 1):
        _status(job, state="cropping", done=index, total=len(photos))
        with Image.open(photo) as opened:
            image = opened.convert("RGB")
        boxes = detector.predict(image, verbose=False)[0].boxes
        if len(boxes) == 0:
            continue
        best = max(range(len(boxes)), key=lambda i: float(boxes.conf[i]))
        box = [float(value) for value in boxes.xyxy[best]]
        crop = image.crop(square_crop(box, image.size)).resize((1024, 1024), Image.LANCZOS)
        crop.save(crops / f"{kept:04d}.jpg", quality=95)
        (crops / f"{kept:04d}.txt").write_text(job["caption"], encoding="utf-8")
        kept += 1
    return kept


def _train(job: dict, images: str) -> int:
    import os  # noqa: PLC0415
    import re  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    log = Path(job["work"]) / "training.log"
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    with log.open("w", encoding="utf-8") as written:
        process = subprocess.Popen(train_command(job, images), cwd=job["sd_scripts"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=flags,
                                   env=training_environment(dict(os.environ)))
        piece = b""
        while chunk := process.stdout.read1(256):
            written.write(chunk.decode("utf-8", "replace"))
            piece = (piece + chunk)[-512:]
            steps = re.findall(rb"steps:\s+\d+%\|[^|]*\|\s*(\d+)/(\d+)", piece)
            if steps:
                done, total = steps[-1]
                _status(job, state="training", done=int(done), total=int(total))
        return process.wait()


def main(job_path: str) -> int:
    import json  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    work = Path(job["work"])
    shutil.rmtree(work / "images", ignore_errors=True)
    crops = work / "crops"
    shutil.rmtree(crops, ignore_errors=True)
    kept = _crop_photos(job, crops)
    if not kept:
        _status(job, state="failed", message="The fix's detector found its part in none of the photos.")
        return 1
    images = work / "images"
    images.mkdir(parents=True)
    crops.rename(dataset_folder(str(images), job["part"], kept))
    _status(job, state="training", done=0, total=0)
    if _train(job, str(images)) != 0:
        _status(job, state="failed", message=f"The training stopped; its log is {work / 'training.log'}.")
        return 1
    _status(job, state="done", lora=f"{job['output_name']}.safetensors")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
