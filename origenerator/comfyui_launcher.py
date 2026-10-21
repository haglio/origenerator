"""ComfyUIApp's launcher: what starts ComfyUI, and what knows which Python runs it.

ComfyUIApp is not one of this family's packages, so its launcher is loaded by
path out of the ComfyUIApp checkout ComfyUI sits in, never imported.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def script(comfyui_dir: Path) -> Path:
    return comfyui_dir.parent / "scripts" / "comfyui_server.py"


def load(comfyui_dir: Path):
    spec = importlib.util.spec_from_file_location("comfyui_server", script(comfyui_dir))
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher
