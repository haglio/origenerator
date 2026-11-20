from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from origenerator.prompt_terms import bare_terms

_FEWEST_PROMPTS = 3
_SHARE_THAT_IS_USUAL = 0.5
_TIMES_AS_COMMON_AS_ELSEWHERE = 2


@dataclass(frozen=True)
class UsualCompany:
    positive: tuple = ()
    negative: tuple = ()


def _parts(prompt: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for part in bare_terms(prompt or ""):
        if part.strip():
            parts.setdefault(part.strip().lower(), part.strip())
    return parts


def _usual(with_it: list[str], without_it: list[str]) -> tuple:
    as_written: dict[str, str] = {}
    there: Counter = Counter()
    for prompt in with_it:
        parts = _parts(prompt)
        there.update(parts.keys())
        for key, part in parts.items():
            as_written.setdefault(key, part)
    elsewhere = Counter(key for prompt in without_it for key in _parts(prompt))

    def share_elsewhere(key: str) -> float:
        return elsewhere[key] / len(without_it) if without_it else 0.0

    return tuple(as_written[key] for key, count in there.most_common()
                 if count / len(with_it) >= max(_SHARE_THAT_IS_USUAL,
                                                _TIMES_AS_COMMON_AS_ELSEWHERE * share_elsewhere(key)))


def usual_company(prompts, has_it) -> UsualCompany:
    pairs = list(prompts)
    with_it = [pair for pair in pairs if has_it(pair[0])]
    without_it = [pair for pair in pairs if not has_it(pair[0])]
    if len(with_it) < _FEWEST_PROMPTS:
        return UsualCompany()
    return UsualCompany(
        positive=_usual([positive for positive, _negative in with_it],
                        [positive for positive, _negative in without_it]),
        negative=_usual([negative for _positive, negative in with_it],
                        [negative for _positive, negative in without_it]))
