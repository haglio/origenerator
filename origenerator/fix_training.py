from __future__ import annotations

from pathlib import Path, PureWindowsPath

from origenerator import comfyui_launcher, config, gallery, lora_training
from origenerator.gallery.enhance_settings import MATCH_SOURCE_MODEL
from origenerator.lora_training import TrainingOffer, TrainingState
from origenerator.lora_versions import next_version
from origenerator.model_titles import FIX_LORA_FOLDER
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detector_folder, detector_for_part, part_table

TRAINER = lora_training.TRAINERS / "fix_lora_trainer.py"
HOLDS_THE_LINE = True
FIRST_STATE = "cropping"
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def photos_folder(part) -> Path:
    return config.FIX_PHOTOS_DIR / part.name.lower()


def shared_photos_folder() -> Path:
    return config.FIX_PHOTOS_DIR / "shared"


def photo_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in _PHOTO_SUFFIXES)


def training_folders(part) -> list[Path]:
    return [photos_folder(part)] + ([shared_photos_folder()] if part.shared_photos else [])


def training_photos(part) -> list[Path]:
    return [photo for folder in training_folders(part) for photo in photo_files(folder)]


def photo_stamps(part) -> dict[str, list[int]]:
    return lora_training.picture_stamps(training_photos(part))


def _work_folder(part) -> Path:
    return config.FIX_TRAINING_DIR / part.name


def training_state(part) -> TrainingState:
    return lora_training.training_state(_work_folder(part) / "trained.json", photo_stamps(part))


def train_tooltip(part) -> str:
    folders = (f"{part.name.lower()}, and in fixes\\shared," if part.shared_photos
               else f"{part.name.lower()},")
    return ("Trains this fix a LoRA from the photos in the library's "
            f"app_data\\origenerator\\fixes\\{folders} each cropped down to the part by the "
            "fix's own detector. Nothing generates while it trains.")


def training_offer(part) -> TrainingOffer:
    folder = photos_folder(part)
    return lora_training.offer(training_state(part), tooltip=train_tooltip(part),
                               pictures=len(photo_files(folder)), folder=folder, counted="photo")


def fix_to_train():
    return next((part for part in part_table()
                 if detector_for_part(part) and training_photos(part)
                 and training_state(part) is not TrainingState.CURRENT), None)


def model_to_train_for(enhance_params: dict) -> str:
    chosen = enhance_params.get("checkpoint")
    if not chosen or chosen == MATCH_SOURCE_MODEL:
        return WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW].default_params()["checkpoint"]
    return chosen


def fix_title_base(part_name: str) -> str:
    return f"{part_name.capitalize()} fix"


def training_job(part, checkpoint: str, *, automatic: bool = False) -> dict:
    models = config.COMFYUI_DIR / "models"
    version = next_version(fix_title_base(part.name))
    output_name = f"{part.name} {version}"
    return {
        "part": part.name,
        "photos": [str(path) for path in training_photos(part)],
        "photos_folders": [str(folder) for folder in training_folders(part)],
        "photo_stamps": photo_stamps(part),
        "detector": str(config.COMFYUI_DIR / detector_folder(part) / detector_for_part(part)),
        "caption": f"close-up photo of {part.name}",
        "base_model": str(models / "checkpoints" / checkpoint),
        "sd_scripts": str(config.LORA_TRAINING_SCRIPTS),
        "output_dir": str(models / "loras" / FIX_LORA_FOLDER),
        "output_name": output_name,
        "lora": str(PureWindowsPath(FIX_LORA_FOLDER) / f"{output_name}.safetensors"),
        "display_name": f"{fix_title_base(part.name)} {version}",
        **lora_training.work_files(_work_folder(part)),
        "automatic": automatic,
    }


def comfyui_python() -> Path:
    return comfyui_launcher.load(config.COMFYUI_DIR).comfyui_python()


def start(job: dict) -> lora_training.Trainer:
    return lora_training.start(job, config.LORA_TRAINING_PYTHON, TRAINER,
                               comfyui_python=str(comfyui_python()))


def trainings() -> list[dict]:
    return lora_training.trainings(config.FIX_TRAINING_DIR)


def running_trainings() -> list[dict]:
    return lora_training.running_trainings(config.FIX_TRAINING_DIR)


def note_duration(seconds: float) -> None:
    lora_training.note_duration(config.FIX_TRAINING_DIR, seconds)


def typical_seconds() -> float | None:
    return lora_training.typical_seconds(config.FIX_TRAINING_DIR)
