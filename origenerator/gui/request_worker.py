"""Working out what a spoken request changes, off the UI thread.

Applying a request is arithmetic on two strings until the prompt doesn't happen
to contain the words the speaker used — at which point the local LLM is asked
which of the prompt's own terms they meant, and that is a second or two of
network wait. On the UI thread that is a second or two of frozen slideshow,
mid-sentence, which is the one moment the app must not stutter.

So the whole revision runs on the global pool, as an utterance's transcription
already does, and comes back through a signal. :class:`RevisionWorker` carries
one injected ``apply`` callable so the flow unit-tests inline, without a model
or a server; :class:`ReviseTask` is one run of it on the pool.
"""

import logging

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class RevisionWorker(QObject):
    # (context, revision-or-None) — the caller's own context handed straight
    # back, so it can pick up where it left off without holding state here.
    revised = pyqtSignal(object, object)

    def __init__(self, apply_fn, parent=None):
        super().__init__(parent)
        self._apply = apply_fn

    @pyqtSlot(object, str, str, str)
    def revise(self, context, positive: str, negative: str, request: str) -> None:
        """Work out what ``request`` does to the prompt pair and emit it.

        Never raises: a model that is down or answers nonsense is the ordinary
        case here, not an error — the request is still applied, just by the
        words alone. A revision of ``None`` means the request named nothing to
        act on, which the caller says out loud.
        """
        try:
            revision = self._apply(positive, negative, request)
        except Exception as exc:
            logger.warning("Could not work out the request %r: %s", request, exc)
            revision = None
        self.revised.emit(context, revision)


class ReviseTask(QRunnable):
    """Runs one ``RevisionWorker.revise`` off the UI thread; the worker's signal
    carries the result back to the thread that owns it."""

    def __init__(self, worker: RevisionWorker, context, positive: str,
                 negative: str, request: str):
        super().__init__()
        self._worker = worker
        self._context = context
        self._positive = positive
        self._negative = negative
        self._request = request

    def run(self):
        self._worker.revise(self._context, self._positive, self._negative,
                            self._request)
