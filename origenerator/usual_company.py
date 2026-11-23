from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from origenerator.prompt_checks import things_of

_FEWEST_TWINS = 3
_NEWEST_PROMPTS = 150
_SHARE_THAT_IS_USUAL = 1 / 3
_ALIKE_ENOUGH_TO_BE_A_TWIN = 0.5
_SHORTEST_WORD = 3
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_SAYING_NOTHING = frozenset({
    "the", "and", "with", "her", "his", "their", "its", "she", "they", "him", "them", "for", "from",
    "into", "onto", "that", "this", "are", "was", "very", "has", "have", "who", "whose", "while"})


@dataclass(frozen=True)
class UsualCompany:
    positive: tuple = ()
    negative: tuple = ()


@dataclass(frozen=True)
class _Read:
    positive: dict
    negative: dict
    things: frozenset

    @classmethod
    def of(cls, pair) -> _Read:
        positive = things_of(pair[0])
        return cls(positive, things_of(pair[1]), frozenset(positive))


def _alike(one: frozenset, other: frozenset) -> float:
    shared = len(one & other)
    return shared / (len(one) + len(other) - shared) if shared else 0.0


def _twin(prompt: _Read, without_it: list[_Read]) -> _Read | None:
    twin = max(without_it, key=lambda other: _alike(prompt.things, other.things), default=None)
    alike_enough = twin is not None and _alike(
        prompt.things, twin.things) >= _ALIKE_ENOUGH_TO_BE_A_TWIN
    return twin if alike_enough else None


def _usual(came_with_it: list[dict]) -> tuple:
    as_written: dict[str, str] = {}
    for came in came_with_it:
        for thing, written in came.items():
            as_written.setdefault(thing, written)
    times = Counter(thing for came in came_with_it for thing in came)
    return tuple(as_written[thing] for thing, count in times.most_common()
                 if count >= _FEWEST_TWINS and count / len(came_with_it) >= _SHARE_THAT_IS_USUAL)


def _words(thing: str) -> set[str]:
    return {word for word in _WORD.findall(thing.casefold())
            if len(word) >= _SHORTEST_WORD and word not in _SAYING_NOTHING}


def _usual_by_a_word(came_with_it: list[dict], named_already: tuple) -> tuple:
    as_written = {thing: written for came in reversed(came_with_it) for thing, written in came.items()}
    times = Counter(thing for came in came_with_it for thing in came)
    with_the_word = Counter(word for came in came_with_it
                            for word in set().union(*(_words(thing) for thing in came)))
    usually = [word for word, count in with_the_word.most_common()
               if count >= _FEWEST_TWINS and count / len(came_with_it) >= _SHARE_THAT_IS_USUAL]
    said = set().union(*(_words(thing) for thing in named_already))
    found = []
    for word in usually:
        saying_only_what_usually_came = [thing for thing in times
                                         if word in _words(thing) and _words(thing) <= set(usually)]
        if word in said or not saying_only_what_usually_came:
            continue
        commonest = max(saying_only_what_usually_came, key=times.__getitem__)
        found.append(as_written[commonest])
        said |= _words(commonest)
    return tuple(found)


def _only_in(one: dict, other: dict) -> dict:
    return {thing: written for thing, written in one.items() if thing not in other}


def usual_company(prompts, is_it) -> UsualCompany:
    read = [_Read.of(pair) for pair in prompts]
    has_it = [any(is_it(thing) for thing in prompt.positive) for prompt in read]
    with_it = [prompt for prompt, has in zip(read, has_it, strict=True) if has][-_NEWEST_PROMPTS:]
    without_it = [prompt for prompt, has in zip(read, has_it, strict=True) if not has]
    twins = [(prompt, twin) for prompt in with_it
             if (twin := _twin(prompt, without_it)) is not None]
    came = [_only_in(prompt.positive, twin.positive) for prompt, twin in twins]
    return UsualCompany(
        positive=(usual := _usual(came)) + _usual_by_a_word(came, usual),
        negative=_usual([_only_in(prompt.negative, twin.negative) for prompt, twin in twins
                         if prompt.negative and twin.negative]))
