"""Dictating a spoken request across as many utterances as it takes.

"Request … over" is the one voice input that isn't a single breath: the user
opens with the word *request*, says as much as they like — pausing wherever they
like — and closes with *over*. The mic endpoints on silence, so every one of
those pauses ends an utterance and starts another; a matcher that only ever saw
one utterance at a time could not hear a sentence spoken in three.

So :class:`RequestDictation` is a state machine over the transcriptions. Idle, it
ignores everything that doesn't open with the lead word. Open, it swallows every
utterance — which is what keeps the words of a request from also steering the
loop's prompt or matching a "fix …" command — until one ends on the terminator.

Pure and text-driven: no mic, no Qt, no model. :class:`~origenerator.voice.
steering.VoiceSteering` owns one and feeds it each transcription.
"""

import re
from dataclasses import dataclass

# The states a fed transcription can put the dictation in. OPENED and COLLECTING
# both mean "still listening"; the caller shows them and waits. COMPLETED carries
# the whole request; ABANDONED means the terminator never came.
OPENED = "opened"
COLLECTING = "collecting"
COMPLETED = "completed"
ABANDONED = "abandoned"

# What opens a request, as whisper renders it. "Request" is distinctive enough
# that one substitution is safe (the same tolerance the fix matcher allows its
# lead word), and the trailing forms are what a hurried "request:" comes back as.
_LEAD_WORDS = ("request", "requests", "requested")
# What closes one. Radio's own word, chosen because nothing in a prompt ends on
# it by accident — and matched only as an utterance's LAST word, so "the blanket
# over her legs" carries on rather than cutting the request short there.
_END_WORDS = ("over",)

# How many utterances an open request may run to before it is given up on. The
# failure this guards is whisper missing the "over": without a cap the dictation
# would swallow every later utterance for the rest of the session, and the user
# would have no way to tell why nothing they said was landing. Eight is a long
# request and a short hostage-taking.
_MAX_UTTERANCES = 8


def _words(text: str) -> list[str]:
    """The lowercase words of a transcription, punctuation and case dropped —
    both are whisper's invention rather than the speaker's."""
    return re.findall(r"[a-z']+", (text or "").lower())


def _is_one_of(word: str, targets: tuple) -> bool:
    """Whether ``word`` is one of ``targets``, allowing a single substitution.

    Off a quiet mic the base model reliably lands the shape of a word and misses
    a letter of it, so an exact test drops requests the speaker clearly made.
    Length still has to match, which is what keeps the tolerance from swallowing
    ordinary speech.
    """
    return any(
        word == target
        or (len(word) == len(target)
            and sum(a != b for a, b in zip(word, target)) == 1)
        for target in targets
    )


def _strip_leading_word(text: str) -> str:
    """``text`` without its first word and whatever punctuation followed it."""
    return re.sub(r"^\W*[\w']+\W*", "", text or "", count=1)


def _strip_trailing_word(text: str) -> str:
    """``text`` without its last word and whatever punctuation surrounded it."""
    return re.sub(r"\W*[\w']+\W*$", "", text or "", count=1)


def _join(parts: list) -> str:
    """The collected pieces as one line, blank pieces dropped."""
    return " ".join(part for part in (p.strip() for p in parts) if part)


@dataclass(frozen=True)
class SpokenRequest:
    """Where an in-progress (or just-finished) request stands.

    ``text`` is the request itself — the words between the markers, which is what
    gets acted on. ``heard`` is every transcription that went into it, markers
    and all: what the user actually said, kept verbatim so a request that came
    out wrong shows *why* rather than just being wrong.
    """

    state: str
    text: str
    heard: str

    @property
    def listening(self) -> bool:
        """Whether the dictation is still open and expecting more."""
        return self.state in (OPENED, COLLECTING)


class RequestDictation:
    """Collects "Request … over" out of a stream of transcriptions.

    :meth:`push` takes one transcription and answers what it meant: ``None`` for
    an utterance that isn't part of a request (the caller's other uses of the mic
    get it), or a :class:`SpokenRequest` saying the request opened, is still
    collecting, finished, or was given up on.
    """

    def __init__(self, *, max_utterances: int = _MAX_UTTERANCES):
        self._max = max_utterances
        self._parts: list[str] = []  # the request body, one utterance per entry
        self._heard: list[str] = []  # what was transcribed, markers included
        self._open = False

    @property
    def listening(self) -> bool:
        """Whether a request is open right now — the cue to hold a slideshow."""
        return self._open

    def reset(self) -> None:
        """Forget an open request. The mic closing calls this: a request nobody
        can finish saying must not be waiting the next time it opens."""
        self._parts = []
        self._heard = []
        self._open = False

    def push(self, text: str):
        """Feed one transcription; see the class docstring for the answers."""
        if not self._open:
            return self._maybe_open(text)
        return self._continue(text)

    def _maybe_open(self, text: str):
        words = _words(text)
        if not words or not _is_one_of(words[0], _LEAD_WORDS):
            return None  # not a request — the caller's other uses may have it
        self._open = True
        self._heard = [text]
        body = _strip_leading_word(text)
        # "Request, no silver earrings, over" is a whole request in one breath, so
        # the opening utterance is checked for the terminator like any other.
        if self._ends_the_request(words):
            return self._finish(_strip_trailing_word(body))
        self._parts = [body]
        return SpokenRequest(OPENED, _join(self._parts), _join(self._heard))

    def _continue(self, text: str):
        self._heard.append(text)
        words = _words(text)
        if self._ends_the_request(words):
            return self._finish(_join(self._parts + [_strip_trailing_word(text)]))
        self._parts.append(text)
        if len(self._heard) >= self._max:
            heard = _join(self._heard)
            self.reset()
            return SpokenRequest(ABANDONED, "", heard)
        return SpokenRequest(COLLECTING, _join(self._parts), _join(self._heard))

    @staticmethod
    def _ends_the_request(words: list[str]) -> bool:
        """Whether an utterance's last word closes the request. Only the last:
        "over" is an ordinary English word in the middle of a sentence and a
        deliberate sign-off at the end of one."""
        return bool(words) and _is_one_of(words[-1], _END_WORDS)

    def _finish(self, body: str):
        heard = _join(self._heard)
        self.reset()
        return SpokenRequest(COMPLETED, body.strip(), heard)


def request_bias() -> str:
    """The request markers as whisper's initial prompt.

    The same trick the fix commands need: a short marker word off a quiet mic
    comes back as something else entirely unless the model is told to expect it,
    and the whole feature hangs on hearing exactly these two words.
    """
    return "Voice requests: request, over."
