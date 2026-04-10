from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_DIR / "state"
DB_PATH = STATE_DIR / "origenerator.db"
THUMB_DIR = STATE_DIR / "thumbnails"

COMFYUI_DIR = Path("C:/path/to/suite-root/projects/ComfyUIApp/ComfyUI")
COMFYUI_OUTPUT_DIR = COMFYUI_DIR / "output"
COMFYUI_INPUT_DIR = COMFYUI_DIR / "input"

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188

THUMB_SIZE = (256, 256)
