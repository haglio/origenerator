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

# --- Voice command → prompt edit ------------------------------------------
# Push-to-talk speech is transcribed locally (faster-whisper on the CPU) and a
# local LLM rewrites the current prompt per the spoken instruction. All local —
# no audio or prompt text leaves the machine. Point LOCAL_LLM_* at your own
# OpenAI-compatible chat server (Ollama's /v1, LM Studio, llama.cpp, …) and set
# the model you run.
WHISPER_MODEL = "base"                            # faster-whisper size: tiny/base/small/…
VOICE_VAD_THRESHOLD = 0.02                         # mic RMS above which a frame counts as speech; raise if it trips on background noise
LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
LOCAL_LLM_MODEL = "llama3.1"                       # the chat model that rewrites prompts
VOICE_REWRITE_SYSTEM_PROMPT = (
    "You edit image-generation prompts. Given the current prompt and a spoken "
    "instruction, apply the change and reply with ONLY the full revised prompt — "
    "no quotes, no explanation, no preamble. Preserve the parts of the prompt the "
    "instruction doesn't touch."
)
