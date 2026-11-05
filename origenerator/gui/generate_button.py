from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QPlainTextEdit, QPushButton

from origenerator.gui.prompt_marks import only_unread_emphasis_to_resolve, problem_to_resolve

_GUARD_MS = 2500
DEFAULT_CAPTION = "Generate"
RANDOM_SEED_CAPTION = "Generate with Random seed"
UNREAD_EMPHASIS_QUESTION = ("This model reads parentheses and numbers as plain text, "
                            "so they add no strength.")
REMOVE_EMPHASIS = "Remove emphasis"


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


def _wants_emphasis_removed(button: GenerateButton) -> bool:
    popup = QMessageBox(QMessageBox.Icon.Question, "Unread emphasis", UNREAD_EMPHASIS_QUESTION,
                        QMessageBox.StandardButton.NoButton, button.window())
    remove = popup.addButton(REMOVE_EMPHASIS, QMessageBox.ButtonRole.AcceptRole)
    popup.addButton(QMessageBox.StandardButton.Cancel)
    popup.setDefaultButton(remove)
    popup.exec()
    return popup.clickedButton() is remove


def refused_over_prompts(button: GenerateButton, fields: Iterable[QPlainTextEdit],
                         remove_emphasis: Callable[[], None]) -> bool:
    fields = list(fields)
    if only_unread_emphasis_to_resolve(fields):
        if _wants_emphasis_removed(button):
            remove_emphasis()
        return True
    problem = problem_to_resolve(fields)
    if problem is not None:
        button.flash_guard(problem)
    return problem is not None
