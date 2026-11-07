from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QPushButton


class ActionButton(QPushButton):
    def __init__(self, action: QAction, *, name: str):
        super().__init__(action.text())
        self.setObjectName(name)
        self._action = action
        self.clicked.connect(lambda _checked=False: action.trigger())
        action.changed.connect(self._follow)
        self._follow()

    def _follow(self) -> None:
        self.setVisible(self._action.isVisible())
        self.setEnabled(self._action.isEnabled())
        self.setToolTip(self._action.toolTip())
