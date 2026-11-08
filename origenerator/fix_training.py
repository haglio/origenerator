from __future__ import annotations

from pathlib import Path, PureWindowsPath

from origenerator import comfyui_launcher, config, gallery, lora_training
from origenerator.gallery.enhance_settings import MATCH_SOURCE_MODEL
from origenerator.lora_training import TrainingOffer, TrainingState
from origenerator.lora_versions import next_version, trash_tooltip
from origenerator.model_titles import FIX_LORA_FOLDER, model_stem
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detector_folder, detector_for_part

TRAINER = lora_training.TRAINERS / "fix_lora_trainer.py"
HOLDS_THE_LINE = True
FIRST_STATE = "cropping"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def images_folder(part) -> Path:
    return config.FIX_IMAGES_DIR / part.name.lower()


def shared_images_folder() -> Path:
    return config.FIX_IMAGES_DIR / "shared"


def image_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in _IMAGE_SUFFIXES)


def training_folders(part) -> list[Path]:
    return [images_folder(part)] + ([shared_images_folder()] if part.shared_images else [])


def training_images(part) -> list[Path]:
    return [image for folder in training_folders(part) for image in image_files(folder)]


def image_stamps(part) -> dict[str, list[int]]:
    return lora_training.image_stamps(training_images(part))


def _work_folder(part) -> Path:
    return config.FIX_TRAINING_DIR / part.name


def training_state(part) -> TrainingState:
    return lora_training.training_state(_work_folder(part) / "trained.json", image_stamps(part))


def train_tooltip(part) -> str:
    folders = (f"{part.name.lower()}, and in fixes\\shared," if part.shared_images
               else f"{part.name.lower()},")
    return ("Trains this fix a LoRA from the images in the library's "
            f"app_data\\origenerator\\fixes\\{folders} each cropped down to the part by the "
            "fix's own detector. Nothing generates while it trains.")


def training_offer(part, lora) -> TrainingOffer:
    folder = images_folder(part)
    return lora_training.offer(training_state(part), tooltip=train_tooltip(part),
                               images=len(image_files(folder)), folder=folder,
                               trash_tooltip=trash_tooltip(lora))


def model_to_train_for(enhance_params: dict) -> str:
    chosen = enhance_params.get("checkpoint")
    if not chosen or chosen == MATCH_SOURCE_MODEL:
        return WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW].default_params()["checkpoint"]
    return chosen


def fix_title_base(part_name: str) -> str:
    return f"{part_name.capitalize()} fix"


def training_job(part, checkpoint: str) -> dict:
    models = config.COMFYUI_DIR / "models"
    version = next_version(fix_title_base(part.name))
    output_name = f"{part.name} {version}"
    return {
        "part": part.name,
        "images": [str(path) for path in training_images(part)],
        "images_folders": [str(folder) for folder in training_folders(part)],
        "image_stamps": image_stamps(part),
        "detector": str(config.COMFYUI_DIR / detector_folder(part) / detector_for_part(part)),
        "caption": f"close-up photo of {part.name}",
        "base_model": str(models / "checkpoints" / checkpoint),
        "sd_scripts": str(config.LORA_TRAINING_SCRIPTS),
        "output_dir": str(models / "loras" / FIX_LORA_FOLDER),
        "output_name": output_name,
        "lora": str(PureWindowsPath(FIX_LORA_FOLDER) / f"{output_name}.safetensors"),
        "display_name": f"{fix_title_base(part.name)} {version}",
        **lora_training.work_files(_work_folder(part)),
    }


def comfyui_python() -> Path:
    return comfyui_launcher.load(config.COMFYUI_DIR).comfyui_python()


def start(job: dict) -> lora_training.Trainer:
    return lora_training.start(job, config.LORA_TRAINING_PYTHON, TRAINER,
                               comfyui_python=str(comfyui_python()))


def trainings() -> list[dict]:
    return lora_training.trainings(config.FIX_TRAINING_DIR)


def trained_on(lora) -> str | None:
    checkpoints = config.COMFYUI_DIR / "models" / "checkpoints"
    for job in trainings():
        if job.get("output_name") == model_stem(lora) and job.get("base_model"):
            base = Path(job["base_model"])
            return str(base.relative_to(checkpoints)) if base.is_relative_to(checkpoints) else (
                base.name)
    return None


def running_trainings() -> list[dict]:
    return lora_training.running_trainings(config.FIX_TRAINING_DIR)


def note_duration(seconds: float) -> None:
    lora_training.note_duration(config.FIX_TRAINING_DIR, seconds)


def typical_seconds() -> float | None:
    return lora_training.typical_seconds(config.FIX_TRAINING_DIR)
