"""Reading a transcription: its words, and whether one of them is a word meant.

Every spoken-command matcher in this app opens the same way — the utterance cut
down to lowercase words, punctuation and case being whisper's invention rather
than the speaker's — and each one used to spell that out itself, in three
variants nothing explained. The variants are real: :func:`words` keeps
apostrophes where a matcher needs "don't" whole and digits where a command
names a number, and each call site now says which it needs.

Qt-free and dependency-free on purpose: the matchers that call it live in the
workflows and gallery packages as well as this one.
"""
from __future__ import annotations

import re


def words(text: str | None, *, keep_apostrophes: bool = False,
          keep_digits: bool = False) -> list[str]:
    """The lowercase words of a transcription.

    ``keep_apostrophes`` holds a contraction together — a matcher that splits
    "don't" into "don" and "t" can match the wrong command on the tail.
    ``keep_digits`` keeps a spoken number as a word of its own, for the
    commands that name one.
    """
    word = "[a-z']+" if keep_apostrophes else "[a-z]+"
    return re.findall(rf"{word}|\d+" if keep_digits else word, (text or "").lower())


def sounds_like(word: str, targets: tuple) -> bool:
    """Whether ``word`` is one of ``targets``, allowing a single substitution.

    Off a quiet mic the base model reliably lands the shape of a short word and
    misses a letter of it, so an exact test drops requests the speaker clearly
    made. Length still has to match, which is what keeps the tolerance from
    swallowing ordinary speech.
    """
    return any(
        word == target
        or (len(word) == len(target)
            and sum(a != b for a, b in zip(word, target)) == 1)
        for target in targets
    )
