from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app_support import haglio_settings, siblings
from funestra.robot_hand import bpm_for_speed

from origenerator.branch_session import is_branch_session
from origenerator.content import load_content

PROJECT_DIR = Path(__file__).resolve().parents[1]
# The checkout's own state directory, unless the process says otherwise.  Only
# the suite says otherwise: it points every run at a fresh temporary directory
# before this module is imported, so three thousand tests stop writing a log,
# the spinner arrows, thumbnails, trash and a diagnostic recording into the
# production app's state/ -- where what a previous run left decided what the
# next one drew.  Every path below hangs off it, and every module that binds
# one of them at import gets the same answer, which a test's monkeypatch of
# this module never could.
_TOLD_WHERE_STATE_IS = os.environ.get("ORIGENERATOR_STATE_DIR")
STATE_DIR = Path(_TOLD_WHERE_STATE_IS or PROJECT_DIR / "state")
UI_STATE_PATH = STATE_DIR / "ui_state.json"
FRAMES_BEING_MADE_DIR = STATE_DIR / "frames_being_made"
_BRANCH_SESSION = is_branch_session()

_CONTENT = load_content()
# Public now: the tests assert which paths still hang off the media-library root
# and which come from the project roots, and that split is the thing worth
# pinning -- getting it backwards silently repoints a production app at nothing.
LIBRARY_ROOT = Path(haglio_settings.value("library_root"))


PROJECT_ROOTS = haglio_settings.project_roots()


def ambient_audio_dir(settings: dict[str, Any] | None = None) -> Path | None:
    """The folder the audio switch shuffles clips out of, or ``None`` for none.

    *Which* folder of the library it is describes the library, so it comes from
    the settings all of Haglio shares rather than from source. A relative value
    hangs off ``library_root`` -- where it in fact sits -- and an absolute one is
    taken as given, so a folder outside the library tree works too.
    """
    settings = haglio_settings.load() if settings is None else settings
    raw = settings.get("ambient_audio_dir")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else Path(settings["library_root"]) / path


AMBIENT_AUDIO_DIR = ambient_audio_dir()


def speech_python(content: dict[str, Any] | None = None) -> Path | None:
    """The Python that speaks a story's lines (see :mod:`origenerator.speech`),
    or ``None`` when no voice is set up.

    Qwen3-TTS pins a torch and a transformers that would break this app's own
    environment and ComfyUI's, so it lives in one of its own, and which one is
    a fact about the machine: the overlay names its interpreter. Absent, a
    recipe with lines fails at submit saying so, rather than the app guessing
    at an environment that may not exist.
    """
    return _overlay_path("speech_python", content)


def _overlay_path(key: str, content: dict[str, Any] | None = None) -> Path | None:
    content = _CONTENT if content is None else content
    raw = content.get(key)
    return Path(raw) if raw else None


SPEECH_PYTHON = speech_python()
# kohya's sd-scripts, which trains a fix's LoRA (see :mod:`origenerator.fix_training`),
# and the Python of the environment it lives in: its pins are not this app's either.
LORA_TRAINING_PYTHON = _overlay_path("lora_training_python")
LORA_TRAINING_SCRIPTS = _overlay_path("lora_training_scripts")
# How many clips the audio bed plays at once. Each voice walks its own shuffled
# pass of the folder, so they drift apart the moment two clip lengths differ.
AMBIENT_AUDIO_VOICES = 3


def project_dir(name: str, roots: tuple[Path, ...] | None = None) -> Path:
    """The sibling checkout *name*, from the first root that actually holds it.

    Falls back to a path under the first root when no root does: every consumer
    here already guards on existence (the OSR2 handoff is a no-op when the
    broker isn't running), so a missing sibling must not be an import-time crash.
    """
    return siblings.project_dir(name, PROJECT_ROOTS if roots is None else roots)


# The production app and every preview open the production checkout's database,
# so every instance shows every generation; its thumbnails and Trash live in the
# library itself, beside the copy of its records. Only what is about this
# window alone (UI_STATE_PATH, the logs) stays in the checkout that runs it.
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
TRASH_DIR = _LIBRARY_FILES_DIR / "trash"
FIX_PHOTOS_DIR = _LIBRARY_FILES_DIR / "fix photos"
FIX_TRAINING_DIR = _LIBRARY_FILES_DIR / "fix training"
LIBRARY_OVERLAY_PATH = LIBRARY_STATE_DIR.parent / "content.local.json"


