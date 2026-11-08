from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app_support import haglio_settings, siblings
from funestra.robot_hand import bpm_for_speed

from origenerator.branch_session import THIS_CHECKOUT, is_branch_session
from origenerator.comfyui_inputs import ComfyFolders
from origenerator.content import load_content
from origenerator.db_connection import SqliteFile
from origenerator.db_trash import TrashStore
from origenerator.output_places import OutputPlaces

PROJECT_DIR = THIS_CHECKOUT
_TOLD_WHERE_STATE_IS = os.environ.get("ORIGENERATOR_STATE_DIR")
STATE_DIR = Path(_TOLD_WHERE_STATE_IS or PROJECT_DIR / "state")
UI_STATE_PATH = STATE_DIR / "ui_state.json"
FRAMES_BEING_MADE_DIR = STATE_DIR / "frames_being_made"
_BRANCH_SESSION = is_branch_session()

_CONTENT = load_content()
LIBRARY_ROOT = Path(haglio_settings.value("library_root"))


PROJECT_ROOTS = haglio_settings.project_roots()


def radio_dir(settings: dict[str, Any] | None = None) -> Path | None:
    settings = haglio_settings.load() if settings is None else settings
    raw = settings.get("ambient_audio_dir")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else Path(settings["library_root"]) / path


RADIO_DIR = radio_dir()


def speech_python(content: dict[str, Any] | None = None) -> Path | None:
    return _overlay_path("speech_python", content)


def _overlay_path(key: str, content: dict[str, Any] | None = None) -> Path | None:
    content = _CONTENT if content is None else content
    raw = content.get(key)
    return Path(raw) if raw else None


SPEECH_PYTHON = speech_python()
LORA_TRAINING_PYTHON = _overlay_path("lora_training_python")
LORA_TRAINING_SCRIPTS = _overlay_path("lora_training_scripts")
KREA2_TRAINING_PYTHON = _overlay_path("krea2_training_python")
KREA2_TRAINING_SCRIPTS = _overlay_path("krea2_training_scripts")
RADIO_STATIONS = 3


def project_dir(name: str, roots: tuple[Path, ...] | None = None) -> Path:
    return siblings.project_dir(name, PROJECT_ROOTS if roots is None else roots)


RECORDS_DIR = LIBRARY_ROOT / "app_data" / "origenerator"
_THE_LIBRARYS_CHECKOUT = project_dir("origenerator")
PRODUCTION_CHECKOUT = _THE_LIBRARYS_CHECKOUT if _BRANCH_SESSION else PROJECT_DIR
LIBRARY_STATE_DIR = PRODUCTION_CHECKOUT / "state" if _BRANCH_SESSION else STATE_DIR
DB_PATH = LIBRARY_STATE_DIR / "origenerator.db"
OPENS_THE_LIBRARY = (not _TOLD_WHERE_STATE_IS and LIBRARY_STATE_DIR.resolve()
                     == (_THE_LIBRARYS_CHECKOUT / "state").resolve())
_LIBRARY_FILES_DIR = RECORDS_DIR if OPENS_THE_LIBRARY else STATE_DIR
STARTS_A_LIBRARY_OF_ITS_OWN = not (OPENS_THE_LIBRARY or _TOLD_WHERE_STATE_IS)
THUMB_DIR = _LIBRARY_FILES_DIR / "thumbnails"
STARTING_FRAMES_DIR = _LIBRARY_FILES_DIR / "starting frames"
TRASH_DIR = _LIBRARY_FILES_DIR / "trash"
FIX_IMAGES_DIR = _LIBRARY_FILES_DIR / "fixes"
FIX_TRAINING_DIR = LIBRARY_STATE_DIR / "fix training"
LOOK_TRAINING_DIR = LIBRARY_STATE_DIR / "lora training"
MODEL_TITLES_PATH = _LIBRARY_FILES_DIR / "model_titles.json"
TRIGGER_WORDS_PATH = _LIBRARY_FILES_DIR / "trigger_words.json"
BASE_MODELS_PATH = _LIBRARY_FILES_DIR / "base_models.json"
COLLECTION_NOTES_PATH = _LIBRARY_FILES_DIR / "collection_notes.json"
LIBRARY_OVERLAY_PATH = LIBRARY_STATE_DIR.parent / "content.local.json"


COMFYUI_DIR = LIBRARY_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"


LIBRARY_VIDEOS_DIR = LIBRARY_ROOT / "videos" / "videos"
LIBRARY_SCRIPTS_DIR = LIBRARY_ROOT / "videos" / "scripts" / "scripts"

EVOLVER_AI_DIR = LIBRARY_VIDEOS_DIR / "2D" / "AI"
EVOLVER_INBOX_DIR = EVOLVER_AI_DIR / "0_inbox"
EVOLVER_SOURCE = "origenerator"
EVOLVER_UPSCALED_DIR = EVOLVER_AI_DIR / "2_outbox" / "upscaled_by_orientation"
KINO_TRASH_DIR = EVOLVER_AI_DIR / "2_outbox" / "trash"

OUTPUT_PLACES = OutputPlaces.from_settings(haglio_settings.load(), comfyui_dir=COMFYUI_DIR,
                                           trash=TRASH_DIR, kino_library=EVOLVER_UPSCALED_DIR)
COMFYUI_INPUT_DIR = COMFYUI_DIR / "input"
COMFYUI_TEMP_DIR = COMFYUI_DIR / "temp"
COMFYUI_FOLDERS = ComfyFolders(input=COMFYUI_INPUT_DIR, places=OUTPUT_PLACES, temp=COMFYUI_TEMP_DIR,
                               trashed=TrashStore(SqliteFile(DB_PATH)).trashed_file)
# ComfyUI writes its console log here (rotated as comfyui.log, .prev.log, …);
# the "Prompt executed in N seconds" lines feed duration backfill.
COMFYUI_LOG_DIR = COMFYUI_DIR / "user"

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188

GENAU_SOURCE = haglio_settings.value("genau_source")

CUSTOM_POSES_DIR = LIBRARY_ROOT / "images" / "custom_poses"

MOTION_DEFAULT_SPEED = 50
MOTION_DEFAULT_HZ = bpm_for_speed(MOTION_DEFAULT_SPEED) / 60

VOICE_MODEL_NAME = "vosk-model-en-us-0.22-lgraph"  # the vosk model Fun Time listens with; cached under ~/.cache/vosk
# Windows has made a dead headset microphone the default input before.
VOICE_DEVICE_NAME = "Brio"
LOCAL_LLM_BASE_URL = "http://localhost:11434"
LOCAL_LLM_MODEL = "huihui_ai/qwen3.5-abliterated:9b"
