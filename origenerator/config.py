from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app_support import siblings

from origenerator.content import load_content, overlay_value

PROJECT_DIR = Path(__file__).resolve().parents[1]
# The checkout's own state directory, unless the process says otherwise.  Only
# the suite says otherwise: it points every run at a fresh temporary directory
# before this module is imported, so three thousand tests stop writing a log,
# the spinner arrows, thumbnails, trash and a diagnostic recording into the
# live app's state/ -- where what a previous run left decided what the
# next one drew.  Every path below hangs off it, and every module that binds
# one of them at import gets the same answer, which a test's monkeypatch of
# this module never could.
STATE_DIR = Path(os.environ.get("ORIGENERATOR_STATE_DIR") or PROJECT_DIR / "state")
UI_STATE_PATH = STATE_DIR / "ui_state.json"
# Set by the preview launcher and never by the live one: this run is a worktree's
# code shown for judging, not the live install (see origenerator.branch_session).
BRANCH_SESSION_FLAG = "ORIGENERATOR_BRANCH_SESSION"
_BRANCH_SESSION = os.environ.get(BRANCH_SESSION_FLAG) == "1"

_CONTENT = load_content()
# Public now: the tests assert which paths still hang off the media-library root
# and which come from the project roots, and that split is the thing worth
# pinning -- getting it backwards silently repoints a live app at nothing.
LIBRARY_ROOT = Path(overlay_value(_CONTENT, "library_root"))


def project_roots(content: dict[str, Any] | None = None) -> tuple[Path, ...]:
    """The folders that hold the suite's own app checkouts, in search order.

    A key of its own, because the suite's *own* repos live outside the
    file-synced tree the media library stays in; everything that does not --
    the library, ComfyUI -- keeps reading ``library_root``.

    A *list*, because the move runs one repo at a time: with a single path there
    is a window where a sibling that has not moved yet is unreachable. An
    overlay that says nothing still means ``library_root/projects``, as before.
    """
    content = _CONTENT if content is None else content
    return siblings.project_roots(
        content.get("project_roots"),
        fallback=Path(overlay_value(content, "library_root")) / "projects")


PROJECT_ROOTS = project_roots()


def ambient_audio_dir(content: dict[str, Any] | None = None) -> Path | None:
    """The folder the audio switch shuffles clips out of, or ``None`` for none.

    *Which* folder of the library it is describes the library, so it comes from
    the overlay rather than from source. A relative value hangs off
    ``library_root`` -- where it in fact sits -- and an absolute one is taken as
    given, so a folder outside the library tree works too.
    """
    content = _CONTENT if content is None else content
    raw = content.get("ambient_audio_dir")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else Path(content["library_root"]) / path


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
    content = _CONTENT if content is None else content
    raw = content.get("speech_python")
    return Path(raw) if raw else None


SPEECH_PYTHON = speech_python()
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


# The library's own state -- the database, the thumbnails it draws, the trash
# its deletes go to -- is the live install's wherever this app runs from: a
# branch session reads and writes the primary checkout's, so every instance
# shows every generation, whichever of them made it. Only what is about this
# window alone (UI_STATE_PATH, the logs) stays in the checkout that runs it.
LIBRARY_STATE_DIR = project_dir("origenerator") / "state" if _BRANCH_SESSION else STATE_DIR
DB_PATH = LIBRARY_STATE_DIR / "origenerator.db"
THUMB_DIR = LIBRARY_STATE_DIR / "thumbnails"
TRASH_DIR = LIBRARY_STATE_DIR / "trash"


# The media library and the third-party apps live outside this repo; their
# location is private, so it comes from the content overlay. ComfyUI is not one
# of the suite's own repos and did not move with them, so it stays on the suite
# root rather than coming from the project roots.
COMFYUI_DIR = LIBRARY_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"
COMFYUI_OUTPUT_DIR = COMFYUI_DIR / "output"
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
# A Genau clip goes to the same inbox under its own source name. Evolver routes by
# that name, so the folder is the whole signal: it upscales the clip on its usual
# schedule and then delivers the result to Genau's clips folder rather than leaving
# it in the outbox. Sending straight to Genau's folder instead would skip the
# upscale, and a loop straight out of the graph is visibly softer than the clips
# already there.
#
# From the overlay, not from source, because naming a folder in the library makes
# that name library vocabulary: the sanitize blocklist exists to keep exactly that
# out of a public commit, so hardcoding one here writes it into the tracked tree.
# Evolver reads the same key from its own overlay and the two have to agree — the
# folder is the only thing passing between them.
GENAU_SOURCE = _CONTENT["genau_source"]

# The curated pose references the SDXL Pose Transfer workflow is steered by. Its
# Structure Image picker opens here rather than in ComfyUI's input folder, which
# collects generated frames instead; LoadImage takes the absolute path back
# unchanged, so drawing the input from outside costs nothing. Built from the
# library root because that root is private and must stay out of source.
CUSTOM_POSES_DIR = LIBRARY_ROOT / "images" / "custom_poses"

# --- Funscript ---------------------------------------------------------------
# Each generated video gets a funscript synthesized alongside it (see
# funscript.py). The motion isn't measured from the video — it's a steady motion
# at this cadence (full cycles per second), phased to the clip's duration/loop.
MOTION_DEFAULT_HZ = 1.2

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
