"""Ask the local LLM to widen a search query, off the GUI thread.

The deterministic tier of :mod:`origenerator.search` has already drawn results
by the time this is asked anything, so everything here is an improvement to a
view the user is looking at: it runs in a worker thread, it never blocks a
keystroke, and a failure is silence rather than an error — the results simply
stay as the table tier ranked them.

Answers are cached by query for the life of the window, because a query gets
re-asked constantly: backspacing a character and retyping it, or a gallery
rebuild landing while the same search is open, must not each cost a model call.
"""

import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import search
from origenerator.config import (
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    SEARCH_EXPANSION_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def _expand(query: str) -> dict:
    """The real widening, against the configured local endpoint."""
    return search.expand_query(
        query, base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
        system_prompt=SEARCH_EXPANSION_SYSTEM_PROMPT,
    )


class SearchExpander(QObject):
    """Widens search queries in the background, one call per distinct query."""

    # The query that was widened, and its ``{typed word: (related words,)}``.
    # Carries the query because a slow answer can land after the user has moved
    # on, and results widened for a query they are no longer running would be
    # results they cannot account for.
    expanded = pyqtSignal(str, object)

    def __init__(self, parent=None, *, expand=None):
        super().__init__(parent)
        self._expand = expand or _expand
        self._cache: dict[str, dict] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _key(query: str) -> str:
        """What counts as the same query: its search words, in order. Trailing
        spaces and stop words are not a new question to ask the model."""
        return " ".join(search.query_words(query))

    def cached(self, query: str) -> dict | None:
        """The widening already known for ``query``, or ``None``. Asks nothing and
        starts nothing: this is what a keystroke consults, so that typing costs
        lookups rather than a model call per character."""
        with self._lock:
            return self._cache.get(self._key(query))

    def request(self, query: str) -> dict | None:
        """The widening for ``query`` if it is already known, else ``None`` with
        a worker started to fetch it (and :attr:`expanded` emitted when it lands).

        A query already in flight starts nothing further — the pending call will
        answer it, and the view re-runs on whatever it returns.
        """
        key = self._key(query)
        if not key:
            return None
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            if key in self._in_flight:
                return None
            self._in_flight.add(key)
        threading.Thread(target=self._run, args=(query, key), daemon=True).start()
        return None

    def _run(self, query: str, key: str):
        try:
            expansions = self._expand(query)
        except Exception as exc:  # the worker must never take the app down with it
            logger.warning("search expansion failed for %r (%s)", query, exc)
            expansions = {}
        with self._lock:
            self._cache[key] = expansions
            self._in_flight.discard(key)
        # Emitted from the worker thread to a receiver in the GUI thread, so Qt
        # queues it — the view is only ever touched on its own thread.
        self.expanded.emit(query, expansions)
