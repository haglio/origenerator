from __future__ import annotations

from pathlib import Path, PureWindowsPath

from origenerator import config, lora_training
from origenerator.content import load_content
from origenerator.lora_training import TrainingOffer, TrainingState
from origenerator.lora_versions import newest_version, next_version
from origenerator.model_titles import lora_folder, model_stem, model_title, versioned, write_title
from origenerator.trigger_words import trigger_words_by_lora, write_trigger_words
from origenerator.workflows.model_arch import describe
from origenerator.workflows.model_files import is_no_lora

TRAINER = lora_training.TRAINERS / "look_lora_trainer.py"
HOLDS_THE_LINE = False
FIRST_STATE = "preparing"
STEPS = 1500
SAVE_EVERY = 25
PICTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".bmp", ".tif", ".tiff"}


def trainable_loras() -> dict:
    return load_content().get("trainable_loras") or {}


def trainable_base_of(lora) -> str | None:
    if is_no_lora(lora):
        return None
    parsed = versioned(model_title(lora))
    if parsed is None or parsed[0] not in trainable_loras():
        return None
    family, own = model_family(parsed[0]), describe(lora_folder() / str(lora)).arch
    return parsed[0] if family is None or own in (None, family) else None


def model_family(base: str) -> str | None:
    return describe(_model_file("diffusion_models", trainable_loras()[base]["base_model"])).arch


def _model_file(category: str, name: str) -> Path:
    return config.COMFYUI_DIR / "models" / category / name


def pictures_folder(base: str) -> Path:
    return Path(trainable_loras()[base]["pictures"])


def picture_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in PICTURE_SUFFIXES)


def picture_stamps(base: str) -> dict[str, list[int]]:
    return lora_training.picture_stamps(picture_files(pictures_folder(base)))


def work_folder(base: str) -> Path:
    return config.LOOK_TRAINING_DIR / base


def training_state(base: str) -> TrainingState:
    if newest_version(base, model_family(base)) is None:
        return TrainingState.UNTRAINED
    state = lora_training.training_state(work_folder(base) / "trained.json", picture_stamps(base))
    return TrainingState.OUT_OF_DATE if state is TrainingState.UNTRAINED else state


def training_job(base: str) -> dict:
    settings = trainable_loras()[base]
    family = model_family(base)
    newest = newest_version(base, family)
    folder = PureWindowsPath(newest[1]).parent if newest else PureWindowsPath()
    output_name = f"{base} {next_version(base, family)}"
    return {
        "base": base,
        "pictures_folder": str(pictures_folder(base)),
        "picture_stamps": picture_stamps(base),
        "output_name": output_name,
        "display_name": output_name,
        "lora_folder": str(lora_folder() / folder),
        "lora": str(folder / f"{output_name}.safetensors"),
        "trigger_words": _words_to_train_on(settings, newest),
        "base_model": str(_model_file("diffusion_models", settings["base_model"])),
        "text_encoder": str(_model_file("text_encoders", settings["text_encoder"])),
        "vae": str(_model_file("vae", settings["vae"])),
        "scripts": str(config.KREA2_TRAINING_SCRIPTS),
        "steps": STEPS,
        "save_every": SAVE_EVERY,
        "comfyui": f"http://{config.COMFYUI_HOST}:{config.COMFYUI_PORT}",
        **lora_training.work_files(work_folder(base)),
    }


def _words_to_train_on(settings: dict, newest) -> list[str]:
    if "trigger_words" in settings:
        return list(settings["trigger_words"])
    return list(trigger_words_by_lora().get(model_stem(newest[1]), [])) if newest else []


def start(job: dict) -> lora_training.Trainer:
    return lora_training.start(job, config.KREA2_TRAINING_PYTHON, TRAINER)


def trainings() -> list[dict]:
    return lora_training.trainings(config.LOOK_TRAINING_DIR)


def running_trainings() -> list[dict]:
    return lora_training.running_trainings(config.LOOK_TRAINING_DIR)


def note_duration(seconds: float) -> None:
    lora_training.note_duration(config.LOOK_TRAINING_DIR, seconds)


def typical_seconds() -> float | None:
    return lora_training.typical_seconds(config.LOOK_TRAINING_DIR)


def take(job: dict) -> str:
    stem = model_stem(job["lora"])
    write_title(stem, job["output_name"])
    write_trigger_words({stem: list(job["trigger_words"])})
    return job["lora"]


def training_offer(base: str) -> TrainingOffer:
    folder = pictures_folder(base)
    return lora_training.offer(
        training_state(base),
        tooltip=(f"Trains the next version of {base} from the pictures in {folder}. Your own "
                 "generations come first: the training pauses whenever ComfyUI has work and picks "
                 "up where it stopped."),
        pictures=len(picture_files(folder)), folder=folder)
