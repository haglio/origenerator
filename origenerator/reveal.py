"""Show a file selected in Windows Explorer — the param form's "Show in Explorer".

Explorer selects a file with ``/select,<path>`` and returns a non-zero exit code even on success.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Windows flashes a console window for a bare subprocess.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def show_in_explorer(path: Path) -> None:
    subprocess.run(["explorer", "/select,", os.path.realpath(path)], creationflags=_NO_WINDOW,
                   check=False)


def open_in_explorer(folder: Path) -> None:
    subprocess.run(["explorer", os.path.realpath(folder)], creationflags=_NO_WINDOW, check=False)
