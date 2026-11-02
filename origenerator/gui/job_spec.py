from __future__ import annotations

from dataclasses import dataclass

from origenerator.config import COMFYUI_INPUT_DIR, OUTPUT_PLACES, THUMB_DIR
from origenerator.generation_state import GenerationSource


@dataclass(frozen=True)
class JobSpec:
    workflow: object
    params: dict
    source: str = GenerationSource.GENERATED
    prompt_id: str | None = None


@dataclass(frozen=True)
class JobFolders:
    places: object = OUTPUT_PLACES
    thumb_dir: object = THUMB_DIR
    input_dir: object = COMFYUI_INPUT_DIR


NO_FOLDERS = JobFolders()
