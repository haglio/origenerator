from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QPlainTextEdit, QPushButton

from origenerator.gui.prompt_marks import problem_to_resolve

_GUARD_MS = 2500
DEFAULT_CAPTION = "Generate"
RANDOM_SEED_CAPTION = "Generate with Random seed"


class GenerateButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(DEFAULT_CAPTION, parent)
        self.setObjectName("generateBtn")
        self._caption = DEFAULT_CAPTION
        self._guard_timer = QTimer(self)
        self._guard_timer.setSingleShot(True)
        self._guard_timer.timeout.connect(self._clear_guard)

    def set_caption(self, text: str):
        self._caption = text
        if not self._guard_timer.isActive():
            self.setText(text)

    def flash_guard(self, message: str):
        self.setText(message)
        self._wear_warning(True)
        self._guard_timer.start(_GUARD_MS)

    def _clear_guard(self):
        self.setText(self._caption)
        self._wear_warning(False)

    def _wear_warning(self, warning: bool) -> None:
        self.setProperty("warning", warning)
        self.style().unpolish(self)
        self.style().polish(self)


def refused_over_prompts(button: GenerateButton, fields: Iterable[QPlainTextEdit]) -> bool:
    problem = problem_to_resolve(fields)
    if problem is not None:
        button.flash_guard(problem)
    return problem is not None
