from __future__ import annotations

import os
from pathlib import Path

from app_support.win32 import mutex_name, try_acquire_mutex
from PyQt6.QtWidgets import QMessageBox


def claim_the_library(state_dir: Path) -> int | None:
    library = os.path.normcase(os.path.realpath(state_dir))
    return try_acquire_mutex(mutex_name("Global\\Origenerator", library))


def say_another_copy_is_running() -> None:
    QMessageBox.information(None, "Origenerator", "Another copy of Origenerator is already running.")
