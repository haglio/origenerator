from pathlib import Path
from typing import Any

from origenerator.content import load_content

PROJECT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_DIR / "state"
DB_PATH = STATE_DIR / "origenerator.db"
THUMB_DIR = STATE_DIR / "thumbnails"
UI_STATE_PATH = STATE_DIR / "ui_state.json"

_CONTENT = load_content()
# Public now: the tests assert which paths still hang off the media-library root
# and which come from the project roots, and that split is the thing worth
# pinning -- getting it backwards silently repoints a live app at nothing.
SUITE_ROOT = Path(_CONTENT["suite_root"])


def project_roots(content: dict[str, Any] | None = None) -> tuple[Path, ...]:
    """The folders that hold the suite's own app checkouts, in search order.

    ``suite_root`` used to answer this as well as naming where the media library
    and the third-party apps are, and one folder was the answer to all of it.
    The suite's *own* repos then moved out of the file-synced tree the library
    stays in, so they get their own key; everything that did not move --
    the library, ComfyUI -- keeps reading ``suite_root``.

    A *list*, because the move runs one repo at a time: with a single path there
    is a window where a sibling that has not moved yet is unreachable. An
    overlay that says nothing still means ``suite_root/projects``, as before.
    """
    content = _CONTENT if content is None else content
    roots = content.get("project_roots")
    if not roots:
        return (Path(content["suite_root"]) / "projects",)
    return tuple(Path(root) for root in roots)


PROJECT_ROOTS = project_roots()


def ambient_audio_dir(content: dict[str, Any] | None = None) -> Path | None:
    """The folder the audio switch shuffles clips out of, or ``None`` for none.

    *Which* folder of the library it is describes the library, so it comes from
    the overlay rather than from source. A relative value hangs off
    ``suite_root`` -- where it in fact sits -- and an absolute one is taken as
    given, so a folder outside the library tree works too.
    """
    content = _CONTENT if content is None else content
    raw = content.get("ambient_audio_dir")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else Path(content["suite_root"]) / path


AMBIENT_AUDIO_DIR = ambient_audio_dir()
# How many clips the audio bed plays at once. Each voice walks its own shuffled
# pass of the folder, so they drift apart the moment two clip lengths differ.
AMBIENT_AUDIO_VOICES = 3


def project_dir(name: str, roots: tuple[Path, ...] | None = None) -> Path:
    """The sibling checkout *name*, from the first root that actually holds it.

    Falls back to a path under the first root when no root does: every consumer
    here already guards on existence (the OSR2 handoff is a no-op when the
    broker isn't running), so a missing sibling must not be an import-time crash.
    """
    roots = PROJECT_ROOTS if roots is None else roots
    for root in roots:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return roots[0] / name


# The media library and the third-party apps live outside this repo; their
# location is private, so it comes from the content overlay. ComfyUI is not one
# of the suite's own repos and did not move with them, so it stays on the suite
# root rather than coming from the project roots.
COMFYUI_DIR = SUITE_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"
COMFYUI_OUTPUT_DIR = COMFYUI_DIR / "output"
COMFYUI_INPUT_DIR = COMFYUI_DIR / "input"
# ComfyUI writes its console log here (rotated as comfyui.log, .prev.log, …);
# the "Prompt executed in N seconds" lines feed duration backfill.
COMFYUI_LOG_DIR = COMFYUI_DIR / "user"

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188

# Evolver (the sibling video-maintenance app) watches this inbox and ingests any
# finalized video dropped under a per-source subfolder. Mirrors evolver's own
# INBOX_DIR; we write under our own source name so Evolver can route
# Origenerator's videos distinctly from other inbox sources.
EVOLVER_INBOX_DIR = SUITE_ROOT / "videos" / "videos" / "2D" / "AI" / "0_inbox"
EVOLVER_SOURCE = "origenerator"
# A Genau clip goes to the same inbox under its own source name. Evolver routes by
# that name, so the folder is the whole signal: it upscales the clip on its usual
# schedule and then delivers the result to Genau's clips folder rather than leaving
# it in the outbox. Sending straight to Genau's folder instead would skip the
# upscale, and a loop straight out of the graph is visibly softer than the clips
# already there.
#
# From the overlay, not from source, because naming a folder in the library makes
# that name library vocabulary: the sanitize blocklist exists to keep exactly that
# out of a public commit, so hardcoding one here writes it into the tracked tree. Evolver reads the same key from its own overlay
# and the two have to agree — the folder is the only thing passing between them.
GENAU_SOURCE = _CONTENT["genau_source"]

