from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from origenerator import training_rounds
from origenerator.training_rounds import (
    IMAGE_SUFFIXES,
    IN_THE_BACKGROUND,
    Stopped,
    output_folder,
    said_why,
    status,
)

LONG_SIDE = 1536
SHORT_SIDE_AT_LEAST = 512
DESCRIBER = "florence-community/Florence-2-large"
DESCRIBING_TASK = "<MORE_DETAILED_CAPTION>"
def _copies_folder(job: dict) -> Path:
    return Path(job["work"]) / "images"


def _captions_folder(job: dict) -> Path:
    return Path(job["work"]) / "captions"


def _cache_folder(job: dict) -> Path:
    return Path(job["work"]) / "cache"


def _copy_name(image: bytes) -> str:
    return hashlib.sha256(image).hexdigest()[:16]


def prepare(job: dict) -> int:
    from PIL import Image  # noqa: PLC0415

    folder = Path(job["images_folder"])
    images, captions = _copies_folder(job), _captions_folder(job)
    images.mkdir(parents=True, exist_ok=True)
    captions.mkdir(exist_ok=True)
    sources = sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    kept: set[str] = set()
    copied = too_small = unreadable = 0
    for index, source in enumerate(sources, 1):
        status(job, state="preparing", done=index, total=len(sources))
        name = _copy_name(source.read_bytes())
        if (images / f"{name}.jpg").exists():
            kept.add(name)
            continue
        try:
            with Image.open(source) as opened:
                image = opened.convert("RGB")
        except Exception:
            unreadable += 1
            continue
        if min(image.size) < SHORT_SIDE_AT_LEAST:
            too_small += 1
            continue
        if max(image.size) > LONG_SIDE:
            scale = LONG_SIDE / max(image.size)
            image = image.resize((round(image.width * scale), round(image.height * scale)),
                                     Image.LANCZOS)
        image.save(images / f"{name}.jpg", quality=95)
        kept.add(name)
        copied += 1
    for copy in images.glob("*.jpg"):
        if copy.stem not in kept:
            copy.unlink()
            copy.with_suffix(".txt").unlink(missing_ok=True)
            (captions / f"{copy.stem}.txt").unlink(missing_ok=True)
            for cached in _cache_folder(job).glob(f"{copy.stem}*"):
                cached.unlink()
    print(f"images: {len(sources)} in the folder, {copied} copied, {len(kept) - copied} already "
          f"copied, {too_small} too small, {unreadable} unreadable", flush=True)
    if not kept:
        raise Stopped(f"No image in {folder} can be trained on: an image has to be at least "
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

    def describe(image) -> str:
        inputs = processor(text=DESCRIBING_TASK, images=image, return_tensors="pt").to(device)
        inputs["pixel_values"] = inputs["pixel_values"].to(dtype)
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=256, num_beams=3, do_sample=False)
        text = processor.batch_decode(ids, skip_special_tokens=False)[0]
        description = processor.post_process_generation(
            text, task=DESCRIBING_TASK, image_size=image.size)[DESCRIBING_TASK]
        return " ".join(str(description).split())

    return describe


def describe(job: dict, describer=None, wait_for_idle=None) -> int:
    from PIL import Image  # noqa: PLC0415

    images = sorted(_copies_folder(job).glob("*.jpg"))
    captions = _captions_folder(job)
    captions.mkdir(exist_ok=True)
    status(job, state="describing", done=0, total=len(images))
    missing = [image for image in images if not (captions / f"{image.stem}.txt").exists()]
    if missing:
        (wait_for_idle or _wait_for_the_graphics_card)(job)
        describer = describer or _florence()
    for index, image in enumerate(images, 1):
        if image in missing:
            with Image.open(image) as opened:
                opened_image = opened.convert("RGB")
            (captions / f"{image.stem}.txt").write_text(describer(opened_image), encoding="utf-8")
        status(job, state="describing", done=index, total=len(images))
    print(f"descriptions: {len(missing)} written, {len(images) - len(missing)} kept", flush=True)
    return len(missing)


def dataset(job: dict) -> None:
    images, captions = _copies_folder(job), _captions_folder(job)
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
    status(job, state="caching")
    settings = str(Path(job["work"], "dataset.toml"))
    for command in (
        [sys.executable, _musubi(job, "krea2_cache_latents.py"), "--dataset_config", settings,
         "--vae", job["vae"], "--skip_existing"],
        [sys.executable, _musubi(job, "krea2_cache_text_encoder_outputs.py"), "--dataset_config",
         settings, "--text_encoder", job["text_encoder"], "--batch_size", "1", "--skip_existing"],
    ):
        if subprocess.run(command, creationflags=IN_THE_BACKGROUND, check=False).returncode != 0:
            raise Stopped("Preparing the images for the training failed. Nothing about your "
                          f"images caused it; an agent can read why in {job['log']}.")


def _wait_for_the_graphics_card(job: dict) -> None:
    training_rounds.wait_for_idle(job, training_rounds.machine_of(job))


def train_command(job: dict, steps: int, resume: Path | None = None) -> list[str]:
    output = output_folder(job)
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


def train(job: dict, machine, popen=subprocess.Popen, kill=training_rounds.end_process) -> None:
    training_rounds.train(job, machine, training_rounds.Rounds(
        lambda done, resume: train_command(job, job["steps"] - done, resume),
        saved_states_count_every_round=True), popen=popen, kill=kill)


def install(job: dict) -> None:
    training_rounds.install(job, trigger_words=job["trigger_words"])


def run(job: dict) -> None:
    try:
        prepare(job)
        describing = subprocess.run([sys.executable, str(Path(__file__).resolve()), "describe",
                                     job["job_file"]], creationflags=IN_THE_BACKGROUND,
                                    check=False)
        if describing.returncode != 0:
            if said_why(job):
                raise Stopped()
            raise Stopped("Describing the images quit without saying why. An agent can read "
                          f"what it printed in {job['log']}.")
        dataset(job)
        cache(job, wait_for_idle=_wait_for_the_graphics_card)
        train(job, training_rounds.machine_of(job))
        install(job)
    finally:
        training_rounds.let_go_of_the_graphics_card()


STEPS = {"run": run, "prepare": prepare, "describe": describe, "dataset": dataset, "cache": cache,
         "train": lambda job: train(job, training_rounds.machine_of(job)), "install": install}
_DOING = {"run": "training", "prepare": "copying the images", "describe": "describing the images",
          "dataset": "writing the dataset", "cache": "preparing the images", "train": "training",
          "install": "installing the LoRA"}


def main(argv: list[str]) -> int:
    return training_rounds.main(argv, STEPS, _DOING)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
