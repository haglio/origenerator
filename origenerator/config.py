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