# The curated pose references the SDXL Pose Transfer workflow is steered by. Its
# Structure Image picker opens here rather than in ComfyUI's input folder, which
# collects generated frames instead; LoadImage takes the absolute path back
# unchanged, so drawing the input from outside costs nothing. Built from the
# library root because that root is private and must stay out of source.
CUSTOM_POSES_DIR = SUITE_ROOT / "images" / "custom_poses"

# --- Funscript / OSR2 -------------------------------------------------------
# Each generated video gets a funscript synthesized alongside it (see
# funscript.py). The motion isn't measured from the video — it's a steady stroke
# at this cadence (full strokes per second), phased to the clip's duration/loop.
STROKE_DEFAULT_HZ = 1.2

# The broker sibling bridges to the OSR2 device (COM4) and forwards raw
# T-code sent to this UDP port straight to the device (osr2_broker/session.py).
# origenerator drives the device by streaming T-code here in sync with a playing
# video. While it drives, it pauses genau auto-mode by writing "0" to the broker's
# shared enabled-flag file (and restores the prior value after). All harmless
# no-ops when the broker isn't running.
OSR2_BROKER_HOST = "127.0.0.1"
OSR2_TCODE_UDP_PORT = 50557
OSR2_STATE_DIR = project_dir("fun_time") / "state"
OSR2_GENAU_ENABLED_FILE = OSR2_STATE_DIR / "genau_enabled.txt"
# The broker stamps this with the time the OSR2 last spoke. It is the only
# evidence that the device is there — the console reads it to say "Off" and grey
# its readout (see origenerator.osr2.device_on). The broker writes a second stamp
# for what it last *sent*, deliberately not read here: this app's own stroke
# would keep it fresh against a device that is switched off.
OSR2_SERIAL_RX_FILE = OSR2_STATE_DIR / "osr2_serial_rx.txt"
# How long the device may stay quiet and still count as on — the broker's own
# window for the same question (osr2_broker.monitor.MonitorState), so the app and
# the broker never disagree about whether the OSR2 is there.
OSR2_RX_STALE_S = 30.0

# --- Voice command → prompt edit ------------------------------------------
# While a folder auto-generates, the mic listens (always-on); each spoken
# instruction is transcribed locally (faster-whisper, CPU) and a local LLM
# rewrites that loop's prompt. All local — no audio or prompt text leaves the
# machine. Point LOCAL_LLM_* at your own OpenAI-compatible chat server (Ollama's
# /v1, LM Studio, llama.cpp, …). What the LLM is *told* is behavior rather than
# configuration and lives in origenerator.prompts.
WHISPER_MODEL = "small"                           # faster-whisper size: tiny/base/small/… — small is more robust on a noisy mic
VOICE_VAD_THRESHOLD = 0.008                       # minimum speech floor; the gate self-calibrates above your mic's ambient level
LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
LOCAL_LLM_MODEL = "dolphin-llama3"                # uncensored (ollama pull dolphin-llama3); a censored model refuses explicit edits
# --- the LLM's system prompts (see origenerator.prompts) --------------------
# Re-exported so the twenty-four modules that import config kept working when
# the prompts moved out; a consumer written from here on should import them from
# origenerator.prompts directly.
from origenerator.prompts import (  # noqa: E402,F401
    SEARCH_EXPANSION_SYSTEM_PROMPT,
    VIDEO_SCENE_MATCH_SYSTEM_PROMPT,
    VOICE_REQUEST_MATCH_SYSTEM_PROMPT,
    VOICE_REWRITE_SYSTEM_PROMPT,
)
