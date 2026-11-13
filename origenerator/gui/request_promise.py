from __future__ import annotations


class RequestPromise:
    def __init__(self) -> None:
        self.note = ""
        self._request = None

    def make(self, note: str, request) -> None:
        self.note, self._request = note, request

    def keep(self, request) -> str:
        if request is not self._request:
            return ""
        kept, self.note, self._request = self.note, "", None
        return kept
