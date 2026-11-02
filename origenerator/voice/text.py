from __future__ import annotations

import re


def words(text: str | None, *, keep_apostrophes: bool = False,
          keep_digits: bool = False) -> list[str]:
    word = "[a-z']+" if keep_apostrophes else "[a-z]+"
    return re.findall(rf"{word}|\d+" if keep_digits else word, (text or "").lower())


def sounds_like(word: str, targets: tuple) -> bool:
    """Off a quiet mic the base Whisper model lands the shape of a short word and misses a letter of it, so one substitution is allowed at the same length."""
    return any(
        word == target
        or (len(word) == len(target)
            and sum(a != b for a, b in zip(word, target, strict=True)) == 1)
        for target in targets
    )
