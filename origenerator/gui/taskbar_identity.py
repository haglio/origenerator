from __future__ import annotations

import logging
from collections.abc import Callable

from app_support.win32 import TaskbarApp
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)


class TaskbarIdentity(QObject):
    """Dresses each window at its Show event, which Qt sends before mapping the
    window and so before Windows makes its taskbar button from what it wears."""

    def __init__(self, app: QApplication, own: str, own_app: TaskbarApp | None, *,
                 dress: Callable[[int, str, TaskbarApp | None], None],
                 described: Callable[[str], TaskbarApp | None]) -> None:
        super().__init__(app)
        self._own = self._wearing = (own, own_app)
        self._dress = dress
        self._described = described
        app.installEventFilter(self)

    @property
    def wearing(self) -> tuple[str, TaskbarApp | None]:
        return self._wearing

    def join(self, app_id: str) -> None:
        self._wearing = (app_id, self._described(app_id))

    def leave(self) -> None:
        self._wearing = self._own

    def eventFilter(self, watched, event):  # noqa: N802 -- Qt's name
        if (event.type() == QEvent.Type.Show and isinstance(watched, QWidget)
                and watched.isWindow()):
            try:
                self._dress(int(watched.winId()), *self._wearing)
            except OSError as refusal:
                logger.info("The taskbar keeps its own idea of %r: %s",
                            watched.windowTitle(), refusal)
        return False
