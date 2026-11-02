from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import search
from origenerator.config import LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL
from origenerator.gui.off_thread import run_off_thread
from origenerator.prompts import SEARCH_EXPANSION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _expand(query: str) -> dict:
    return search.expand_query(
        query, base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
        system_prompt=SEARCH_EXPANSION_SYSTEM_PROMPT,
    )


class SearchExpander(QObject):
    expanded = pyqtSignal(str, object)

    def __init__(self, parent=None, *, expand=None):
        super().__init__(parent)
        self._expand = expand or _expand
        self._cache: dict[str, dict] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(search.query_words(query))

    def unanswered(self, query: str) -> bool:
        key = self._key(query)
        with self._lock:
            return bool(key) and key not in self._cache

    def same_words(self, query: str, other: str) -> bool:
        return self._key(query) == self._key(other)

    def cached(self, query: str) -> dict | None:
        with self._lock:
            return self._cache.get(self._key(query))

    def request(self, query: str) -> dict | None:
        key = self._key(query)
        if not key:
            return None
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            if key in self._in_flight:
                return None
            self._in_flight.add(key)
        run_off_thread(lambda: self._widened(query),
                       lambda expansions: self._landed(query, key, expansions),
                       owner=self)
        return None

    def _widened(self, query: str) -> dict:
        try:
            return self._expand(query)
        except Exception as exc:
            logger.warning("search expansion failed for %r (%s)", query, exc)
            return {}

    def _landed(self, query: str, key: str, expansions) -> None:
        expansions = expansions or {}
        with self._lock:
            self._cache[key] = expansions
            self._in_flight.discard(key)
        self.expanded.emit(query, expansions)
