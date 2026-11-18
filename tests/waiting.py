from __future__ import annotations

from collections.abc import Callable

from app_support.threading_utils import wait_until
from PySide6.QtWidgets import QApplication


def until(condition: Callable[[], object]) -> None:
    wait_until(condition, pump=QApplication.processEvents)
