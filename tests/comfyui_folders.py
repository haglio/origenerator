from __future__ import annotations

import os
from pathlib import Path

from origenerator import config
from origenerator.comfyui_inputs import ComfyFolders

_THE_SUITES_COMFYUI = Path(os.environ["ORIGENERATOR_STATE_DIR"]) / "comfyui"
SUITE_FOLDERS = ComfyFolders(input=_THE_SUITES_COMFYUI / "input", temp=_THE_SUITES_COMFYUI / "temp",
                             places=config.OUTPUT_PLACES)