# The media library and the third-party apps live outside this repo; their
# location is private, so it comes from the content overlay. ComfyUI is not one
# of the suite's own repos and did not move with them, so it stays on the suite
# root rather than coming from the project roots.
COMFYUI_DIR = LIBRARY_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"


def comfyui_output_dir(settings: dict[str, Any], comfyui_dir: Path) -> Path:
    named = settings.get("comfyui_output_dir")
    return Path(named) if named else comfyui_dir / "output"


COMFYUI_OUTPUT_DIR = comfyui_output_dir(haglio_settings.load(), COMFYUI_DIR)
COMFYUI_INPUT_DIR = COMFYUI_DIR / "input"
# Where ComfyUI keeps a ``name [temp]`` LoadImage source -- a preview or a
# node's scratch output, the third place its LoadImage can point.
COMFYUI_TEMP_DIR = COMFYUI_DIR / "temp"
# ComfyUI writes its console log here (rotated as comfyui.log, .prev.log, …);
# the "Prompt executed in N seconds" lines feed duration backfill.
COMFYUI_LOG_DIR = COMFYUI_DIR / "user"

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188

# Evolver (the sibling video-maintenance app) watches this inbox and ingests any
# finalized video dropped under a per-source subfolder; we write under our own
# source name so it can route Origenerator's videos distinctly from other inbox
# sources, and it files the upscale it makes of each one in the folder below.
#
# Both folders are Evolver's, and both were spelled here from reading its
# source, with nothing comparing the two. It publishes them now, library-relative,
# in `evolver_contract.json` at the checkout `project_dir("evolver")` resolves, and
# tests/test_evolver_pipeline_contract.py holds these to that document -- the
# only place the two can be compared, since neither repo's gate clones the other.
_EVOLVER_AI_DIR = LIBRARY_ROOT / "videos" / "videos" / "2D" / "AI"
EVOLVER_INBOX_DIR = _EVOLVER_AI_DIR / "0_inbox"
EVOLVER_SOURCE = "origenerator"
EVOLVER_UPSCALED_DIR = _EVOLVER_AI_DIR / "2_outbox" / "upscaled_by_orientation"
# A Genau flick goes to the same inbox under its own source name. Evolver routes by
# that name, so the folder is the whole signal: it upscales the clip on its usual
# schedule and then delivers the result to Genau's flicks folder rather than leaving
# it in the outbox. Sending straight to Genau's folder instead would skip the
# upscale, and a loop straight out of the graph is visibly softer than the clips
# already there.
#
# From the settings all of Haglio shares, not from source, because naming a folder
# in the library makes that name library vocabulary: the sanitize blocklist exists
# to keep exactly that out of a public commit. Evolver reads the same setting --
# the folder is the only thing passing between them.
GENAU_SOURCE = haglio_settings.value("genau_source")

# The curated pose references the SDXL Pose Transfer workflow is steered by. Its
# Structure Image picker opens here rather than in ComfyUI's input folder, which
# collects generated frames instead; LoadImage takes the absolute path back
# unchanged, so drawing the input from outside costs nothing. Built from the
# library root because that root is private and must stay out of source.
CUSTOM_POSES_DIR = LIBRARY_ROOT / "images" / "custom_poses"

# --- Funscript ---------------------------------------------------------------
MOTION_DEFAULT_SPEED = 50
MOTION_DEFAULT_HZ = bpm_for_speed(MOTION_DEFAULT_SPEED) / 60

# --- Voice command → prompt edit ------------------------------------------
# While a folder auto-generates, the mic listens (always-on); each spoken
# instruction is heard locally (voice_core: vosk and faster-whisper, CPU) and a
# local LLM rewrites that loop's prompt. All local — no audio or prompt text leaves
# the machine. Point LOCAL_LLM_* at your own OpenAI-compatible chat server (Ollama's
# /v1, LM Studio, llama.cpp, …). What the LLM is *told* is behavior rather than
# configuration and lives in origenerator.prompts.
VOICE_MODEL_NAME = "vosk-model-en-us-0.22-lgraph"  # the vosk model Fun Time listens with; cached under ~/.cache/vosk
# A substring of the microphone's name, the one Evolver's backfill tool pins too: Windows has made
# a dead headset microphone the default input before. None, or a name nothing answers to today,
# listens to the liveliest input instead (`python -m sounddevice` lists the names).
VOICE_DEVICE_NAME = "Brio"
LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
LOCAL_LLM_MODEL = "dolphin-llama3"                # uncensored (ollama pull dolphin-llama3); a censored model refuses explicit edits
