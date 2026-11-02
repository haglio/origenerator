from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class RevisionWorker(QObject):
    revised = pyqtSignal(object, object)

    def __init__(self, apply_fn, parent=None):
        super().__init__(parent)
        self._apply = apply_fn

    @pyqtSlot(object, str, str, str, bool)
    def revise(self, context, positive: str, negative: str, request: str,
               in_scenes: bool = False) -> None:
        try:
            revision = self._apply(positive, negative, request, in_scenes=in_scenes)
        except Exception as exc:
            logger.warning("Could not work out a request (%s)", type(exc).__name__)
            revision = None
        self.revised.emit(context, revision)


class ReviseTask(QRunnable):
    def __init__(self, worker: RevisionWorker, *asked, in_scenes: bool):
        super().__init__()
        self._worker = worker
        self._asked = asked
        self._in_scenes = in_scenes

    def run(self):
        """Closing the window deletes the worker's C++ object, and the emit then raises on a pool thread, where Qt prints it into whatever runs next."""
        try:
            self._worker.revise(*self._asked, self._in_scenes)
        except RuntimeError:
            logger.info("The request's window closed before its answer came back")
