from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from origenerator.voice.text import sounds_like, words


class RequestState(Enum):
    OPENED = "opened"
    COLLECTING = "collecting"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    CANCELED = "canceled"

    @property
    def listening(self) -> bool:
        return self in (RequestState.OPENED, RequestState.COLLECTING)


OPENED = RequestState.OPENED
COLLECTING = RequestState.COLLECTING
COMPLETED = RequestState.COMPLETED
ABANDONED = RequestState.ABANDONED
CANCELED = RequestState.CANCELED

# As Whisper renders the lead word; a hurried "request:" comes back in the trailing forms.
LEAD_WORDS = ("request", "requests", "requested")
SUBMIT_WORD = "submit"
RETRY_WORD = "retry"
CANCEL_WORD = "cancel"

_MAX_UTTERANCES = 8


def _without_leading_word(text: str) -> str:
    return re.sub(r"^\W*[\w']+\W*", "", text or "", count=1)


def _without_trailing_word(text: str) -> str:
    return re.sub(r"\W*[\w']+\W*$", "", text or "", count=1)


def _ends_on(heard: list[str], marker: str) -> bool:
    return bool(heard) and sounds_like(heard[-1], (marker,))


def _join(parts: list) -> str:
    return " ".join(part for part in (p.strip() for p in parts) if part)


@dataclass(frozen=True)
class SpokenRequest:
    state: RequestState
    text: str
    heard: str
    opened_at: float | None = None

    @property
    def listening(self) -> bool:
        return self.state.listening


class RequestDictation:
    def __init__(self, *, max_utterances: int = _MAX_UTTERANCES):
        self._max = max_utterances
        self._parts: list[str] = []
        self._heard: list[str] = []
        self._open = False
        self._opened_at: float | None = None

    @property
    def listening(self) -> bool:
        return self._open

    def reset(self) -> None:
        self._parts = []
        self._heard = []
        self._open = False
        self._opened_at = None

    def push(self, text: str, *, spoken_at: float | None = None):
        if not self._open:
            return self._maybe_open(text, spoken_at)
        return self._continue(text)

    def _maybe_open(self, text: str, spoken_at: float | None):
        heard = words(text, keep_apostrophes=True)
        if not heard or not sounds_like(heard[0], LEAD_WORDS):
            return None
        self._open = True
        self._opened_at = spoken_at
        self._heard = [text]
        body = _without_leading_word(text)
        marked = self._ended_on_a_marker(heard, text, _without_trailing_word(body))
        if marked is not None:
            return marked
        self._parts = [body]
        return SpokenRequest(OPENED, _join(self._parts), _join(self._heard), self._opened_at)

    def _continue(self, text: str):
        self._heard.append(text)
        marked = self._ended_on_a_marker(words(text, keep_apostrophes=True), text,
                                         _join([*self._parts, _without_trailing_word(text)]))
        if marked is not None:
            return marked
        self._parts.append(text)
        if len(self._heard) >= self._max:
            given_up, opened_at = _join(self._heard), self._opened_at
            self.reset()
            return SpokenRequest(ABANDONED, "", given_up, opened_at)
        return SpokenRequest(COLLECTING, _join(self._parts), _join(self._heard), self._opened_at)

    def _ended_on_a_marker(self, heard: list[str], text: str, submitted: str):
        if _ends_on(heard, CANCEL_WORD):
            return self._cancel()
        if _ends_on(heard, RETRY_WORD):
            return self._retry(text)
        if _ends_on(heard, SUBMIT_WORD):
            return self._finish(submitted)
        return None

    def _retry(self, text: str):
        self._parts = []
        self._heard = [text]
        return SpokenRequest(COLLECTING, "", text, self._opened_at)

    def _cancel(self):
        heard, opened_at = _join(self._heard), self._opened_at
        self.reset()
        return SpokenRequest(CANCELED, "", heard, opened_at)

    def _finish(self, body: str):
        heard, opened_at = _join(self._heard), self._opened_at
        self.reset()
        return SpokenRequest(COMPLETED, body.strip(), heard, opened_at)


def request_words(heard: str) -> str:
    return _without_trailing_word(_without_leading_word(heard)).strip()


def words_of(record: dict | None) -> str:
    if not record:
        return ""
    if record.get("asked") is not None:
        return record["asked"]
    return request_words(record.get("heard") or "")


def request_bias() -> str:
    # A short marker word off a quiet mic comes back as something else unless Whisper is told to expect it.
    return f"Voice requests: request, {SUBMIT_WORD}, {RETRY_WORD}, {CANCEL_WORD}."
