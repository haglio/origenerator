from __future__ import annotations

import os
from pathlib import Path

from origenerator.comfyui_inputs import ComfyFolders
from origenerator.output_places import OutputPlaces

_THE_SUITES_COMFYUI = Path(os.environ["ORIGENERATOR_STATE_DIR"]) / "comfyui"
SUITE_FOLDERS = ComfyFolders(input=_THE_SUITES_COMFYUI / "input", temp=_THE_SUITES_COMFYUI / "temp",
                             places=OutputPlaces.in_one_folder(_THE_SUITES_COMFYUI / "output"))
