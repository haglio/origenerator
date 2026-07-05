from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_DIR / "state"
DB_PATH = STATE_DIR / "origenerator.db"
THUMB_DIR = STATE_DIR / "thumbnails"
UI_STATE_PATH = STATE_DIR / "ui_state.json"

COMFYUI_DIR = Path("C:/path/to/suite-root/projects/ComfyUIApp/ComfyUI")
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
EVOLVER_INBOX_DIR = Path("C:/path/to/suite-root/videos/videos/2D/AI/0_inbox")
EVOLVER_SOURCE = "origenerator"

THUMB_SIZE = (256, 256)

# --- Funscript / OSR2 -------------------------------------------------------
# Each generated video gets a funscript synthesized alongside it (see
# funscript.py). The motion isn't measured from the video — it's a steady stroke
# at this cadence (full strokes per second), phased to the clip's duration/loop.
STROKE_DEFAULT_HZ = 1.2

# The osr2_broker sibling bridges to the OSR2 device (COM4) and forwards raw
# T-code sent to this UDP port straight to the device (osr2_broker/session.py).
# origenerator drives the device by streaming T-code here in sync with a playing
# video. While it drives, it pauses genau auto-mode by writing "0" to the broker's
# shared enabled-flag file (and restores the prior value after). All harmless
# no-ops when the broker isn't running.
OSR2_BROKER_HOST = "127.0.0.1"
OSR2_TCODE_UDP_PORT = 50557
OSR2_STATE_DIR = Path("C:/path/to/suite-root/projects/fun_time/state")
OSR2_GENAU_ENABLED_FILE = OSR2_STATE_DIR / "genau_enabled.txt"

# --- Voice command → prompt edit ------------------------------------------
# While a folder auto-generates, the mic listens (always-on); each spoken
# instruction is transcribed locally (faster-whisper, CPU) and a local LLM
# rewrites that loop's prompt. All local — no audio or prompt text leaves the
# machine. Point LOCAL_LLM_* at your own OpenAI-compatible chat server (Ollama's
# /v1, LM Studio, llama.cpp, …).
WHISPER_MODEL = "small"                           # faster-whisper size: tiny/base/small/… — small is more robust on a noisy mic
VOICE_VAD_THRESHOLD = 0.008                       # minimum speech floor; the gate self-calibrates above your mic's ambient level
LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
LOCAL_LLM_MODEL = "dolphin-llama3"                # uncensored (ollama pull dolphin-llama3); a censored model refuses explicit edits
VOICE_REWRITE_SYSTEM_PROMPT = (
    "You edit Stable Diffusion image-generation prompts from short spoken "
    "instructions. You get the current POSITIVE prompt (what to include) and "
    "NEGATIVE prompt (what to keep out), plus one instruction. Apply it and return "
    "BOTH prompts as JSON.\n"
    "Rules:\n"
    "- Positive prompts cannot negate. To exclude something (\"no X\", \"without "
    "X\", \"remove X\"), put the bare term in the NEGATIVE prompt (e.g. \"tan "
    "lines\") and delete it from the positive if it's there. Never write \"no X\" "
    "or \"without X\" in the positive prompt.\n"
    "- Emphasis uses (term:weight). If asked for MORE of something already present, "
    "raise its weight (big -> (big:1.3); (big:1.2) -> (big:1.4)). If asked for LESS "
    "of something present, lower it ((big:0.8)) or drop it if already low.\n"
    "- To add something wanted, place it among related terms (a subject with its "
    "attributes; style/quality words later), not just tacked on the end.\n"
    "- Make the smallest change that satisfies the instruction; keep everything "
    "else intact.\n"
    "- Reply with ONLY JSON: {\"positive\": \"<full positive>\", \"negative\": "
    "\"<full negative>\"}. Always include both fields, echoing one unchanged if the "
    "instruction didn't touch it."
)

# --- Category → video recipe routing --------------------------------------
# The combine panel's category dropdown resolves to one of the user's past i2v
# videos, whose recipe is then re-run on the dropped image. The same local LLM
# reads the dropped image's own prompt (its scene) plus the candidate clips'
# prompts and names the best fit. Uncensored, like the rewrite model above.
VIDEO_CATEGORY_MATCH_SYSTEM_PROMPT = (
    "You route an input image to the best-matching adult video recipe. You are "
    "given a desired act (e.g. gamma, epsilon, redacted), a description of the "
    "input image (what is in frame — bodies, positions, who is touching what, "
    "whether a anchor is already visible and where), and a numbered list of "
    "candidate clips, each described by the prompt it was generated from.\n"
    "Choose the single candidate that (1) actually depicts the desired act and "
    "(2) whose starting scene best matches the input image — same people, "
    "positions and contact (e.g. a anchor already at her mouth vs. not yet in "
    "frame). Explicit content is expected; judge it plainly and literally.\n"
    "Reply with ONLY JSON: {\"choice\": n}, where n is the number shown beside "
    "the chosen candidate, or -1 if none of them depict the desired act."
)
