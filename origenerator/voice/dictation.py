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

    @property
    def listening(self) -> bool:
        return self in (RequestState.OPENED, RequestState.COLLECTING)


OPENED = RequestState.OPENED
COLLECTING = RequestState.COLLECTING
COMPLETED = RequestState.COMPLETED
ABANDONED = RequestState.ABANDONED

# As Whisper renders the lead word; a hurried "request:" comes back in the trailing forms.
LEAD_WORDS = ("request", "requests", "requested")
_END_WORDS = ("over",)

_MAX_UTTERANCES = 8


def _without_leading_word(text: str) -> str:
    return re.sub(r"^\W*[\w']+\W*", "", text or "", count=1)


def _without_trailing_word(text: str) -> str:
    return re.sub(r"\W*[\w']+\W*$", "", text or "", count=1)


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
        if self._ends_the_request(heard):
            return self._finish(_without_trailing_word(body))
        self._parts = [body]
        return SpokenRequest(OPENED, _join(self._parts), _join(self._heard), self._opened_at)

    def _continue(self, text: str):
        self._heard.append(text)
        if self._ends_the_request(words(text, keep_apostrophes=True)):
            return self._finish(_join([*self._parts, _without_trailing_word(text)]))
        self._parts.append(text)
        if len(self._heard) >= self._max:
            given_up, opened_at = _join(self._heard), self._opened_at
            self.reset()
            return SpokenRequest(ABANDONED, "", given_up, opened_at)
        return SpokenRequest(COLLECTING, _join(self._parts), _join(self._heard), self._opened_at)

    @staticmethod
    def _ends_the_request(heard: list[str]) -> bool:
        return bool(heard) and sounds_like(heard[-1], _END_WORDS)

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
    return "Voice requests: request, over."
