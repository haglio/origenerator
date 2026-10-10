"""Origenerator's loading screen: the family's loading window under this app's name."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from shared_ui.loading_window import Loading, LoadingCanceled, LoadingWindow
from shared_ui.preview import Preview

__all__ = ["CANCEL_HINT", "CAPTION", "Loading", "LoadingCanceled", "loading_screen"]

CAPTION = "Origenerator Loading"
CANCEL_HINT = "Press Esc to cancel opening Origenerator"


def loading_screen(icon: Path, preview: Preview | None,
                   steps: Sequence[str | tuple[str, float]]) -> LoadingWindow:
    return LoadingWindow(caption=CAPTION, wordmark="Origenerator", icon=icon, preview=preview,
                         steps=steps, cancel_hint=CANCEL_HINT)
