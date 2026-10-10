from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from shared_ui.loading_window import LoadingWindow


class LoadingScreenInThisProcess(LoadingWindow):
    shown = pyqtSignal(int)

    def __init__(self, *, app_id, taskbar, **window) -> None:
        super().__init__(**window)
        self.wearing = (app_id, taskbar)
        self.show()


def opened_here(screens: list):
    def open_here(**opened):
        screens.append(LoadingScreenInThisProcess(**opened))
        return screens[-1]

    return open_here
