"""ComfyUIApp's launcher: what starts ComfyUI, and what knows which Python runs it.

ComfyUIApp is not one of this family's packages, so its launcher is loaded by
path out of the ComfyUIApp checkout ComfyUI sits in, never imported.
"""
from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

from origenerator.comfyui_api import comfyui_responding


def script(comfyui_dir: Path) -> Path:
    return comfyui_dir.parent / "scripts" / "comfyui_server.py"


def load(comfyui_dir: Path):
    spec = importlib.util.spec_from_file_location("comfyui_server", script(comfyui_dir))
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher


def ensure_comfyui_server(logger, host, port, comfyui_dir, on_status=None, pump_events=None):
    if comfyui_responding(host, port):
        logger.info("ComfyUI server already running on %s:%d", host, port)
        return

    if _port_open(host, port):
        logger.warning(
            "Port %d is occupied by a non-ComfyUI server; ComfyUI cannot start there. "
            "Stop that process (or change COMFYUI_PORT) and relaunch Origenerator.",
            port,
        )
        return

    server_script = script(comfyui_dir)
    if not server_script.exists():
        logger.warning("ComfyUI not running and launcher not found at %s", server_script)
        return

    try:
        server = load(comfyui_dir)
        logger.info("Starting ComfyUI server via %s...", server_script)
        result = server.start(base_dir=comfyui_dir.parent, on_status=on_status,
                              pump_events=pump_events)
        if result.started:
            logger.info("ComfyUI server started (PID %s)", result.pid)
        elif result.error:
            logger.warning("ComfyUI server failed to start: %s", result.error)
        else:
            logger.info("ComfyUI server was already running")
    except Exception as e:
        logger.warning("Failed to start ComfyUI server: %s", e)


def _port_open(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False
