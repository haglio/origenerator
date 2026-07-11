"""Show a file selected in Windows Explorer — the param form's "Show in Explorer".

Opening the containing folder isn't enough; revealing means landing on the file
itself, highlighted. Explorer does that with ``/select,<path>`` and — quirkily —
returns a non-zero exit code even on success, so the result is never checked.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Suppress the console-window flash Windows shows for a bare subprocess.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def show_in_explorer(path: Path) -> None:
    """Open Explorer with ``path`` selected. The caller ensures ``path`` exists;
    otherwise Explorer ignores the selection and opens a default location."""
    subprocess.run(["explorer", "/select,", str(path)], creationflags=_NO_WINDOW)
