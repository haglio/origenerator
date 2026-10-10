"""Origenerator's loading screen: the family's loading window, in a process of its own."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from shared_ui.loading_process import LoadingProcess
from shared_ui.loading_window import Loading, LoadingCanceled
from shared_ui.preview import Preview

if TYPE_CHECKING:
    from app_support.win32 import TaskbarApp

__all__ = ["CANCEL_HINT", "CAPTION", "Loading", "LoadingCanceled", "loading_screen"]

CAPTION = "Origenerator Loading"
CANCEL_HINT = "Press Esc to cancel opening Origenerator"


def loading_screen(icon: Path, preview: Preview | None,
                   steps: Sequence[str | tuple[str, float]], *,
                   app_id: str | None, taskbar: TaskbarApp | None) -> LoadingProcess:
    return LoadingProcess.open(caption=CAPTION, wordmark="Origenerator", icon=icon,
                               preview=preview, steps=steps, cancel_hint=CANCEL_HINT,
                               app_id=app_id, taskbar=taskbar)
