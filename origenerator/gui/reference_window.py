from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QToolButton
from shared_ui.reference import ReferenceDialog

from origenerator.reference import reference_sections


class ReferenceWindow(QObject):
    def __init__(self, button: QToolButton) -> None:
        super().__init__(button)
        self._button = button
        self._dialog: ReferenceDialog | None = None
        button.toggled.connect(self._show)

    def _show(self, shown: bool) -> None:
        if not shown:
            if self._dialog is not None:
                self._dialog.close()
            return
        if self._dialog is None:
            self._dialog = ReferenceDialog(reference_sections(),
                                           icon=self._button.window().windowIcon())
            self._dialog.finished.connect(lambda _result: self._button.setChecked(False))
            self.destroyed.connect(self._dialog.deleteLater)
        self._dialog.show()
        self._dialog.raise_()
